"""Local forum music link collector. Python 3.11+, standard library only."""
import concurrent.futures
import csv
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import queue
import random
import re
import ssl
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox
import urllib.error
import urllib.parse as up
import urllib.request as ur
import urllib.robotparser
import webbrowser

BASE = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
ASSETS = Path(getattr(sys, '_MEIPASS', BASE)) / 'assets' if getattr(sys, 'frozen', False) else BASE / 'assets'
BG = '#f5f1e9'
INK = '#303d38'
MUTED = '#7a847c'
GREEN = '#356455'
PALE = '#e5ece3'

def configure_dpi():
    if os.name == 'nt':
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass

def rounded_shape(canvas, x1, y1, x2, y2, radius=16, **options):
    r = min(radius, (x2 - x1) / 2, (y2 - y1) / 2)
    return canvas.create_polygon(x1+r,y1, x2-r,y1, x2,y1, x2,y1+r,
                                 x2,y2-r, x2,y2, x2-r,y2, x1+r,y2,
                                 x1,y2, x1,y2-r, x1,y1+r, x1,y1,
                                 smooth=True, splinesteps=24, **options)

class SoftButton(tk.Canvas):
    """Small rounded, keyboard-accessible button without runtime dependencies."""
    def __init__(self, master, text='', command=None, style='', **kwargs):
        self.text = text
        self.command = command
        self.accent = style == 'Accent.TButton'
        self.button_state = 'normal'
        self.hover = False
        self.font = tkfont.Font(family='Microsoft YaHei UI', size=10, weight='bold' if self.accent else 'normal')
        try:
            background = master.cget('background')
        except tk.TclError:
            background = BG
        super().__init__(master, bg=background, highlightthickness=0, bd=0, takefocus=1,
                         width=self.font.measure(text) + 26, height=self.font.metrics('linespace') + 18,
                         cursor='hand2', **kwargs)
        self.bind('<Configure>', lambda _: self.redraw())
        self.bind('<Enter>', lambda _: self.set_hover(True))
        self.bind('<Leave>', lambda _: self.set_hover(False))
        self.bind('<ButtonRelease-1>', lambda _: self.invoke())
        self.bind('<Return>', lambda _: self.invoke())
        self.bind('<space>', lambda _: self.invoke())
        self.bind('<FocusIn>', lambda _: self.redraw())
        self.bind('<FocusOut>', lambda _: self.redraw())
    def configure(self, cnf=None, **kwargs):
        if 'text' in kwargs:
            self.text = kwargs.pop('text')
            kwargs['width'] = self.font.measure(self.text) + 26
        if 'state' in kwargs:
            self.button_state = kwargs.pop('state')
        result = super().configure(cnf, **kwargs)
        self.redraw()
        return result
    config = configure
    def set_hover(self, value):
        self.hover = value
        self.redraw()
    def invoke(self):
        if self.button_state != 'disabled' and self.command:
            self.focus_set()
            self.command()
    def redraw(self):
        self.delete('all')
        disabled = self.button_state == 'disabled'
        fill = '#dce0d8' if disabled else ('#274f42' if self.hover else GREEN) if self.accent else ('#dce7da' if self.hover else '#e8e9df')
        text = '#959d93' if disabled else '#ffffff' if self.accent else GREEN
        rounded_shape(self, 1, 1, max(2,self.winfo_width()-1), max(2,self.winfo_height()-1), 12,
                      fill=fill, outline='#bc9664' if self.focus_get() == self else fill, width=2)
        self.create_text(self.winfo_width()/2, self.winfo_height()/2, text=self.text, fill=text, font=self.font)

class RoundedCard(tk.Canvas):
    def __init__(self, master, **kwargs):
        super().__init__(master, bg=BG, highlightthickness=0, bd=0, height=220, **kwargs)
        self.content = tk.Frame(self, bg='#fffdf8')
        self.window = self.create_window((20, 18), window=self.content, anchor='nw')
        self.bind('<Configure>', self.resize)
        self.content.bind('<Configure>', self.content_resize)
    def content_resize(self, event):
        height = self.content.winfo_reqheight() + 36
        if int(self.cget('height')) != height:
            self.configure(height=height)
        self.redraw()
    def resize(self, event):
        self.itemconfigure(self.window, width=max(40, event.width - 40))
        for child in self.content.winfo_children():
            if isinstance(child, tk.Label) and child.cget('wraplength'):
                child.configure(wraplength=max(100, event.width - 42))
        self.redraw()
    def redraw(self):
        self.delete('surface')
        rounded_shape(self, 1, 2, max(2,self.winfo_width()-1), max(3,self.winfo_height()-1), 22,
                      fill='#fffdf8', outline='#e2dfd2', tags='surface')
        self.tag_lower('surface')

def paw(canvas, x, y, scale=1, color='#c3a980'):
    canvas.create_oval(x-7*scale,y-3*scale,x+7*scale,y+8*scale,fill=color,outline='')
    for dx, dy in ((-8,-7),(-3,-11),(3,-11),(8,-7)):
        canvas.create_oval(x+(dx-2.6)*scale,y+(dy-3)*scale,x+(dx+2.6)*scale,y+(dy+3)*scale,fill=color,outline='')
DATA = Path(os.environ.get('LOCALAPPDATA', str(BASE))) / 'MusicLinkCollector'
UA = 'MusicLinkCollector/1.0 (local personal link organizer)'
MEDIA = {'.flac', '.ape', '.wav', '.alac', '.aiff', '.aif', '.wv', '.tta', '.tak', '.dsf', '.dff'}
ARCHIVES = {'.zip', '.rar', '.7z'}
CLOUD = ('pan.baidu.com', 'alipan.com', 'aliyundrive.com', 'pan.quark.cn', 'pan.xunlei.com', '123pan.com', '123912.com', '123865.com', '115.com', '115cdn.com', 'lanzou.com', 'lanzoui.com', 'lanzoux.com', 'lanzoub.com', 'lanzouj.com', 'lanzoul.com', 'lanzoup.com', 'lanzouv.com', 'lanzouw.com', 'weiyun.com', 'mega.nz', 'mediafire.com', 'gofile.io', 'mypikpak.com')
VENDORS = ('music.163.com', 'kugou.com', 'kuwo.cn', 'y.qq.com', 'music.migu.cn')
BUILTIN_SITES = (
    ('HIFINI', 'https://hifini.net/', '可能需要浏览器校验'),
    ('HiFi听吧', 'https://hifitb.com/index.html', '部分资源需登录、回复'),
    ('读屏族音乐论坛', 'https://www.dpzyy.com/', '有会员资源区'),
    ('Hi-Res视听发烧论坛', 'https://www.hi-res.com.cn/', 'Hi-Res / SACD / DSD'),
    ('捌零无损音乐论坛', 'https://www.80wusun.com/forum.php', '华语、外语、专辑'),
    ('享乐音乐论坛', 'https://www.xlebbs.com/', '部分板块有等级要求'),
    ('海水之声', 'https://www.hszsz.com/', '发烧专辑、原抓分享'),
    ('23APE', 'http://www.23ape.net/', '公开帖子可读取；网盘有效性需另行核对'),
    ('XDOUBAN', 'https://xdouban.com/', '无损音乐分享板块；部分资源有积分限制'),
    ('动感炫音', 'https://bbs.dgxy.cc/', '华语、欧美、古典专辑；部分需登录'),
    ('CD包子铺', 'https://cdbao.org/', '网友音乐分享社区；部分需登录或回复'),
    ('优歌', 'https://yogoe.cn/', '专辑与综艺音乐分享；下载限制以页面为准'),
    ('挖音乐', 'https://www.wayinyue.com/', '专辑与歌手合集；部分需会员'),
    ('乐海拾贝', 'https://www.yuehaishibei.com/', 'WAV / FLAC / APE 网盘分享'),
    ('熊猫无损音乐网', 'https://xmyinyue.com/', '音乐合集与网盘分享；链接有效性待核对'),
)
LEGACY_SITE_URLS = {url for _, url, _ in BUILTIN_SITES[:8]}
BLOG_HOSTS = {'yogoe.cn', 'wayinyue.com', 'yuehaishibei.com', 'xmyinyue.com'}
CLOUD += ('ctfile.com', '189.cn', 'yun.139.com', '123pan.cn')

# Editorial listening ideas. Tags are browsing aids, not an audio-quality claim.
RECOMMENDATION_ROWS = (
    ('周杰伦', '范特西', '华语', '流行', '怀旧', '从熟悉的旋律出发，适合重新听一遍整张专辑。'),
    ('周杰伦', '叶惠美', '华语', '流行', '怀旧', '想听千禧年华语流行，可以从这张开始。'),
    ('王菲', '寓言', '华语', '流行', '氛围', '留一点安静的时间，听声音和编曲的层次。'),
    ('孙燕姿', '风筝', '华语', '流行', '提神', '适合想听清亮人声、让情绪轻快一点的时候。'),
    ('林俊杰', '第二天堂', '华语', '流行', '怀旧', '适合重温早期华语流行的旋律。'),
    ('陈奕迅', '认了吧', '华语', '流行', '夜晚', '晚上想听故事感强的人声时，可以试试。'),
    ('张惠妹', '阿密特', '华语', '流行', '提神', '想从温柔歌单切到更有力量的人声时试试。'),
    ('陶喆', '黑色柳丁', '华语', '节奏蓝调', '氛围', '适合想听律动，又不想太喧闹的时候。'),
    ('方大同', '爱爱爱', '华语', '节奏蓝调', '放松', '从节奏和人声入手，给日常换一点律动。'),
    ('邓丽君', '淡淡幽情', '华语', '国风', '安静', '适合慢下来，听文字与旋律相遇。'),
    ('张学友', '吻别', '华语', '流行', '怀旧', '不知道选什么时，可以重温这张熟悉的专辑。'),
    ('李健', '', '华语', '民谣', '安静', '想听克制、舒展的人声，可以先按歌手搜集。'),
    ('陈绮贞', '旅行的意义', '华语', '民谣', '放松', '适合散步、读书间隙，或想短暂放空的时候。'),
    ('朴树', '生如夏花', '华语', '民谣', '怀旧', '适合想找回一点青春和旅途感的时候。'),
    ('赵雷', '无法长大', '华语', '民谣', '夜晚', '晚上想听日常生活里的故事，可以从这里开始。'),
    ('窦唯', '黑梦', '华语', '摇滚', '氛围', '想离开常听的流行歌单时，可以试试这张。'),
    ('崔健', '新长征路上的摇滚', '华语', '摇滚', '提神', '适合想听更直接、更有冲劲的表达。'),
    ('万能青年旅店', '', '华语', '摇滚', '氛围', '给自己一段完整时间，试着从整张专辑听起。'),
    ('许巍', '时光漫步', '华语', '摇滚', '放松', '适合在路上，或想让心情舒展开的时候。'),
    ('Beyond', '海阔天空', '粤语', '摇滚', '提神', '想听熟悉的合唱感和吉他，可以从这首搜起。'),
    ('陈奕迅', 'U87', '粤语', '流行', '夜晚', '想从单曲换成整张专辑聆听时，可以选它。'),
    ('张国荣', '风继续吹', '粤语', '流行', '怀旧', '适合从一首熟悉的歌，慢慢往回听。'),
    ('梅艳芳', '似是故人来', '粤语', '流行', '怀旧', '想听叙事感和余韵时，可以试试。'),
    ('林忆莲', '都市触觉', '粤语', '流行', '氛围', '适合给夜晚添一点都市流行的色彩。'),
    ('Norah Jones', 'Come Away With Me', '欧美', '爵士', '放松', '适合夜晚、咖啡和不着急的聆听。'),
    ('Bill Evans', 'Waltz for Debby', '纯音乐', '爵士', '安静', '想从钢琴爵士开始，可以试着完整听这张。'),
    ('Miles Davis', 'Kind of Blue', '纯音乐', '爵士', '放松', '给爵士留一个不忙碌的下午，慢慢听。'),
    ('Dave Brubeck', 'Take Five', '纯音乐', '爵士', '提神', '想给背景音乐增加一点节奏变化时试试。'),
    ('Pink Floyd', 'The Dark Side of the Moon', '欧美', '摇滚', '氛围', '适合戴上耳机，留一段连续聆听的时间。'),
    ('Eagles', 'Hotel California', '欧美', '摇滚', '怀旧', '想听吉他与熟悉的旋律，可以从这里开始。'),
    ('Daft Punk', 'Random Access Memories', '欧美', '电子', '提神', '想让日常歌单多一点律动时，可以选它。'),
    ('Adele', '21', '欧美', '流行', '夜晚', '适合想专注听人声与情绪的夜晚。'),
    ('Enya', 'Watermark', '欧美', '流行', '安静', '想要柔和、宽阔的背景氛围时，可以试试。'),
    ('久石让', 'Dream Songs', '纯音乐', '影视原声', '放松', '想找电影感和钢琴、管弦乐的变化，可以从这里开始。'),
    ('坂本龙一', 'async', '纯音乐', '电子', '氛围', '想听空间、声音和留白时，给它一点耐心。'),
    ('坂本龙一', 'Merry Christmas Mr. Lawrence', '纯音乐', '影视原声', '安静', '适合从一段熟悉的电影旋律开始。'),
    ('Yiruma', 'River Flows in You', '纯音乐', '钢琴', '安静', '想听简洁的钢琴旋律时，可以作为起点。'),
    ('德彪西', '月光', '纯音乐', '古典', '安静', '想试试古典钢琴，可以先从一首短作品开始。'),
    ('巴赫', '哥德堡变奏曲', '纯音乐', '古典', '专注', '适合愿意把注意力交给结构和细节的时候。'),
    ('贝多芬', '第六交响曲', '纯音乐', '古典', '放松', '想从管弦乐入门，可以试着听完整部作品。'),
    ('柴可夫斯基', '胡桃夹子', '纯音乐', '古典', '提神', '想听色彩丰富的管弦乐段落时，可以选它。'),
    ('宇多田光', 'First Love', '日韩', '流行', '怀旧', '想从熟悉的日语旋律往外探索时试试。'),
    ('中岛美嘉', '雪之华', '日韩', '流行', '夜晚', '适合安静的夜晚，专心听一首歌。'),
    ('米津玄师', 'STRAY SHEEP', '日韩', '流行', '提神', '想给歌单换一点不同的日语流行色彩时试试。'),
    ('IU', 'Palette', '日韩', '流行', '放松', '想听轻松些的韩语流行，可以从这张开始。'),
    ('林海', '琵琶相', '纯音乐', '国风', '氛围', '想听民族器乐与画面感，可以按这个主题探索。'),
    ('赵聪', '聆听中国', '纯音乐', '国风', '提神', '想在器乐歌单里加入不同音色时试试。'),
    ('Hans Zimmer', 'Interstellar', '纯音乐', '影视原声', '氛围', '想听有空间感的电影配乐，可以从这里开始。'),
)
RECOMMENDATIONS = tuple({'id': f'r{i:02d}', 'artist': a, 'work': w, 'region': region,
                         'genre': genre, 'mood': mood, 'reason': reason,
                         'query': (a + ' ' + w).strip()}
                        for i, (a, w, region, genre, mood, reason) in enumerate(RECOMMENDATION_ROWS))

def recommendation_pool(region='全部', genre='全部', mood='全部', favorites=None):
    return [item for item in RECOMMENDATIONS
            if (region == '全部' or item['region'] == region)
            and (genre == '全部' or item['genre'] == genre)
            and (mood == '全部' or item['mood'] == mood)
            and (favorites is None or item['id'] in favorites)]

def pick_recommendations(pool, previous=(), count=6):
    fresh = [item for item in pool if item['id'] not in previous]
    old = [item for item in pool if item['id'] in previous]
    random.shuffle(fresh)
    random.shuffle(old)
    return (fresh + old)[:count]

def combine_sources(custom, selected):
    urls = [url for _, url, _ in BUILTIN_SITES if url in selected]
    urls.extend(line.strip() for line in custom.splitlines() if line.strip())
    return list(dict.fromkeys(normalize(url) for url in urls if normalize(url)))

def host(url):
    return (up.urlsplit(url).hostname or '').lower()

def matches_host(h, candidates):
    return any(h == d or h.endswith('.' + d) for d in candidates)

def normalize(url, base=''):
    url = html.unescape(url).strip().strip('"<>')
    url = up.urljoin(base, url)
    parsed = up.urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        return ''
    return up.urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or '/', parsed.query, parsed.fragment))

def classify(url):
    if matches_host(host(url), VENDORS):
        return ''
    if matches_host(host(url), CLOUD) or re.fullmatch(r'(?:[\w-]+\.)?lanzou[a-z]\.com', host(url)):
        return '网盘'
    suffix = Path(up.unquote(up.urlsplit(url).path)).suffix.lower()
    if suffix in MEDIA:
        return '音频直链'
    if suffix in ARCHIVES:
        return '压缩包直链'
    return ''

def extract_code(text):
    found = re.search(r'(?:提取码|访问码|访问密码|密码|提取密码|解压密码)\s*[:：=]?\s*([A-Za-z0-9_-]{4,24})', text)
    return found.group(1) if found else ''

class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.texts = []
        self.title = []
        self.in_title = False
        self.skip = 0
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'style'):
            self.skip += 1
        if tag == 'title':
            self.in_title = True
        if tag == 'a' and attrs.get('href'):
            self.current = [attrs['href'], '', len(self.texts)]
            self.links.append(self.current)

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.skip = max(0, self.skip - 1)
        if tag == 'title':
            self.in_title = False
        if tag == 'a':
            self.current = None

    def handle_data(self, text):
        if self.skip:
            return
        self.texts.append(text)
        if self.in_title:
            self.title.append(text)
        if self.current is not None:
            self.current[1] += text

def parse_resources(document, source, keyword=''):
    parser = PageParser()
    parser.feed(document)
    title = ' '.join(parser.title).strip() or host(source)
    visible = ' '.join(parser.texts)
    terms = [x.casefold() for x in keyword.split() if x]
    relevant = not terms or all(t in (title + ' ' + visible).casefold() for t in terms)
    candidates = []
    navigation = []
    for href, label, pos in parser.links:
        url = normalize(href, source)
        if not url:
            continue
        navigation.append((url, label))
        context = ' '.join(parser.texts[max(0, pos - 2):pos + 8])
        candidates.append((url, label, context))
    for match in re.finditer(r'https?://[^\s<>"\x27]+', visible):
        raw = match.group().rstrip('，。；、）)]}')
        url = normalize(raw)
        if url:
            candidates.append((url, '', visible[match.start():match.end() + 100]))
    results = []
    seen = set()
    for url, label, context in candidates:
        kind = classify(url)
        if not kind or not relevant or url in seen:
            continue
        seen.add(url)
        fragment = up.urlsplit(url).fragment
        code = extract_code(context) if kind == '网盘' else ''
        if kind == '网盘' and not code:
            query_codes = up.parse_qs(up.urlsplit(url).query)
            code = (query_codes.get('pwd') or query_codes.get('password') or query_codes.get('p') or [''])[0]
        if kind == '网盘' and not code and re.fullmatch(r'[A-Za-z0-9]{4}', fragment):
            code = fragment
        label = re.sub(r'\s+', ' ', label).strip()
        if label in ('百度盘', '百度网盘', '夸克网盘', '下载', '点击下载', '下载地址'):
            label = title
        results.append({'title': title, 'name': label or up.unquote(Path(up.urlsplit(url).path).name) or title,
                        'kind': kind, 'url': url, 'code': code, 'source': source, 'status': '待下载' if kind != '网盘' else '待打开'})
    return results, navigation, title, visible

def request_bytes(url, cancel=None, cookie_file=None, data=None, timeout=10):
    """Use the OS curl with an absolute wall deadline and interruptible process."""
    import tempfile
    cancel = cancel or threading.Event()
    with tempfile.TemporaryDirectory(prefix='shiyin-') as directory:
        body = Path(directory) / 'body'
        headers = Path(directory) / 'headers'
        args = ['curl.exe', '--silent', '--show-error', '--location', '--max-redirs', '3',
                '--connect-timeout', '4', '--max-time', str(timeout), '--max-filesize', '4194304',
                '--proto', '=http,https', '--proto-redir', '=http,https', '--user-agent', UA,
                '--output', str(body), '--dump-header', str(headers),
                '--write-out', '%{url_effective}\n%{http_code}\n%{content_type}']
        if cookie_file:
            args += ['--cookie', str(cookie_file), '--cookie-jar', str(cookie_file)]
        if data is not None:
            payload = Path(directory) / 'form'
            payload.write_bytes(data)
            args += ['--data-binary', '@' + str(payload), '--header', 'Content-Type: application/x-www-form-urlencoded']
        args.append(url)
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        started = time.monotonic()
        while process.poll() is None:
            if cancel.wait(0.08) or time.monotonic() - started > timeout + 1:
                process.kill()
                process.communicate()
                raise TimeoutError('已停止' if cancel.is_set() else f'请求超过 {timeout} 秒，已中止')
        out, error = process.communicate()
        if process.returncode:
            raise TimeoutError(f'连接失败或超过 {timeout} 秒：' + error.decode('utf-8', 'replace')[:120])
        info = out.decode('utf-8', 'replace').splitlines()
        if len(info) < 2:
            raise ValueError('服务器未返回有效响应')
        final, code = info[0], int(info[1])
        if code >= 400:
            raise urllib.error.HTTPError(final, code, f'HTTP {code}', None, None)
        return body.read_bytes(), final, info[2] if len(info) > 2 else ''

def fetch_page(url, cancel=None, cookie_file=None, data=None, timeout=10):
    raw, final, ctype = request_bytes(url, cancel, cookie_file, data, timeout)
    if ctype and not any(x in ctype for x in ('text/html', 'xhtml', 'text/plain')):
        raise ValueError('不是可解析的网页')
    match = re.search(r'charset=([\w-]+)', ctype, re.I)
    if not match:
        match = re.search(br'charset\s*=\s*["\x27]?([a-zA-Z0-9_-]+)', raw[:10000])
    charset = match.group(1) if match else 'utf-8'
    if isinstance(charset, bytes):
        charset = charset.decode('ascii')
    try:
        return raw.decode(charset), final
    except (LookupError, UnicodeDecodeError):
        return raw.decode('gb18030', errors='replace'), final

class RobotPolicy:
    def __init__(self, cancel=None, deadline=None):
        self.cache = {}
        self.cancel = cancel
        self.deadline = deadline

    def allowed(self, url):
        parsed = up.urlsplit(url)
        origin = f'{parsed.scheme}://{parsed.netloc}'
        if origin not in self.cache:
            rp = urllib.robotparser.RobotFileParser()
            try:
                remaining = self.deadline - time.monotonic() if self.deadline else 5
                if remaining <= 0:
                    return False
                raw, _, _ = request_bytes(origin + '/robots.txt', self.cancel, timeout=min(5, remaining))
                text = raw.decode('utf-8', errors='replace')
                if '<html' in text.lower() or '/_guard/' in text:
                    self.cache[origin] = None
                    return False
                rp.parse(text.splitlines())
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    rp.parse([])
                else:
                    self.cache[origin] = None
                    return False
            except Exception:
                self.cache[origin] = None
                return False
            self.cache[origin] = rp
        rp = self.cache[origin]
        return rp is not None and rp.can_fetch(UA, url)

class SearchFormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms = []
        self.current = None
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self.current = {'action': attrs.get('action', ''), 'method': attrs.get('method', 'get').lower(), 'fields': {}}
            self.forms.append(self.current)
        if tag == 'input' and self.current is not None and attrs.get('name'):
            if attrs.get('type', 'text').lower() not in ('password', 'file', 'checkbox', 'radio'):
                self.current['fields'][attrs['name']] = attrs.get('value', '')
    def handle_endtag(self, tag):
        if tag == 'form':
            self.current = None

def find_search(document, base, keyword):
    parser = SearchFormParser()
    parser.feed(document)
    for form in parser.forms:
        fields = form['fields'].copy()
        field = next((name for name in ('srchtxt', 'keyword', 'keywords', 'q', 's') if name in fields), None)
        url = normalize(form['action'], base)
        if not field or not url or host(url) != host(base):
            continue
        fields[field] = keyword
        if field == 'srchtxt':
            fields['searchsubmit'] = 'yes'
        query = up.urlencode(fields).encode('ascii')
        if form['method'] == 'post':
            return url, query
        return url + ('&' if '?' in url else '?') + query.decode('ascii'), None
    return None

def is_thread(url):
    if re.search(r'/(?:tag|tags|category|categories|forum|user|member|page)/', url, re.I):
        return False
    parsed = up.urlsplit(url)
    if host(url).removeprefix('www.') in BLOG_HOSTS:
        return parsed.path not in ('', '/', '/index.php', '/index.html') and not re.search(r'\.(?:jpg|png|webp|css|js|xml|txt)$', parsed.path, re.I) and not parsed.path.startswith(('/wp-', '/feed', '/search'))
    return bool(re.search(r'(thread[-/]|viewthread|viewtopic|/topic/|/t/|/p/|read\.php|tid=|/\d+\.html)', url, re.I))

def keyword_match(text, keyword):
    return all(term.casefold() in text.casefold() for term in keyword.split())

def crawl(seeds, keyword, limit, depth, cancel, emit):
    """Parallel sources, native public search, visible candidates and hard deadlines."""
    import tempfile
    started = time.monotonic()
    deadline = started + 120
    budget_lock = threading.Lock()
    requests_count = [0]
    matches = [0]
    resources_count = [0]
    resource_urls = set()
    resumes = {}
    def reserve():
        with budget_lock:
            if requests_count[0] >= limit or cancel.is_set() or time.monotonic() >= deadline:
                return False
            requests_count[0] += 1
            return True
    def status(text):
        emit('progress', text)
    def work(seed, quota, state=None):
        site = host(seed)
        if classify(seed):
            emit('resource', {'title': '直接导入', 'name': up.unquote(Path(up.urlsplit(seed).path).name) or '分享链接', 'kind': classify(seed), 'url': seed, 'code': '', 'source': seed, 'status': '待打开' if classify(seed) == '网盘' else '待下载'})
            return
        with tempfile.TemporaryDirectory(prefix='shiyin-session-') as directory:
            cookies = Path(directory) / 'cookies.txt'
            state = state or {}
            if state.get('cookies'):
                cookies.write_bytes(state['cookies'])
            policy = state.get('policy') or RobotPolicy(cancel, deadline)
            visited = state.get('visited', set())
            todo = state.get('todo', [(seed, 0, None)])
            searched = state.get('searched', False)
            last_request = state.get('last_request', 0)
            found_here = state.get('found', 0)
            checked_here = 0
            while todo and checked_here < quota and not cancel.is_set() and time.monotonic() < deadline:
                url, level, form_data = todo.pop(0)
                if url in visited and form_data is None:
                    continue
                visited.add(url)
                if not reserve():
                    break
                checked_here += 1
                status(f'正在查询 {site} · 已检查 {requests_count[0]}/{limit} 页')
                emit('log', f'[{site}] ' + ('提交关键词搜索' if form_data else '读取 ') + url)
                if not policy.allowed(url):
                    emit('log', f'[{site}] 跳过：robots.txt 禁止或无法确认，未读取帖子。')
                    continue
                if cancel.wait(max(0, 1.5 - (time.monotonic() - last_request))):
                    return
                last_request = time.monotonic()
                try:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    document, final = fetch_page(url, cancel, cookies, form_data, timeout=min(10, remaining))
                    if host(final).removeprefix('www.') != site.removeprefix('www.'):
                        emit('log', f'[{site}] 跳过：转到了其他网站。')
                        return
                    if '/_guard/' in document or 'challenge-platform' in document:
                        emit('log', f'[{site}] 需要浏览器校验，已停止该站。')
                        return
                    found, links, title, text = parse_resources(document, final, keyword)
                    if keyword and (not is_thread(final) or not keyword_match(title, keyword)):
                        found = []
                    restricted = any(s in text for s in ('回复可见', '回复后可见', '隐藏内容请回复', '登录后可见', '登录后下载', '需要 登录', '需要登录', '请先登录', '验证码'))
                    if keyword and is_thread(final) and keyword_match(title, keyword):
                        emit('resource', {'title': title, 'name': title, 'kind': '相关帖子', 'url': final, 'code': '', 'source': final, 'status': '需登录/回复，链接未公开' if restricted else '帖子已读取，未见公开下载链接' if not found else '已提取公开链接'})
                    for resource in found:
                        emit('resource', resource)
                        with budget_lock:
                            if resource['url'] not in resource_urls:
                                resource_urls.add(resource['url'])
                                resources_count[0] += 1
                    found_here += len(found)
                    emit('log', f'[{site}] {title[:55]} · 公开链接 {len(found)} 条' + (' · 有登录/回复限制' if restricted else ''))
                    if keyword and not searched and not is_thread(final):
                        searched = True
                        search = find_search(document, final, keyword)
                        if search:
                            todo.insert(0, (search[0], 0, search[1]))
                        else:
                            emit('log', f'[{site}] 没有可用的公开搜索表单，仅检查当前页面匹配的帖子。')
                    next_pages = []
                    for target, label in links:
                        target = up.urldefrag(target)[0]
                        if host(target).removeprefix('www.') != site.removeprefix('www.') or target in visited or classify(target):
                            continue
                        if keyword and is_thread(target) and keyword_match(label, keyword):
                            emit('resource', {'title': label.strip(), 'name': label.strip(), 'kind': '相关帖子', 'url': target, 'code': '', 'source': target, 'status': '找到帖子，等待读取链接'})
                            with budget_lock:
                                matches[0] += 1
                            next_pages.append((target, level + 1, None))
                        elif not keyword and level < depth and re.search(r'(thread|forum|viewtopic|topic|/t/|/p/|read|page=|fid=|tid=|下一页|下页)', target + label):
                            if not re.search(r'(logout|action=delete|action=reply|mod=post|register|login|attachment|download)', target, re.I):
                                next_pages.append((target, level + 1, None))
                    if keyword:
                        todo.extend(next_pages[:12])
                    else:
                        todo.extend(next_pages[:limit])
                except Exception as error:
                    emit('log', f'[{site}] 失败：{str(error)[:160]}')
            if todo and not cancel.is_set() and time.monotonic() < deadline:
                resumes[seed] = {'cookies': cookies.read_bytes() if cookies.exists() else b'',
                                 'policy': policy, 'visited': visited, 'todo': todo,
                                 'searched': searched, 'last_request': last_request, 'found': found_here}
    emit('progress', '正在启动查询 · 最多运行 120 秒，可随时停止')
    emit('log', f'开始：{len(seeds)} 个来源，最多 {limit} 页，总时限 120 秒；关键词：{keyword or "未指定"}')
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            per_site, extra = divmod(limit, max(1, len(seeds)))
            futures = [pool.submit(work, seed, per_site + (index < extra)) for index, seed in enumerate(seeds)]
            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                except Exception as error:
                    emit('log', '网站查询异常：' + str(error)[:160])
            remaining_pages = limit - requests_count[0]
            if remaining_pages > 0 and resumes and not cancel.is_set() and time.monotonic() < deadline:
                emit('log', f'首轮已覆盖所选来源，继续使用剩余 {remaining_pages} 页额度，优先检查已提取到公开链接的网站。')
                candidates = sorted(list(resumes.items()), key=lambda pair: pair[1]['found'], reverse=True)
                continuations = [pool.submit(work, seed, min(24, remaining_pages), state) for seed, state in candidates]
                for future in concurrent.futures.as_completed(continuations):
                    try:
                        future.result()
                    except Exception as error:
                        emit('log', '追加查询异常：' + str(error)[:160])
        reason = '已停止' if cancel.is_set() else '达到总时限' if time.monotonic() >= deadline else '查询结束'
        summary = f'{reason} · 用时 {time.monotonic()-started:.0f} 秒 · 检查 {requests_count[0]} 页 · 新发现公开链接 {resources_count[0]} 条'
        emit('progress', summary)
        emit('log', summary)
        if not resources_count[0]:
            emit('log', '没有获得公开下载链接。请查看相关帖子和各站失败原因；这不表示论坛没有这首歌。')
    finally:
        emit('crawl_done', None)


def safe_filename(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .')[:150]
    if not name or name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        name = '_' + (name or 'download')
    return name

def download_one(item, folder, cancel, emit):
    if cancel.is_set():
        emit('status', (item['url'], '已暂停'))
        return
    url = item['url']
    key = hashlib.sha256(url.encode()).hexdigest()[:10]
    name = safe_filename(up.unquote(Path(up.urlsplit(url).path).name))
    target = folder / f'{Path(name).stem}_{key}{Path(name).suffix}'
    part = target.with_name(target.name + '.part')
    meta_path = target.with_name(target.name + '.part.json')
    done_path = target.with_name(target.name + '.done.json')
    def status(value):
        emit('status', (url, value))
    try:
        if done_path.exists() and target.exists():
            saved = json.loads(done_path.read_text('utf-8'))
            if saved.get('url') == url and saved.get('size') == target.stat().st_size:
                status('已下载（跳过）')
                return
        if target.exists():
            raise ValueError('同名文件已存在且未验证，保留原文件')
        saved = {}
        if meta_path.exists():
            try:
                saved = json.loads(meta_path.read_text('utf-8'))
            except (ValueError, OSError):
                pass
        offset = part.stat().st_size if part.exists() and saved.get('url') == url and saved.get('validator') else 0
        headers = {'User-Agent': UA, 'Accept-Encoding': 'identity', 'Referer': item.get('source', url)}
        if offset:
            headers.update({'Range': f'bytes={offset}-', 'If-Range': saved['validator']})
        status('连接中')
        with ur.urlopen(ur.Request(url, headers=headers), timeout=30) as response:
            ctype = response.headers.get_content_type()
            if ctype in ('text/html', 'application/xhtml+xml', 'application/json'):
                raise ValueError('链接返回网页或验证页面，并非文件')
            if matches_host(host(response.geturl()), VENDORS):
                raise ValueError('链接跳转到音乐平台，已跳过')
            append = response.status == 206 and offset > 0
            if response.status == 206:
                content_range = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
                if not append or not content_range or int(content_range[1]) != offset:
                    raise ValueError('服务器返回了不匹配的续传范围，已保留临时文件')
                total = int(content_range[3])
            else:
                offset = 0
                total = int(response.headers.get('Content-Length') or 0)
            validator = response.headers.get('ETag') or response.headers.get('Last-Modified') or ''
            if validator.startswith('W/'):
                validator = response.headers.get('Last-Modified') or ''
            meta_path.write_text(json.dumps({'url': url, 'validator': validator}), 'utf-8')
            received = offset
            tick = 0
            with part.open('ab' if append else 'wb') as output:
                first = True
                while not cancel.is_set():
                    block = response.read(256 * 1024)
                    if not block:
                        break
                    if first and not append:
                        sniff = block[:512].lstrip().lower()
                        if sniff.startswith((b'<!doctype html', b'<html', b'<script', b'{"error', b'mz')):
                            raise ValueError('文件内容是网页、错误信息或程序，已拒绝')
                    first = False
                    output.write(block)
                    received += len(block)
                    if time.monotonic() - tick > 0.5:
                        status(f'{received / total:.0%} · {received / 1048576:.1f} MB' if total else f'{received / 1048576:.1f} MB')
                        tick = time.monotonic()
            if cancel.is_set():
                status('已暂停（保留临时文件）')
                return
            if total and received != total:
                raise ValueError('文件传输未完整，可重新下载续传')
            if received == 0:
                raise ValueError('返回了空文件')
        part.replace(target)
        done_path.write_text(json.dumps({'url': url, 'size': received}, ensure_ascii=False), 'utf-8')
        meta_path.unlink(missing_ok=True)
        status('完成')
    except Exception as error:
        status('失败：' + str(error)[:100])
        emit('log', f'下载失败 {item["name"][:45]}：{error}')

class App:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.items = {}
        self.row_ids = {}
        self.crawl_cancel = threading.Event()
        self.download_cancel = threading.Event()
        self.crawling = False
        self.downloading = False
        self.closing = False
        DATA.mkdir(parents=True, exist_ok=True)
        self.config_path = DATA / 'settings.json'
        self.result_path = DATA / 'links.json'
        self.session_log = DATA / f'run-{os.getpid()}.log'
        try:
            self.settings = json.loads(self.config_path.read_text('utf-8'))
        except (OSError, ValueError):
            self.settings = {}
        saved_sites = self.settings.get('selected_sites')
        all_sites = {url for _, url, _ in BUILTIN_SITES}
        if isinstance(saved_sites, list):
            known = set(self.settings.get('known_sites', LEGACY_SITE_URLS))
            self.selected_sites = (set(saved_sites) & all_sites) | (all_sites - known)
        else:
            self.selected_sites = all_sites
        self.favorite_ids = set(self.settings.get('favorite_recommendations', []))
        self.recommendation_ids = []
        root.title('拾音 1.5 · 论坛音乐链接助手')
        root.geometry(f'{min(1440, root.winfo_screenwidth()-60)}x{min(1000, root.winfo_screenheight()-100)}')
        root.minsize(min(1120, root.winfo_screenwidth()-60), min(840, root.winfo_screenheight()-100))
        root.configure(bg='#f5f1e9')
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('.', font=('Microsoft YaHei UI', 10))
        style.configure('TFrame', background='#f5f1e9')
        style.configure('TLabel', background='#f5f1e9', foreground='#303d38')
        style.configure('TButton', padding=(12, 7))
        style.configure('Accent.TButton', background='#356455', foreground='white')
        style.configure('Treeview', rowheight=32, background='white', fieldbackground='white')
        style.configure('Treeview.Heading', font=('Microsoft YaHei UI', 10, 'bold'), padding=7)
        style.configure('TNotebook', background=BG, borderwidth=0, tabmargins=(18, 12, 0, 4))
        style.configure('TNotebook.Tab', background='#e8e9df', foreground=MUTED, padding=(23, 11), borderwidth=0)
        style.map('TNotebook.Tab', background=[('selected', GREEN)], foreground=[('selected', 'white')])
        style.configure('TEntry', fieldbackground='#fffdf8', foreground=INK, bordercolor='#d8dccf', padding=6)
        style.configure('TCombobox', fieldbackground='#fffdf8', background=PALE, foreground=INK, arrowcolor=GREEN, padding=6)
        style.map('TCombobox', fieldbackground=[('readonly', '#fffdf8')], foreground=[('readonly', INK)])
        style.configure('TSpinbox', fieldbackground='#fffdf8', foreground=INK, padding=5, arrowcolor=GREEN)
        style.configure('TCheckbutton', background=BG, foreground=INK)
        style.map('TCheckbutton', background=[('active', BG)])
        style.configure('Vertical.TScrollbar', background='#c8d0bf', troughcolor=BG, borderwidth=0, arrowsize=12)
        style.configure('Treeview', background='#fffdf8', fieldbackground='#fffdf8', foreground=INK, rowheight=36, borderwidth=0)
        style.map('Treeview', background=[('selected', '#dce7da')], foreground=[('selected', GREEN)])
        style.configure('Treeview.Heading', background=PALE, foreground=GREEN, relief='flat', borderwidth=0)
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill='both', expand=True)
        self.collect_tab = ttk.Frame(self.notebook)
        self.discover_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.discover_tab, text='  发现音乐  ')
        self.notebook.add(self.collect_tab, text='  搜集与下载  ')
        outer = ttk.Frame(self.collect_tab, padding=22)
        outer.pack(fill='both', expand=True)
        collect_header = ttk.Frame(outer)
        collect_header.pack(fill='x')
        ttk.Label(collect_header, text='拾音 · 音乐资源工作台', font=('Microsoft YaHei UI', 17, 'bold')).pack(side='left')
        self.mini_mascot = None
        if (ASSETS / 'fox-music.png').exists():
            original = tk.PhotoImage(file=str(ASSETS / 'fox-music.png'))
            factor = max(1, (original.height() + 61) // 62)
            self.mini_mascot = original.subsample(factor, factor)
            ttk.Label(collect_header, image=self.mini_mascot).pack(side='right')
            root.iconphoto(True, self.mini_mascot)
        ttk.Label(outer, text='把零散帖子变成一张下载清单。公开页面搜集 · 网盘整理 · 直链批量下载', foreground='#7a847c').pack(anchor='w', pady=(3, 16))
        upper = ttk.Frame(outer)
        upper.pack(fill='x')
        upper.columnconfigure(0, weight=1)
        upper.columnconfigure(1, weight=0)
        left = ttk.Frame(upper)
        left.grid(row=0, column=0, sticky='nsew')
        ttk.Label(left, text='额外帖子 / 网站地址（可留空，每行一个）', wraplength=550).pack(anchor='w')
        self.sources = tk.Text(left, width=1, height=3, font=('Microsoft YaHei UI', 10), relief='flat', padx=10, pady=8, undo=True)
        self.sources.configure(bg='#fffdf8', fg=INK, insertbackground=GREEN, highlightthickness=1, highlightbackground='#e2dfd2', highlightcolor=GREEN)
        self.sources.pack(fill='x', pady=(6, 0))
        self.sources.insert('1.0', self.settings.get('sources', ''))
        right = ttk.Frame(upper, padding=(18, 0, 0, 0))
        right.grid(row=0, column=1, sticky='nsew')
        ttk.Label(right, text='歌手 / 专辑 / 歌名（可留空）').pack(anchor='w')
        self.keyword = tk.StringVar(value=self.settings.get('keyword', ''))
        ttk.Entry(right, textvariable=self.keyword, width=22).pack(fill='x', pady=(6, 9))
        options = ttk.Frame(right)
        options.pack(fill='x')
        ttk.Label(options, text='最多页面').pack(side='left')
        self.limit = tk.IntVar(value=self.settings.get('page_limit', 100))
        ttk.Spinbox(options, from_=1, to=500, textvariable=self.limit, width=5).pack(side='left', padx=(5, 12))
        ttk.Label(options, text='展开层数').pack(side='left')
        self.depth = tk.IntVar(value=1)
        ttk.Spinbox(options, from_=0, to=3, textvariable=self.depth, width=3).pack(side='left', padx=5)
        bar = ttk.Frame(outer)
        bar.pack(fill='x', pady=12)
        self.start_button = SoftButton(bar, text='开始搜集', style='Accent.TButton', command=self.start_crawl)
        self.start_button.pack(side='left')
        SoftButton(bar, text='停止搜集', command=self.crawl_cancel.set).pack(side='left', padx=6)
        SoftButton(bar, text='导入帖子文本', command=self.import_text).pack(side='left')
        SoftButton(bar, text='站内搜索', command=self.search).pack(side='left', padx=6)
        SoftButton(bar, text='浏览器采集助手', command=self.browser_helper).pack(side='left')
        self.sites_button = SoftButton(bar, text=f'内置网站（已选 {len(self.selected_sites)}）', command=self.choose_sites)
        self.sites_button.pack(side='left', padx=6)
        table_frame = ttk.Frame(outer)
        self.progress_label = ttk.Label(outer, text='准备就绪 · 关键词查询会优先使用论坛公开搜索入口', foreground='#356455', wraplength=1120)
        self.progress_label.pack(fill='x', pady=(0, 7))
        table_frame.pack(fill='both', expand=True)
        columns = ('kind', 'name', 'code', 'source', 'status')
        self.tree = ttk.Treeview(table_frame, columns=columns, show='headings', selectmode='extended', height=3)
        for key, title, width in [('kind', '类型', 100), ('name', '文件 / 分享标题', 370), ('code', '提取码*', 85), ('source', '来源', 180), ('status', '状态', 230)]:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=65, stretch=(key in ('name', 'status')))
        scrollbar = ttk.Scrollbar(table_frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        self.tree.bind('<Double-1>', lambda _: self.open_selected())
        actions = ttk.Frame(outer)
        actions.pack(fill='x', pady=10)
        self.download_button = SoftButton(actions, text='批量下载直链', style='Accent.TButton', command=self.start_download)
        self.download_button.pack(side='left')
        SoftButton(actions, text='暂停下载', command=self.download_cancel.set).pack(side='left', padx=6)
        SoftButton(actions, text='打开选中链接', command=self.open_selected).pack(side='left')
        SoftButton(actions, text='复制链接和提取码', command=self.copy_selected).pack(side='left', padx=6)
        SoftButton(actions, text='导出 CSV', command=self.export).pack(side='left')
        SoftButton(actions, text='清空清单', command=self.clear).pack(side='right')
        directory = ttk.Frame(outer)
        directory.pack(fill='x')
        ttk.Label(directory, text='下载到').pack(side='left')
        self.folder = tk.StringVar(value=self.settings.get('folder', str(Path.home() / 'Downloads' / '拾音')))
        ttk.Entry(directory, textvariable=self.folder).pack(side='left', fill='x', expand=True, padx=8)
        SoftButton(directory, text='选择目录', command=self.choose_folder).pack(side='left')
        SoftButton(directory, text='打开目录', command=self.open_folder).pack(side='left', padx=(6, 0))
        self.count_label = ttk.Label(outer, text='准备就绪。支持 FLAC / APE / WAV 等音频和压缩包直链。', foreground='#7a847c')
        self.count_label.pack(anchor='w', pady=(10, 4))
        self.log_widget = tk.Text(outer, height=3, font=('Microsoft YaHei UI', 9), bg='#e8eadd', fg='#59685e', relief='flat', padx=10, pady=7, state='disabled')
        self.log_widget.pack(fill='x', before=table_frame, pady=(0, 8))
        ttk.Label(outer, text='提示：多选用 Ctrl / Shift；未选中时批量下载全部直链。* 提取码为自动识别，请核对原帖。扩展名不能证明音源音质。', foreground='#7a847c', font=('Microsoft YaHei UI', 9)).pack(anchor='w', pady=(7, 0))
        try:
            for item in json.loads(self.result_path.read_text('utf-8')):
                if normalize(item.get('url', '')) and (classify(item['url']) or item.get('kind') == '相关帖子'):
                    if item.get('status', '').startswith(('连接', '0%', '1%')) or ' MB' in item.get('status', ''):
                        item['status'] = '待下载'
                    self.add_item(item)
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self.build_discovery()
        self.notebook.select(self.collect_tab if self.settings.get('active_tab') == 'collect' else self.discover_tab)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(150, self.poll)

    def build_discovery(self):
        panel = ttk.Frame(self.discover_tab, padding=22)
        panel.pack(fill='both', expand=True)
        self.hero = tk.Canvas(panel, height=200, bg=BG, highlightthickness=0)
        self.hero.pack(fill='x', pady=(0, 18))
        self.mascot_image = None
        if (ASSETS / 'fox-music.png').exists():
            original = tk.PhotoImage(file=str(ASSETS / 'fox-music.png'))
            factor = max(1, (original.height() + 187) // 188)
            self.mascot_image = original.subsample(factor, factor)
        def draw_hero(event=None):
            c = self.hero
            c.delete('all')
            w = c.winfo_width()
            rounded_shape(c, 0, 0, w, 200, 24, fill='#e4eadf', outline='')
            c.create_oval(w-295, -130, w+90, 270, fill='#d4decf', outline='')
            paw(c, w-260, 118, 2.3, '#c3d0bd')
            paw(c, w-313, 50, 1.3, '#cbd6c5')
            c.create_text(26, 27, anchor='w', text='拾音  /  FOX & VINYL', fill=GREEN, font=('Microsoft YaHei UI', 9, 'bold'))
            c.create_text(26, 79, anchor='w', text='今天，想听点什么？', fill=INK, font=('Microsoft YaHei UI', 22, 'bold'))
            c.create_text(28, 129, anchor='w', text='戴上耳机，跟小狐狸一起发现下一张心动专辑。', fill='#59685e', font=('Microsoft YaHei UI', 10))
            c.create_text(28, 167, anchor='w', text='精选推荐  ·  自由分类  ·  收藏喜欢的声音', fill='#75816e', font=('Microsoft YaHei UI', 9))
            if self.mascot_image:
                c.create_image(w-115, 103, image=self.mascot_image)
        self.hero.bind('<Configure>', draw_hero)
        filters = ttk.Frame(panel)
        filters.pack(fill='x')
        preferences = self.settings.get('discovery', {})
        self.discovery_region = tk.StringVar(value=preferences.get('region', '全部'))
        self.discovery_genre = tk.StringVar(value=preferences.get('genre', '全部'))
        self.discovery_mood = tk.StringVar(value=preferences.get('mood', '全部'))
        for label, field, variable in [('方向', 'region', self.discovery_region), ('风格', 'genre', self.discovery_genre), ('心情 / 场景', 'mood', self.discovery_mood)]:
            ttk.Label(filters, text=label).pack(side='left', padx=(0, 7))
            choices = ['全部'] + sorted({item[field] for item in RECOMMENDATIONS})
            if variable.get() not in choices:
                variable.set('全部')
            box = ttk.Combobox(filters, textvariable=variable, values=choices, state='readonly', width=12)
            box.pack(side='left', padx=(0, 18))
            box.bind('<<ComboboxSelected>>', lambda _: self.refresh_discovery())
        toolbar = ttk.Frame(panel)
        toolbar.pack(fill='x', pady=12)
        SoftButton(toolbar, text='换一批推荐', style='Accent.TButton', command=self.refresh_discovery).pack(side='left')
        SoftButton(toolbar, text='随便来一个', command=lambda: self.refresh_discovery(count=1)).pack(side='left', padx=7)
        self.only_favorites = tk.BooleanVar(value=preferences.get('favorites_only', False))
        ttk.Checkbutton(toolbar, text='只看我的收藏', variable=self.only_favorites, command=self.refresh_discovery).pack(side='left', padx=8)
        SoftButton(toolbar, text='重置分类', command=self.reset_discovery).pack(side='right')
        self.discovery_status = ttk.Label(panel, text='', foreground='#7a847c')
        self.discovery_status.pack(anchor='w', pady=(0, 8))
        container = ttk.Frame(panel)
        container.pack(fill='both', expand=True)
        self.discovery_canvas = tk.Canvas(container, bg='#f5f1e9', highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient='vertical', command=self.discovery_canvas.yview)
        self.discovery_canvas.configure(yscrollcommand=scrollbar.set)
        self.discovery_canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        self.recommendation_cards = ttk.Frame(self.discovery_canvas)
        window = self.discovery_canvas.create_window((0, 0), window=self.recommendation_cards, anchor='nw')
        self.discovery_canvas.bind('<Configure>', lambda event: self.discovery_canvas.itemconfigure(window, width=event.width))
        self.recommendation_cards.bind('<Configure>', lambda _: self.discovery_canvas.configure(scrollregion=self.discovery_canvas.bbox('all')))
        self.recommendation_cards.columnconfigure(0, weight=1, uniform='cards')
        self.recommendation_cards.columnconfigure(1, weight=1, uniform='cards')
        def wheel(event):
            if self.notebook.select() == str(self.discover_tab):
                x, y = self.root.winfo_pointerxy()
                left, top = self.discovery_canvas.winfo_rootx(), self.discovery_canvas.winfo_rooty()
                if left <= x <= left + self.discovery_canvas.winfo_width() and top <= y <= top + self.discovery_canvas.winfo_height():
                    self.discovery_canvas.yview_scroll(-int(event.delta / 120), 'units')
        self.root.bind('<MouseWheel>', wheel, add='+')
        self.refresh_discovery(persist=False)

    def reset_discovery(self):
        for variable in (self.discovery_region, self.discovery_genre, self.discovery_mood):
            variable.set('全部')
        self.only_favorites.set(False)
        self.refresh_discovery()

    def refresh_discovery(self, count=6, persist=True, keep_current=False):
        pool = recommendation_pool(self.discovery_region.get(), self.discovery_genre.get(), self.discovery_mood.get(),
                                   self.favorite_ids if self.only_favorites.get() else None)
        if keep_current:
            by_id = {item['id']: item for item in pool}
            picks = [by_id[key] for key in self.recommendation_ids if key in by_id]
        else:
            picks = pick_recommendations(pool, self.recommendation_ids, count)
        self.recommendation_ids = [item['id'] for item in picks]
        self.discovery_status.configure(text=f'精选主题 · 当前分类 {len(pool)} 个 · 推荐 {len(picks)} 个 · 收藏 {len(self.favorite_ids)} 个')
        for widget in self.recommendation_cards.winfo_children():
            widget.destroy()
        if not picks:
            text = '还没有符合分类的收藏。可先关闭“只看我的收藏”，找到喜欢的再收藏。' if self.only_favorites.get() else '这个组合暂时没有推荐，试着把一个分类改成“全部”，或点击“重置分类”。'
            ttk.Label(self.recommendation_cards, text=text, wraplength=800, padding=25).grid(row=0, column=0, columnspan=2, sticky='ew')
        for index, item in enumerate(picks):
            shell = RoundedCard(self.recommendation_cards)
            shell.grid(row=index // 2, column=index % 2, sticky='nsew', padx=(0, 14) if index % 2 == 0 else (0, 0), pady=(0, 14))
            card = shell.content
            card_header = tk.Frame(card, bg='#fffdf8')
            card_header.pack(fill='x')
            tk.Label(card_header, text=f'{item["region"]}  /  {item["genre"]}  /  {item["mood"]}', bg='#fffdf8', fg='#356455', font=('Microsoft YaHei UI', 9)).pack(side='left')
            stamp = tk.Canvas(card_header, width=30, height=29, bg='#fffdf8', highlightthickness=0)
            stamp.pack(side='right')
            paw(stamp, 15, 16, 1, '#d8c4a5')
            tk.Label(card, text=item['work'] or '从这位音乐人开始', bg='#fffdf8', fg='#303d38', font=('Microsoft YaHei UI', 15, 'bold'), wraplength=430, justify='left').pack(anchor='w', pady=(9, 3))
            tk.Label(card, text=item['artist'], bg='#fffdf8', fg='#59685e', font=('Microsoft YaHei UI', 11)).pack(anchor='w')
            tk.Label(card, text=item['reason'], bg='#fffdf8', fg='#7a847c', font=('Microsoft YaHei UI', 10), wraplength=430, justify='left').pack(anchor='w', pady=(9, 13))
            buttons = tk.Frame(card, bg='#fffdf8')
            buttons.pack(fill='x')
            SoftButton(buttons, text='搜集此推荐', style='Accent.TButton', command=lambda selected=item: self.use_recommendation(selected, True)).pack(side='left')
            SoftButton(buttons, text='只填关键词', command=lambda selected=item: self.use_recommendation(selected, False)).pack(side='left', padx=6)
            SoftButton(buttons, text='已收藏' if item['id'] in self.favorite_ids else '收藏', command=lambda selected=item: self.toggle_favorite(selected)).pack(side='right')
        self.discovery_canvas.yview_moveto(0)
        if persist:
            self.save()

    def toggle_favorite(self, item):
        if item['id'] in self.favorite_ids:
            self.favorite_ids.remove(item['id'])
        else:
            self.favorite_ids.add(item['id'])
        self.refresh_discovery(keep_current=True)

    def use_recommendation(self, item, start):
        if self.crawling and start:
            messagebox.showinfo('查询仍在运行', '先停止当前查询或等它结束，再搜集这条推荐。')
            return
        self.keyword.set(item['query'])
        self.notebook.select(self.collect_tab)
        self.progress_label.configure(text='已填入推荐：' + item['query'])
        self.save()
        if start:
            self.start_crawl()

    def emit(self, kind, value):
        self.events.put((kind, value))

    def log(self, text):
        try:
            with self.session_log.open('a', encoding='utf-8') as output:
                output.write(time.strftime('%Y-%m-%d %H:%M:%S') + '  ' + text + '\n')
        except OSError:
            pass
        self.log_widget.configure(state='normal')
        self.log_widget.insert('end', time.strftime('%H:%M:%S') + '  ' + text + '\n')
        if int(self.log_widget.index('end-1c').split('.')[0]) > 600:
            self.log_widget.delete('1.0', '100.0')
        self.log_widget.see('end')
        self.log_widget.configure(state='disabled')

    def save(self):
        settings = {'sources': self.sources.get('1.0', 'end').strip(), 'selected_sites': [url for _, url, _ in BUILTIN_SITES if url in self.selected_sites], 'keyword': self.keyword.get(), 'folder': self.folder.get(),
                    'known_sites': [url for _, url, _ in BUILTIN_SITES], 'page_limit': self.limit.get(),
                    'favorite_recommendations': sorted(self.favorite_ids),
                    'active_tab': 'collect' if self.notebook.select() == str(self.collect_tab) else 'discover',
                    'discovery': {'region': self.discovery_region.get(), 'genre': self.discovery_genre.get(), 'mood': self.discovery_mood.get(), 'favorites_only': self.only_favorites.get()}}
        self.config_path.write_text(json.dumps(settings, ensure_ascii=False), 'utf-8')
        temporary = self.result_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(list(self.items.values()), ensure_ascii=False, indent=2), 'utf-8')
        temporary.replace(self.result_path)

    def add_item(self, item):
        url = item['url']
        if url in self.items:
            if item['kind'] == '相关帖子' and self.items[url].get('kind') == '相关帖子':
                self.items[url].update(item)
                self.tree.set(self.row_ids[url], 'status', item['status'])
            return
        self.items[url] = item
        self.row_ids[url] = self.tree.insert('', 'end', values=(item['kind'], item['name'], item.get('code', ''), host(item['source']), item['status']))
        cloud = sum(i['kind'] == '网盘' for i in self.items.values())
        posts = sum(i['kind'] == '相关帖子' for i in self.items.values())
        self.count_label.configure(text=f'共 {len(self.items)} 条 · 相关帖子 {posts} · 直链 {len(self.items) - cloud - posts} · 网盘 {cloud} · 自动去重')

    def start_crawl(self):
        if self.crawling:
            return
        urls = []
        raw_sources = [url for _, url, _ in BUILTIN_SITES if url in self.selected_sites]
        raw_sources.extend(self.sources.get('1.0', 'end').splitlines())
        for line in raw_sources:
            if line.strip():
                url = normalize(line.strip())
                if not url:
                    messagebox.showerror('地址格式', '请输入完整的 http:// 或 https:// 地址，每行一个。')
                    return
                if matches_host(host(url), VENDORS):
                    messagebox.showinfo('来源', '请填写论坛或网友分享地址；此工具不适配音乐厂商平台。')
                    return
                if url not in urls:
                    urls.append(url)
        try:
            limit, depth = self.limit.get(), self.depth.get()
            if not 1 <= limit <= 500 or not 0 <= depth <= 3:
                raise ValueError()
        except (ValueError, tk.TclError):
            messagebox.showerror('范围', '页面数应为 1～500，展开层数应为 0～3。')
            return
        if not urls:
            messagebox.showinfo('添加来源', '先粘贴论坛、版块或帖子地址，也可以导入已复制的帖子文本。')
            return
        self.reset_results()
        self.save()
        self.crawling = True
        self.crawl_cancel.clear()
        self.start_button.configure(state='disabled')
        self.progress_label.configure(text='正在启动查询……')
        self.log('已开始新搜索：自动清空上次结果，下载文件和收藏不受影响。')
        threading.Thread(target=crawl, args=(urls, self.keyword.get().strip(), limit, depth, self.crawl_cancel, self.emit), daemon=True).start()

    def reset_results(self):
        rows = self.tree.get_children()
        if rows:
            self.tree.delete(*rows)
        self.items.clear()
        self.row_ids.clear()
        self.count_label.configure(text='新搜索已就绪 · 等待本轮结果')

    def choose_sites(self):
        dialog = tk.Toplevel(self.root)
        dialog.title('内置音乐网站')
        dialog.geometry(f'{min(1100, self.root.winfo_screenwidth()-80)}x{min(850, self.root.winfo_screenheight()-100)}')
        dialog.transient(self.root)
        panel = ttk.Frame(dialog, padding=20)
        panel.pack(fill='both', expand=True)
        ttk.Label(panel, text='选择要搜集的网站', font=('Microsoft YaHei UI', 16, 'bold')).pack(anchor='w')
        ttk.Label(panel, text='所选网站与主界面填写的额外地址合并；开始搜集和站内搜索都会使用。').pack(anchor='w', pady=(5, 15))
        site_container = ttk.Frame(panel)
        site_container.pack(fill='both', expand=True)
        site_canvas = tk.Canvas(site_container, bg=BG, highlightthickness=0)
        site_scrollbar = ttk.Scrollbar(site_container, orient='vertical', command=site_canvas.yview)
        site_canvas.configure(yscrollcommand=site_scrollbar.set)
        site_canvas.pack(side='left', fill='both', expand=True)
        site_scrollbar.pack(side='right', fill='y')
        site_rows = ttk.Frame(site_canvas)
        window = site_canvas.create_window((0, 0), window=site_rows, anchor='nw')
        site_canvas.bind('<Configure>', lambda event: site_canvas.itemconfigure(window, width=event.width))
        site_rows.bind('<Configure>', lambda _: site_canvas.configure(scrollregion=site_canvas.bbox('all')))
        dialog.bind('<MouseWheel>', lambda event: site_canvas.yview_scroll(-int(event.delta/120), 'units'))
        variables = {}
        for name, url, note in BUILTIN_SITES:
            row = ttk.Frame(site_rows)
            row.pack(fill='x', pady=5)
            variable = tk.BooleanVar(value=url in self.selected_sites)
            variables[url] = variable
            ttk.Checkbutton(row, text=name, variable=variable, width=19).pack(side='left')
            ttk.Label(row, text=note, foreground='#7a847c', wraplength=470).pack(side='left', padx=8)
            SoftButton(row, text='打开网站', command=lambda address=url: webbrowser.open(address)).pack(side='right')
        ttk.Label(panel, text='内置地址不代表已完成专站适配。登录、校验和隐藏内容仍按原有方式处理。', foreground='#7a847c', wraplength=780).pack(anchor='w', pady=(16, 12))
        buttons = ttk.Frame(panel)
        buttons.pack(fill='x')
        SoftButton(buttons, text='全选', command=lambda: [v.set(True) for v in variables.values()]).pack(side='left')
        SoftButton(buttons, text='全不选', command=lambda: [v.set(False) for v in variables.values()]).pack(side='left', padx=6)
        def apply_selection():
            self.selected_sites = {url for url, variable in variables.items() if variable.get()}
            self.sites_button.configure(text=f'内置网站（已选 {len(self.selected_sites)}）')
            self.save()
            self.log(f'已选择 {len(self.selected_sites)} 个内置网站，下次搜集和搜索时生效。')
            dialog.destroy()
        SoftButton(buttons, text='保存选择', style='Accent.TButton', command=apply_selection).pack(side='right')

    def selected(self):
        selected_ids = set(self.tree.selection())
        return [item for url, item in self.items.items() if self.row_ids[url] in selected_ids]

    def start_download(self):
        if self.downloading:
            return
        items = [i.copy() for i in (self.selected() or list(self.items.values())) if i['kind'] in ('音频直链', '压缩包直链')]
        if not items:
            messagebox.showinfo('没有直链', '网盘分享页需要打开后下载。请选择音频或压缩包直链。')
            return
        try:
            folder = Path(self.folder.get()).expanduser().resolve()
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            messagebox.showerror('目录不可用', str(error))
            return
        self.save()
        self.downloading = True
        self.download_cancel.clear()
        self.download_button.configure(state='disabled')
        self.log(f'下载队列：{len(items)} 个文件，同时下载 2 个。')
        def worker():
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(download_one, item, folder, self.download_cancel, self.emit) for item in items]
                for future in concurrent.futures.as_completed(futures):
                    try:
                        future.result()
                    except Exception as error:
                        self.emit('log', str(error))
            self.emit('download_done', None)
        threading.Thread(target=worker, daemon=True).start()

    def open_selected(self):
        items = self.selected()
        if not items:
            return
        if len(items) > 8 and not messagebox.askyesno('打开多个链接', f'将打开 {len(items)} 个浏览器标签页，继续？'):
            return
        for item in items:
            webbrowser.open(item['url'])

    def copy_selected(self):
        items = self.selected() or list(self.items.values())
        self.root.clipboard_clear()
        self.root.clipboard_append('\n\n'.join(f'{i["name"]}\n{i["url"]}' + (f'\n提取码：{i["code"]}' if i.get('code') else '') for i in items))
        self.log(f'已复制 {len(items)} 条链接。')

    def export(self):
        path = filedialog.asksaveasfilename(defaultextension='.csv', initialfile='音乐链接清单.csv', filetypes=[('CSV 表格', '*.csv')])
        if not path:
            return
        with open(path, 'w', encoding='utf-8-sig', newline='') as output:
            writer = csv.writer(output)
            writer.writerow(['类型', '名称', '链接', '提取码（待核对）', '来源帖子', '状态'])
            for i in self.items.values():
                # Keep forum text from becoming a spreadsheet formula.
                writer.writerow([("'" + str(v)) if str(v).lstrip().startswith(('=', '+', '-', '@')) else v for v in (i['kind'], i['name'], i['url'], i.get('code', ''), i['source'], i['status'])])
        self.log('已导出：' + path)

    def import_text(self):
        dialog = tk.Toplevel(self.root)
        dialog.title('粘贴帖子文本')
        dialog.geometry('740x480')
        ttk.Label(dialog, text='把你能访问的帖子内容粘贴到这里，自动识别链接和附近的提取码。', padding=12).pack(anchor='w')
        text = tk.Text(dialog, font=('Microsoft YaHei UI', 10), wrap='word')
        text.pack(fill='both', expand=True, padx=12)
        def submit():
            raw = text.get('1.0', 'end')
            original_title = re.search(r'^标题：(.+)$', raw, re.MULTILINE)
            original_source = re.search(r'^来源：(https?://\S+)', raw, re.MULTILINE)
            # Escape pasted text so literal angle brackets do not disappear as HTML tags.
            items, _, _, _ = parse_resources('<title>手动导入</title><pre>' + html.escape(raw) + '</pre>', 'https://manual.invalid/')
            for item in items:
                item['source'] = normalize(original_source[1]) if original_source else ''
                if original_title:
                    item['title'] = original_title[1].strip()
                self.add_item(item)
            self.save()
            self.log(f'文本导入完成：识别 {len(items)} 条链接。')
            dialog.destroy()
        SoftButton(dialog, text='识别并加入清单', command=submit).pack(pady=12)

    def browser_helper(self):
        path = BASE / '浏览器采集助手.html'
        if path.exists():
            webbrowser.open(path.as_uri())
        else:
            messagebox.showinfo('浏览器采集', '请打开随附的浏览器采集助手.html。')

    def search(self):
        keyword = self.keyword.get().strip()
        if not keyword:
            messagebox.showinfo('搜索词', '先填写歌手、专辑或歌名。')
            return
        urls = combine_sources(self.sources.get('1.0', 'end'), self.selected_sites)
        hosts = list(dict.fromkeys(host(url) for url in urls if not classify(url)))
        query = keyword + ' 无损 FLAC ' + ('(' + ' OR '.join('site:' + h for h in hosts) + ')' if hosts else '论坛 分享')
        webbrowser.open('https://www.bing.com/search?' + up.urlencode({'q': query}))
        self.log('已在浏览器打开论坛搜索；将找到的版块或帖子地址粘贴到来源框即可批量搜集。')

    def choose_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.folder.set(folder)

    def open_folder(self):
        try:
            folder = Path(self.folder.get()).expanduser().resolve()
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(str(folder))
        except OSError as error:
            messagebox.showerror('无法打开', str(error))

    def clear(self):
        if self.crawling or self.downloading:
            messagebox.showinfo('任务运行中', '先停止搜集、暂停下载，等待结束后再清空。')
            return
        if self.items and messagebox.askyesno('清空清单', '只清空链接清单，已经下载的文件不会删除。继续？'):
            self.tree.delete(*self.tree.get_children())
            self.items.clear()
            self.row_ids.clear()
            self.count_label.configure(text='清单已清空。')
            self.save()

    def poll(self):
        for _ in range(250):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'resource':
                self.add_item(value)
            elif kind == 'log':
                self.log(value)
            elif kind == 'progress':
                self.progress_label.configure(text=value)
            elif kind == 'status':
                url, status = value
                if url in self.items:
                    self.items[url]['status'] = status
                    self.tree.set(self.row_ids[url], 'status', status)
            elif kind == 'crawl_done':
                self.crawling = False
                self.start_button.configure(state='normal')
                self.save()
            elif kind == 'download_done':
                self.downloading = False
                self.download_button.configure(state='normal')
                self.log('下载队列已结束。失败项可选中后重试。')
                self.save()
        if self.closing and not self.downloading and not self.crawling:
            self.save()
            self.root.destroy()
            return
        self.root.after(150, self.poll)

    def close(self):
        if self.closing:
            return
        if self.crawling or self.downloading:
            self.closing = True
            self.crawl_cancel.set()
            self.download_cancel.set()
            self.log('正在停止任务并保存临时文件，请稍候……')
            self.root.title('拾音 · 正在保存并退出')
        else:
            self.save()
            self.root.destroy()

if __name__ == '__main__':
    configure_dpi()
    root = tk.Tk()
    App(root)
    root.mainloop()
