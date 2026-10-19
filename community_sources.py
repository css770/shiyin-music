"""Public community search routes, navigation and transparent fallbacks."""
from html import escape
from html.parser import HTMLParser
import re
import urllib.parse as up

TIEBA_HOSTS = {'tieba.baidu.com', 'c.tieba.baidu.com'}


def hostname(url):
    return (up.urlsplit(url).hostname or '').lower().removeprefix('www.')


def is_tieba(url):
    return hostname(url) in TIEBA_HOSTS


def same_site(left, right):
    a, b = hostname(left), hostname(right)
    return a == b or a in TIEBA_HOSTS and b in TIEBA_HOSTS


def site_key(url):
    return 'tieba.baidu.com' if is_tieba(url) else hostname(url)


def native_search(seed, keyword):
    if not keyword or not is_tieba(seed) or re.fullmatch(r'/p/\d+/?', up.urlsplit(seed).path):
        return None
    original = up.parse_qs(up.urlsplit(seed).query)
    params = {'isnew': '1', 'qw': keyword, 'sm': '1', 'pn': '1'}
    if original.get('kw'):
        params['kw'] = original['kw'][0]
    return 'https://tieba.baidu.com/f/search/res?' + up.urlencode(params), None


def browser_search(target, keyword):
    if target == '贴吧全站':
        return native_search('https://tieba.baidu.com/', keyword)[0]
    if target in ('无损音乐吧', 'Hi-Res 吧'):
        bar = '无损音乐' if target == '无损音乐吧' else 'hires'
        return native_search('https://tieba.baidu.com/f?' + up.urlencode({'kw': bar}), keyword)[0]
    if target == '豆瓣小组':
        return 'https://www.douban.com/group/search?' + up.urlencode({'cat': '1019', 'q': keyword})
    domain = 'tieba.baidu.com' if target == '贴吧网盘搜索' else 'www.gqgtpc.com'
    query = f'site:{domain} {keyword} 无损 ("pan.baidu.com" OR "pan.quark.cn" OR "FLAC")'
    return 'https://www.bing.com/search?' + up.urlencode({'q': query})


def search_fallback(seed, keyword, reason):
    if not keyword:
        return None
    if is_tieba(seed):
        search = native_search(seed, keyword)
        url = search[0] if search else seed
        bar = up.parse_qs(up.urlsplit(seed).query).get('kw', ['全站'])[0]
        name = f'贴吧 · {bar} · {keyword}'
    elif hostname(seed) == 'gqgtpc.com':
        url = browser_search('过期罐头音乐区', keyword)
        name = f'过期罐头音乐区 · {keyword}'
    else:
        return None
    return {'kind': '搜索入口', 'url': url, 'name': name, 'title': name, 'source': seed,
            'code': '', 'status': reason + '；双击在浏览器搜索'}


def unwrap_link(url, source):
    """Decode only explicit URLs in known community redirect wrappers."""
    if not is_tieba(source):
        return url
    parsed = up.urlsplit(url)
    allowed = ((parsed.hostname in {'jump2.bdimg.com', 'jump.bdimg.com'} and parsed.path == '/safecheck/index')
               or (parsed.hostname in TIEBA_HOSTS and parsed.path == '/mo/q/checkurl'))
    if not allowed:
        return url
    target = up.parse_qs(parsed.query).get('url', [''])[0]
    decoded = up.urlsplit(target)
    if decoded.scheme in ('http', 'https') and decoded.hostname and not decoded.username and not decoded.password:
        return target
    return url


class TiebaNavigation(HTMLParser):
    def __init__(self):
        super().__init__()
        self.comments = []
        self.heading = ''
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('h1', 'h3') and ('core_title_txt' in attrs.get('class', '') or 'p_title' in attrs.get('class', '')):
            self.heading = attrs.get('title', '')
    def handle_comment(self, text):
        # Some public forum indexes render their thread navigation from an
        # HTML comment. Extract navigation only, never hidden attachments.
        if 'j_th_tit' in text or 'threadlist_title' in text:
            self.comments.append(text)


class CommentLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a' and re.fullmatch(r'/p/\d+(?:\?[^#]*)?', attrs.get('href', '')) and attrs.get('title'):
            self.links.append((attrs['href'], attrs['title']))


def prepare_document(document, source):
    if not is_tieba(source):
        return document
    parser = TiebaNavigation()
    parser.feed(document)
    additions = []
    if parser.heading:
        # Prefer the thread's own heading over a generic page title.
        document = re.sub(r'<title\b[^>]*>.*?</title>', '', document, flags=re.I | re.S)
        additions.append('<title>' + escape(parser.heading) + '</title>')
    for comment in parser.comments:
        links = CommentLinks()
        links.feed(comment)
        additions.extend('<a href="' + escape(url, quote=True) + '">' + escape(label) + '</a>' for url, label in links.links)
    return document + '\n' + '\n'.join(additions)


def pagination(target, current, label):
    """Read a few public reply/search pages without crawling the whole site."""
    if not same_site(target, current) or not re.search(r'下一页|下页|next', label, re.I):
        return False
    target_url, current_url = up.urlsplit(target), up.urlsplit(current)
    if is_tieba(current):
        if target_url.path != current_url.path:
            return False
        if not (re.fullmatch(r'/p/\d+', current_url.path) or current_url.path == '/f/search/res'):
            return False
        tq, cq = up.parse_qs(target_url.query), up.parse_qs(current_url.query)
        if current_url.path == '/f/search/res' and any(tq.get(k) != cq.get(k) for k in ('qw', 'kw')):
            return False
        try:
            return 1 < int(tq.get('pn', ['1'])[0]) <= 3
        except ValueError:
            return False
    if hostname(current) == 'gqgtpc.com':
        # Topic pagination is safe; unrelated forum navigation is excluded.
        thread = re.search(r'/thread-(\d+)-', current_url.path)
        target_thread = re.search(r'/thread-(\d+)-(\d+)-', target_url.path)
        return bool(thread and target_thread and thread[1] == target_thread[1] and 1 < int(target_thread[2]) <= 3)
    return False
