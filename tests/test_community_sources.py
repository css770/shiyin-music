import importlib.machinery
import importlib.util
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse as up

import community_sources as c
from pathlib import Path

loader = importlib.machinery.SourceFileLoader('community_collector', str(Path(__file__).resolve().parents[1] / 'music_collector.pyw'))
spec = importlib.util.spec_from_loader(loader.name, loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)


class CommunityTests(unittest.TestCase):
    def test_native_search_keeps_bar_and_does_not_search_a_post(self):
        url, data = c.native_search('https://tieba.baidu.com/f?kw=hires', '周杰伦 晴天')
        params = up.parse_qs(up.urlsplit(url).query)
        self.assertEqual(params['qw'], ['周杰伦 晴天'])
        self.assertEqual(params['kw'], ['hires'])
        self.assertIsNone(data)
        self.assertIsNone(c.native_search('https://tieba.baidu.com/p/12345', '周杰伦'))
        self.assertIsNone(c.native_search('https://tieba.baidu.com.evil/', '周杰伦'))

    def test_public_navigation_comments_and_redirect_links(self):
        page = '''<title>贴吧</title><h1 class="core_title_txt" title="歌手 无损分享"></h1>
        <!-- <div class="threadlist_title"><a href="/p/12345" title="歌手 专辑">分享</a>
        <a href="https://pan.baidu.com/s/hidden">此隐藏链接不可采集</a></div> -->
        <a href="https://jump2.bdimg.com/safecheck/index?url=https%3A%2F%2Fpan.baidu.com%2Fs%2F1fixture%3Fpwd%3DAB12">下载</a>'''
        resources, navigation, title, _ = m.parse_resources(page, 'https://tieba.baidu.com/p/45678', '歌手')
        self.assertEqual(title, '歌手 无损分享')
        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]['code'], 'AB12')
        self.assertEqual(resources[0]['url'], 'https://pan.baidu.com/s/1fixture?pwd=AB12')
        self.assertIn(('https://tieba.baidu.com/p/12345', '歌手 专辑'), navigation)
        self.assertFalse(any('hidden' in r['url'] for r in resources))

    def test_public_reply_pagination_is_bounded_and_same_post(self):
        base = 'https://tieba.baidu.com/p/12345?pn=1'
        self.assertTrue(c.pagination('https://c.tieba.baidu.com/p/12345?pn=2', base, '下一页'))
        self.assertFalse(c.pagination('https://tieba.baidu.com/p/12345?pn=4', base, '下一页'))
        self.assertFalse(c.pagination('https://tieba.baidu.com/p/67890?pn=2', base, '下一页'))
        self.assertFalse(c.pagination('https://evil.test/p/12345?pn=2', base, '下一页'))

    def test_automatic_tieba_search_follows_reply_links(self):
        events, fetched = [], []
        def fetch(url, *args, **kwargs):
            fetched.append(url)
            if '/f/search/res?' in url:
                return '<title>搜索结果</title><a href="/p/12345">歌手 无损合集</a>', url
            if 'pn=2' not in url:
                return '<title>歌手 无损合集</title><p>链接在回复里</p><a href="/p/12345?pn=2">下一页</a>', url
            return '<title>歌手 无损合集</title><p>链接：https://pan.baidu.com/s/1fixture?pwd=AB12</p>', url
        with patch.object(m.RobotPolicy, 'allowed', return_value=True), patch.object(m, 'fetch_page', side_effect=fetch):
            m.crawl(['https://tieba.baidu.com/f?kw=hires'], '歌手', 5, 1, threading.Event(), lambda *event: events.append(event))
        self.assertIn('/f/search/res?', fetched[0])
        self.assertTrue(any('pn=2' in url for url in fetched))
        self.assertTrue(any(kind == 'resource' and item['kind'] == '网盘' and item['code'] == 'AB12' for kind,item in events))

    def test_403_produces_search_entry_not_a_fake_download(self):
        events = []
        with patch.object(m.RobotPolicy, 'allowed', return_value=True), patch.object(m, 'fetch_page', side_effect=urllib.error.HTTPError('https://tieba.baidu.com/',403,'Forbidden',None,None)):
            m.crawl(['https://tieba.baidu.com/'], '歌手', 2, 1, threading.Event(), lambda *event: events.append(event))
        entries = [item for kind,item in events if kind == 'resource']
        self.assertTrue(entries)
        self.assertTrue(all(item['kind'] == '搜索入口' for item in entries))
        self.assertFalse(any(m.classify(item['url']) for item in entries))
        self.assertEqual(events[-1][0], 'crawl_done')

    def test_browser_search_targets_and_untrusted_wrappers(self):
        for target in ('贴吧全站','无损音乐吧','Hi-Res 吧','贴吧网盘搜索','豆瓣小组','过期罐头音乐区'):
            self.assertTrue(c.browser_search(target, 'Artist & song').startswith('https://'))
        wrapper = 'https://evil.test/safecheck/index?url=https%3A%2F%2Fpan.baidu.com%2Fs%2F1abc'
        self.assertEqual(c.unwrap_link(wrapper, 'https://tieba.baidu.com/p/123'), wrapper)
        opaque = 'https://jump2.bdimg.com/safecheck/index?url=opaque-token'
        self.assertEqual(c.unwrap_link(opaque, 'https://tieba.baidu.com/p/123'), opaque)


if __name__ == '__main__':
    unittest.main()
