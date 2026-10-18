import hashlib
import io
import json
import struct
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import wave
import zipfile

import music_extras as m


def record(**overrides):
    value = {'trackName': 'Track', 'artistName': 'Artist', 'albumName': 'Album',
             'duration': 180, 'syncedLyrics': '[00:01.00] test fixture', 'plainLyrics': None}
    value.update(overrides)
    return value


class LyricsTests(unittest.TestCase):
    def test_strict_identity_duration_and_versions(self):
        song = m.Track(Path('song.flac'), 'Track', 'Artist', 'Album', 180)
        good = record()
        bad = [record(trackName='Track (Live)'), record(artistName='Other'), record(albumName='Live'), record(duration=185)]
        self.assertIs(m.choose_lyrics(song, bad + [good])[0], good)
        self.assertIsNone(m.choose_lyrics(song, bad)[0])
        self.assertIsNone(m.choose_lyrics(m.Track(song.path, song.title), [good])[0])
        self.assertIsNone(m.choose_lyrics(song, [good, record(syncedLyrics='different version')])[0])

    def test_sidecars_and_music_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'song.flac'
            path.write_bytes(b'music-do-not-change')
            song = m.Track(path, 'Track', 'Artist')
            self.assertIn('.lrc', m.save_lyrics(song, record()))
            self.assertEqual(path.with_suffix('.lrc').read_text('utf-8'), '[00:01.00] test fixture\n')
            self.assertIn('保留', m.save_lyrics(song, record(syncedLyrics='overwrite')))
            self.assertEqual(path.read_bytes(), b'music-do-not-change')
            path.with_suffix('.lrc').unlink()
            self.assertIn('.txt', m.save_lyrics(song, record(syncedLyrics=None, plainLyrics='plain fixture')))
            self.assertIn('保留', m.save_lyrics(song, record()))

    def test_instrumental_does_not_create_empty_sidecar(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'song.wav'
            self.assertIn('纯音乐', m.save_lyrics(m.Track(path, 'Track'), record(instrumental=True)))
            self.assertFalse(path.with_suffix('.lrc').exists())

    def test_filename_and_real_audio_tags(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '01. Artist - Track_abcdef1234.wav'
            with wave.open(str(path), 'wb') as audio:
                audio.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
                audio.writeframes(b'\0\0' * 8000)
            track = m.read_track(path)
            self.assertEqual((track.artist, track.title, track.duration), ('Artist', 'Track', 1))
            if m.TinyTag:
                info = b'INFO'
                for key, value in [(b'INAM', b'Tagged title\0'), (b'IART', b'Tagged artist\0'), (b'IPRD', b'Tagged album\0')]:
                    info += key + struct.pack('<I', len(value)) + value + (b'\0' if len(value) % 2 else b'')
                raw = path.read_bytes() + b'LIST' + struct.pack('<I', len(info)) + info
                path.write_bytes(raw[:4] + struct.pack('<I', len(raw)-8) + raw[8:])
                track = m.read_track(path)
                self.assertEqual((track.title, track.artist, track.album), ('Tagged title', 'Tagged artist', 'Tagged album'))

    def test_auto_cancel_and_existing_do_not_query(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(m, 'search_lyrics') as search:
            path = Path(folder) / 'Artist - Track.flac'
            stop = threading.Event()
            stop.set()
            self.assertEqual(m.auto_lyrics(path, stop), '已停止')
            stop.clear()
            path.with_suffix('.lrc').write_text('existing')
            self.assertIn('保留', m.auto_lyrics(path, stop))
            search.assert_not_called()

    def test_auto_unambiguous_match_only(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(m, 'search_lyrics', return_value=[record()]):
            path = Path(folder) / 'Artist - Track.flac'
            self.assertIn('.lrc', m.auto_lyrics(path, threading.Event()))
            self.assertTrue(path.with_suffix('.lrc').exists())


class BaiduTests(unittest.TestCase):
    def test_share_validation_and_code(self):
        self.assertEqual(m.baidu_share('https://pan.baidu.com/share/init?surl=abcd&pwd=AB12'), ('https://pan.baidu.com/s/1abcd', 'AB12'))
        self.assertEqual(m.baidu_share('https://yun.baidu.com/s/1abcd?pwd=AB12', 'xy34')[1], 'xy34')
        for url in ['https://pan.baidu.com.evil/s/1abc', 'file:///test', 'https://pan.baidu.com/s/--help', 'https://user@pan.baidu.com/s/1abc']:
            with self.assertRaises(ValueError):
                m.baidu_share(url)
        with self.assertRaises(ValueError):
            m.baidu_share('https://pan.baidu.com/s/1abc', '--exec=bad')

    def test_zero_exit_error_is_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(RuntimeError):
                m.run_pcs(sys.executable, ['-c', "print('failed: fixture')"], folder, threading.Event())

    def test_zero_uid_is_not_a_logged_in_account(self):
        with patch.object(m, 'run_pcs', return_value='当前帐号 uid: 0, 用户名: '), self.assertRaises(RuntimeError):
            m.check_pcs_login('fixture.exe', 'fixture-config', threading.Event())
        with patch.object(m, 'run_pcs', return_value='当前帐号 uid: 123456, 用户名: fixture'):
            self.assertEqual(m.check_pcs_login('fixture.exe', 'fixture-config', threading.Event()), '123456')

    def test_subprocess_timeout_and_cancellation(self):
        with tempfile.TemporaryDirectory() as folder:
            started = time.monotonic()
            with self.assertRaises(TimeoutError):
                m.run_pcs(sys.executable, ['-c', 'import time; time.sleep(30)'], folder, threading.Event(), timeout=0.2)
            self.assertLess(time.monotonic() - started, 3)
            stop = threading.Event()
            timer = threading.Timer(0.2, stop.set)
            timer.start()
            try:
                with self.assertRaises(m.Cancelled):
                    m.run_pcs(sys.executable, ['-c', 'import time; time.sleep(30)'], folder, stop)
            finally:
                timer.cancel()

    def test_bridge_isolates_share_and_resumes_without_transfer(self):
        calls = []
        item = {'url': 'https://pan.baidu.com/s/1fixture', 'code': 'AB12'}
        with tempfile.TemporaryDirectory() as folder:
            def run(exe, args, config, cancel, **kwargs):
                calls.append(args)
                if args[0] == 'who':
                    return 'uid: 123456'
                if args[0] == 'download':
                    output = Path(args[2]) / 'Artist - Track.flac'
                    output.write_bytes(b'audio fixture')
                return '成功'
            with patch.object(m, 'run_pcs', side_effect=run):
                first = m.download_baidu('fixture.exe', item, folder, Path(folder)/'config', threading.Event())
                second = m.download_baidu('fixture.exe', item, folder, Path(folder)/'config', threading.Event())
            self.assertEqual(first, second)
            self.assertEqual(sum(c[0] == 'transfer' for c in calls), 1)
            downloads = [c for c in calls if c[0] == 'download']
            self.assertTrue(all(c[-1].startswith('/拾音下载/') and c[-1] != '/' for c in downloads))
            self.assertFalse(any(c[0] in ('rm', 'share', 'upload') for c in calls))

    def test_no_download_after_uncertain_transfer(self):
        calls = []
        with tempfile.TemporaryDirectory() as folder:
            def run(exe, args, *a, **kw):
                calls.append(args[0])
                if args[0] == 'who':
                    return 'uid: 123456'
                return 'unknown' if args[0] == 'transfer' else 'ok'
            with patch.object(m, 'run_pcs', side_effect=run), self.assertRaises(RuntimeError):
                m.download_baidu('fixture.exe', {'url':'https://pan.baidu.com/s/1abc'}, folder, Path(folder)/'config', threading.Event())
            self.assertNotIn('download', calls)

    def test_installer_checksum_and_zip_path_safety(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('../../BaiduPCS-Go.exe', b'MZ-fixture')
        raw = archive.getvalue()
        release = {'tag_name':'v4.fixture', 'assets':[{'name':'BaiduPCS-Go-v4-windows-x64.zip',
                   'digest':'sha256:' + hashlib.sha256(raw).hexdigest(),
                   'browser_download_url':m.PCS_REPO+'/releases/download/v4.fixture/tool.zip'}]}
        with tempfile.TemporaryDirectory() as folder, patch.object(m.platform, 'machine', return_value='AMD64'), patch.object(m, 'get_json', return_value=release):
            with patch.object(m.ur, 'urlopen', return_value=io.BytesIO(raw)):
                path, version = m.install_pcs(folder)
            self.assertEqual(path.parent.parent, Path(folder))
            self.assertEqual(path.read_bytes(), b'MZ-fixture')
            release['assets'][0]['digest'] = 'sha256:' + '0'*64
            with patch.object(m.ur, 'urlopen', return_value=io.BytesIO(raw)), self.assertRaises(ValueError):
                m.install_pcs(folder)


if __name__ == '__main__':
    unittest.main()
