"""Lyrics sidecars and an isolated BaiduPCS-Go subprocess bridge."""
from dataclasses import dataclass, replace
from pathlib import Path
import hashlib
import io
import json
import os
import platform
import queue
import re
import subprocess
import threading
import time
import unicodedata
import urllib.parse as up
import urllib.request as ur
import wave
import zipfile

try:
    from tinytag import TinyTag, TinyTagException
except ImportError:
    TinyTag = None

UA = 'Shiyin/1.6 (+https://github.com/css770/shiyin-music)'
AUDIO_EXTS = {'.flac', '.ape', '.wav', '.mp3', '.m4a', '.alac', '.aiff', '.aif', '.wv', '.tta', '.ogg', '.opus', '.dsf', '.dff', '.tak'}
PCS_REPO = 'https://github.com/qjfoidnh/BaiduPCS-Go'


@dataclass(frozen=True)
class Track:
    path: Path
    title: str
    artist: str = ''
    album: str = ''
    duration: float = 0


def read_track(path):
    path = Path(path)
    name = re.sub(r'_[0-9a-f]{10}$', '', path.stem)
    name = re.sub(r'^\d{1,3}[.、 _-]+', '', name).strip()
    parts = re.split(r'\s+[-–—]\s+', name, maxsplit=1)
    track = Track(path, parts[-1], parts[0] if len(parts) == 2 else '')
    if TinyTag:
        try:
            audio = TinyTag.get(path)
            return replace(track, title=audio.title or track.title, artist=audio.artist or track.artist,
                           album=audio.album or '', duration=float(audio.duration or 0))
        except (OSError, ValueError, TinyTagException):
            pass
    if path.suffix.lower() == '.wav':
        try:
            with wave.open(str(path)) as audio:
                track = replace(track, duration=audio.getnframes() / audio.getframerate())
        except (OSError, wave.Error, EOFError):
            pass
    return track


def identity(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', str(text)).casefold() if c.isalnum())


def get_json(url, limit=3 * 1024 * 1024):
    with ur.urlopen(ur.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'}), timeout=18) as response:
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('接口返回内容过大')
    return json.loads(raw)


def search_lyrics(track):
    if not track.title.strip():
        raise ValueError('缺少歌名')
    params = {'track_name': track.title.strip()}
    if track.artist.strip():
        params['artist_name'] = track.artist.strip()
    records = get_json('https://lrclib.net/api/search?' + up.urlencode(params))
    if not isinstance(records, list):
        raise ValueError('歌词接口返回格式异常')
    return [r for r in records if isinstance(r, dict) and r.get('trackName') and
            (r.get('syncedLyrics') or r.get('plainLyrics') or r.get('instrumental'))]


def choose_lyrics(track, records):
    """Only auto-save an exact title/artist, compatible album and duration."""
    if not track.artist:
        return None, '缺少歌手，请手动匹配'
    candidates = []
    for record in records:
        if identity(record.get('trackName', '')) != identity(track.title):
            continue
        if identity(record.get('artistName', '')) != identity(track.artist):
            continue
        if track.album and identity(record.get('albumName', '')) != identity(track.album):
            continue
        try:
            delta = abs(float(record.get('duration') or 0) - track.duration)
        except (ValueError, TypeError):
            continue
        if track.duration and delta > 3:
            continue
        candidates.append((delta if track.duration else 0, record))
    if not candidates:
        return None, '未找到可靠匹配，可手动搜索'
    candidates.sort(key=lambda c: c[0])
    nearest = [r for delta, r in candidates if delta <= candidates[0][0] + 1]
    signatures = {(r.get('syncedLyrics'), r.get('plainLyrics'), bool(r.get('instrumental'))) for r in nearest}
    if len(signatures) > 1:
        return None, '存在多个版本，请手动选择'
    return candidates[0][1], ''


def sidecar_exists(path):
    path = Path(path)
    return any(path.with_suffix(ext).exists() for ext in ('.lrc', '.txt'))


def save_lyrics(track, record):
    if sidecar_exists(track.path):
        return '已有歌词（保留）'
    if record.get('instrumental'):
        return '纯音乐（无歌词）'
    content = record.get('syncedLyrics') or record.get('plainLyrics')
    if not isinstance(content, str) or not content.strip():
        return '未返回歌词'
    target = track.path.with_suffix('.lrc' if record.get('syncedLyrics') else '.txt')
    # Exclusive creation protects existing sidecars even if two tasks race.
    try:
        with target.open('x', encoding='utf-8', newline='\n') as output:
            output.write(content.rstrip() + '\n')
    except FileExistsError:
        return '已有歌词（保留）'
    return '已保存 ' + target.suffix


def auto_lyrics(path, cancel):
    if cancel.is_set():
        return '已停止'
    if sidecar_exists(path):
        return '已有歌词（保留）'
    track = read_track(path)
    if not track.artist:
        return '缺少歌手，请手动匹配'
    record, reason = choose_lyrics(track, search_lyrics(track))
    if cancel.is_set():
        return '已停止'
    return save_lyrics(track, record) if record else reason


def audio_files(folder):
    for path in Path(folder).rglob('*'):
        if path.is_file() and path.suffix.lower() in AUDIO_EXTS and not path.is_symlink():
            yield path


def install_pcs(folder):
    """Install only the official Windows asset with its published SHA-256."""
    arch = 'arm64' if platform.machine().lower() in ('arm64', 'aarch64') else 'x64' if platform.machine().endswith('64') else 'x86'
    release = get_json('https://api.github.com/repos/qjfoidnh/BaiduPCS-Go/releases/latest')
    asset = next((a for a in release['assets'] if a['name'].endswith(f'-windows-{arch}.zip')), None)
    if not asset or not re.fullmatch(r'sha256:[0-9a-f]{64}', asset.get('digest', '')):
        raise ValueError('未找到带 SHA-256 校验值的官方 Windows 版本，请手动选择工具')
    url = asset['browser_download_url']
    if not url.startswith(PCS_REPO + '/releases/download/'):
        raise ValueError('工具下载地址不属于指定的官方仓库')
    with ur.urlopen(ur.Request(url, headers={'User-Agent': UA}), timeout=30) as response:
        raw = response.read(64 * 1024 * 1024 + 1)
    if len(raw) > 64 * 1024 * 1024 or 'sha256:' + hashlib.sha256(raw).hexdigest() != asset['digest']:
        raise ValueError('工具校验失败，未安装')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        member = next((m for m in archive.infolist() if Path(m.filename).name == 'BaiduPCS-Go.exe'), None)
        if not member or member.file_size > 96 * 1024 * 1024:
            raise ValueError('压缩包中没有有效的 BaiduPCS-Go.exe')
        # No extractall: zip paths can never write outside the chosen directory.
        binary = archive.read(member)
    version = re.sub(r'[^a-zA-Z0-9._-]', '_', release['tag_name'])
    target = Path(folder) / version / 'BaiduPCS-Go.exe'
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    temporary.write_bytes(binary)
    temporary.replace(target)
    return target, release['tag_name']


def pcs_env(config_dir):
    env = os.environ.copy()
    Path(config_dir).mkdir(parents=True, exist_ok=True)
    env['BAIDUPCS_GO_CONFIG_DIR'] = str(Path(config_dir).resolve())
    env.pop('BAIDUPCS_GO_VERBOSE', None)
    return env


class Cancelled(Exception):
    pass


def check_pcs_login(executable, config_dir, cancel):
    text = run_pcs(executable, ['who'], config_dir, cancel, timeout=30)
    match = re.search(r'uid\s*[:：]\s*([1-9]\d*)\b', text, re.I)
    if not match:
        raise RuntimeError('百度工具尚未登录有效账号，请在账号终端完成登录')
    return match[1]


def run_pcs(executable, args, config_dir, cancel, timeout=180, progress=None):
    """No shell, no credentials in argv/logs; terminate the exact child on cancel."""
    if cancel.is_set():
        raise Cancelled('已停止')
    process = subprocess.Popen([str(executable), *args], env=pcs_env(config_dir), stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    lines = queue.Queue()
    def reader():
        try:
            for line in iter(process.stdout.readline, b''):
                lines.put(line)
        finally:
            lines.put(None)
    threading.Thread(target=reader, daemon=True).start()
    output, size, started, last_update = [], 0, time.monotonic(), 0
    try:
        while True:
            if cancel.is_set():
                raise Cancelled('已停止，网盘已转存的文件会保留')
            if time.monotonic() - started > timeout:
                raise TimeoutError('网盘任务超时，可重试续传')
            try:
                line = lines.get(timeout=0.1)
            except queue.Empty:
                continue
            if line is None:
                break
            text = line.decode('utf-8', errors='replace')
            if size < 2 * 1024 * 1024:
                output.append(text)
                size += len(line)
            # Show progress only, never raw output that may include auth tokens.
            if progress and time.monotonic() - last_update > 0.8:
                percent = re.search(r'\b\d+(?:\.\d+)?%', text)
                progress('百度下载 ' + percent[0] if percent else '百度任务处理中')
                last_update = time.monotonic()
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        process.stdout.close()
    text = ''.join(output)
    # Upstream can print an error then return code 0.
    if process.returncode or re.search(r'失败|错误|未登录|未登陆|请先登录|请先登陆|error|failed|not logged', text, re.I):
        raise RuntimeError('网盘工具未完成任务：请检查登录、提取码、分享有效性或账号限制')
    return text


def baidu_share(url, code=''):
    parsed = up.urlsplit(url)
    if parsed.scheme not in ('http', 'https') or parsed.hostname not in ('pan.baidu.com', 'yun.baidu.com'):
        raise ValueError('仅支持百度网盘分享链接')
    if parsed.username or parsed.password or parsed.port:
        raise ValueError('分享链接格式不正确')
    query = up.parse_qs(parsed.query)
    if parsed.path in ('/share/init', '/share/init/') and query.get('surl'):
        path = '/s/1' + query['surl'][0]
    else:
        path = parsed.path.rstrip('/')
    if not re.fullmatch(r'/s/1[\w-]{1,64}', path, flags=re.ASCII):
        raise ValueError('请使用 /s/1… 或 /share/init?surl=… 格式的分享链接')
    code = code.strip() or query.get('pwd', [''])[0]
    if code and not re.fullmatch(r'[A-Za-z0-9]{4}', code):
        raise ValueError('提取码应为四位字母或数字')
    return 'https://pan.baidu.com' + path, code


def download_baidu(executable, item, folder, config_dir, cancel, progress=None):
    url, code = baidu_share(item['url'], item.get('code', ''))
    # Isolate each share; never download the account root or mix previous shares.
    key = hashlib.sha256(url.encode()).hexdigest()[:12]
    remote = '/拾音下载/' + key
    local = Path(folder) / ('百度_' + key)
    local.mkdir(parents=True, exist_ok=True)
    run = lambda args, **kwargs: run_pcs(executable, args, config_dir, cancel, **kwargs)
    account = check_pcs_login(executable, config_dir, cancel)
    run(['config', 'set', '--savedir', str(local.resolve())])
    try:
        run(['ls', remote])
    except RuntimeError:
        run(['mkdir', remote])
    run(['cd', remote])
    marker = local / '.shiyin-transfer.json'
    try:
        saved = json.loads(marker.read_text('utf-8'))
        transferred = saved.get('url') == url and saved.get('account') == account
    except (OSError, ValueError, AttributeError):
        transferred = False
    if not transferred:
        text = run(['transfer', url] + ([code] if code else []))
        if '成功' not in text:
            raise RuntimeError('未确认转存成功，未启动下载')
        marker.write_text(json.dumps({'url': url, 'remote': remote, 'account': account}), encoding='utf-8')
    run(['download', '--saveto', str(local.resolve()), remote], timeout=24 * 3600, progress=progress)
    files = list(local.rglob('*'))
    completed = [p for p in files if p.is_file() and p.stat().st_size and p.suffix.lower() not in ('.tmp', '.part', '.json')
                 and not p.name.lower().endswith(('.downloading', '.aria2', '.baidupcs-go-downloading'))]
    if not completed:
        raise RuntimeError('未检测到下载完成的文件，请检查账号或分享状态')
    return local
