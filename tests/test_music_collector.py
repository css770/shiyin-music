import hashlib
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SOURCE = Path(__file__).resolve().parents[1] / 'music_collector.pyw'
loader = importlib.machinery.SourceFileLoader('collector', str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)
PAYLOAD = b'fLaC' + bytes(range(256)) * 8192

class Handler(BaseHTTPRequestHandler):
    hits = []
    def log_message(self, *_):
        pass
    def do_GET(self):
        self.hits.append((self.path, self.headers.get('Range')))
        if self.path == '/slow':
            time.sleep(3)
            try:
                self.send_response(200)
                self.end_headers()
            except (ConnectionResetError, BrokenPipeError):
                pass  # The deadline/cancellation test deliberately closes this socket.
            return
        if self.path == '/greedy-home':
            data = ('<title>论坛</title>' + ''.join(f'<a href="thread-{i}.html">歌手 专辑 {i}</a>' for i in range(1,10))).encode()
            ctype = 'text/html; charset=utf-8'
        elif self.path.startswith('/search?'):
            data = '<title>搜索结果</title><a href="thread-1.html">歌手 专辑 FLAC</a>'.encode()
            ctype = 'text/html; charset=utf-8'
        elif self.path == '/empty-home':
            data = '<title>论坛首页</title><form action="/search" method="get"><input name="q"></form>'.encode()
            ctype = 'text/html; charset=utf-8'
        elif self.path == '/robots.txt':
            data = b'User-agent: *\nDisallow: /private\n'
            ctype = 'text/plain'
        elif self.path == '/forum-1.html':
            data = '<title>论坛</title><a href="thread-1.html">歌手 专辑 FLAC</a><a href="https://elsewhere.invalid/thread-2.html">外站</a>'.encode()
            ctype = 'text/html; charset=utf-8'
        elif self.path.startswith('/thread-'):
            data = '<title>歌手 专辑 无损</title><a href="/sample.flac">专辑</a><a href="https://pan.baidu.com/s/test">百度</a> 提取码：a1b2'.encode()
            ctype = 'text/html; charset=utf-8'
        elif self.path == '/fake.flac':
            data = b'<html>please log in</html>'
            ctype = 'text/html'
        else:
            data = PAYLOAD
            ctype = 'audio/flac'
        offset = 0
        status = 200
        if self.headers.get('Range') and self.path == '/sample.flac':
            offset = int(self.headers['Range'].split('=')[1].split('-')[0])
            status = 206
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data) - offset))
        self.send_header('ETag', '"test-version-1"')
        if status == 206:
            self.send_header('Content-Range', f'bytes {offset}-{len(data)-1}/{len(data)}')
        self.end_headers()
        self.wfile.write(data[offset:])

class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
    def item(self, name='sample.flac'):
        return {'url': self.base + '/' + name, 'name': name, 'source': self.base, 'kind': '音频直链'}
    def test_html_resources_and_deduplication(self):
        page = '<title>歌手 专辑</title><p><a href="https://pan.baidu.com/s/abc?pwd=a1b2">分享</a> 提取码：a1b2</p><a href="album.flac">歌</a><a href="album.flac">重复</a><a href="https://music.163.com/a.flac">厂商</a>'
        resources, _, _, _ = m.parse_resources(page, self.base + '/thread-1.html', '歌手 专辑')
        self.assertEqual(len(resources), 2)
        self.assertEqual(resources[0]['code'], 'a1b2')
        self.assertEqual(resources[1]['url'], self.base + '/album.flac')
        self.assertEqual(m.parse_resources(page, self.base, '不匹配')[0], [])
    def test_import_plain_urls_codes(self):
        resources, _, _, _ = m.parse_resources('<pre>https://pan.quark.cn/s/abc 提取码：z9x8\nhttps://example.com/song.flac</pre>', self.base)
        self.assertEqual(len(resources), 2)
        self.assertEqual(resources[0]['code'], 'z9x8')
    def test_crawler_thread_and_same_site_boundary(self):
        events = []
        m.crawl([self.base + '/forum-1.html'], '歌手', 10, 1, threading.Event(), lambda *event: events.append(event))
        resources = [value for kind, value in events if kind == 'resource' and value['kind'] != '相关帖子']
        self.assertEqual(len(resources), 2)
        self.assertEqual(events[-1][0], 'crawl_done')
    def test_robots_disallow(self):
        self.assertFalse(m.RobotPolicy().allowed(self.base + '/private/thread-1.html'))
    def test_download_and_duplicate_skip(self):
        events = []
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            m.download_one(self.item(), folder, threading.Event(), lambda *event: events.append(event))
            files = list(folder.glob('*.flac'))
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].read_bytes(), PAYLOAD)
            m.download_one(self.item(), folder, threading.Event(), lambda *event: events.append(event))
            self.assertEqual(events[-1][1][1], '已下载（跳过）')
    def test_range_resume(self):
        item = self.item()
        key = hashlib.sha256(item['url'].encode()).hexdigest()[:10]
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            part = folder / f'sample_{key}.flac.part'
            part.write_bytes(PAYLOAD[:17000])
            part.with_name(part.name + '.json').write_text(json.dumps({'url': item['url'], 'validator': '"test-version-1"'}))
            m.download_one(item, folder, threading.Event(), lambda *_: None)
            self.assertEqual(next(folder.glob('*.flac')).read_bytes(), PAYLOAD)
            self.assertIn(('/sample.flac', 'bytes=17000-'), Handler.hits)
    def test_reject_html_and_cancelled_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            events = []
            m.download_one(self.item('fake.flac'), folder, threading.Event(), lambda *event: events.append(event))
            self.assertFalse(list(folder.glob('*.flac')))
            self.assertTrue(any('并非文件' in str(event) for event in events))
            stop = threading.Event()
            stop.set()
            before = len(Handler.hits)
            m.download_one(self.item(), folder, stop, lambda *_: None)
            self.assertEqual(len(Handler.hits), before)
    def test_filename_and_protocol(self):
        self.assertEqual(m.normalize('javascript:alert(1)'), '')
        self.assertEqual(m.normalize('https://a:b@example.com/'), '')
        self.assertTrue(m.safe_filename('CON.flac').startswith('_'))
        self.assertNotIn('\\', m.safe_filename('../../evil\\song.flac'))
    def test_new_blog_routes_and_cloud_share_passwords(self):
        self.assertTrue(m.is_thread('https://yogoe.cn/archives/12345'))
        self.assertTrue(m.is_thread('https://www.wayinyue.com/jay-chou-album.html'))
        self.assertFalse(m.is_thread('https://yogoe.cn/?s=Jay'))
        self.assertFalse(m.is_thread('https://www.wayinyue.com/category/music/'))
        self.assertEqual(m.classify('https://url04.ctfile.com/f/12345?p=1807'),'网盘')
        self.assertEqual(m.classify('https://a.lanzouq.com/abcd'),'网盘')
        resources,_,_,_ = m.parse_resources('<title>测试</title><a href="https://url04.ctfile.com/f/12345?p=1807">下载</a>',self.base)
        self.assertEqual(resources[0]['code'],'1807')
    def test_each_source_gets_turn_and_unused_budget_is_reassigned(self):
        events = []
        before = len(Handler.hits)
        m.crawl([self.base+'/greedy-home',self.base+'/private-a',self.base+'/private-b'], '歌手',8,1,threading.Event(),lambda *event: events.append(event))
        requests = [path for path,_ in Handler.hits[before:] if path!='/robots.txt']
        self.assertIn('/greedy-home',requests)
        self.assertEqual(len(requests),len(set(requests)))
        self.assertTrue(any('继续使用剩余' in str(value) for kind,value in events if kind=='log'))
        self.assertLessEqual(len(requests),8)
        self.assertGreaterEqual(len([p for p in requests if p.startswith('/thread-')]),3)
    def test_native_search_when_keyword_absent_from_homepage(self):
        events = []
        m.crawl([self.base + '/empty-home'], '歌手', 6, 1, threading.Event(), lambda *event: events.append(event))
        self.assertTrue(any('/search?q=' in path for path, _ in Handler.hits))
        self.assertTrue(any(kind == 'resource' and value['kind'] == '相关帖子' for kind, value in events))
        self.assertTrue(any(kind == 'resource' and value['kind'] == '音频直链' for kind, value in events))
        self.assertEqual(events[-1][0], 'crawl_done')
    def test_request_total_deadline_and_cancellation(self):
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            m.request_bytes(self.base + '/slow', timeout=1)
        self.assertLess(time.monotonic() - started, 2.5)
        stop = threading.Event()
        threading.Timer(0.2, stop.set).start()
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            m.request_bytes(self.base + '/slow', cancel=stop, timeout=10)
        self.assertLess(time.monotonic() - started, 1.2)

if __name__ == '__main__':
    unittest.main(verbosity=2)
