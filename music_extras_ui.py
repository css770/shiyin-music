"""Tk widgets for lyrics and BaiduPCS-Go; workers communicate by app events."""
from dataclasses import replace
from pathlib import Path
import os
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import webbrowser

import music_extras as extras


class ExtraFeatures:
    def init_extras(self, data_dir, button):
        self.extra_data = data_dir
        self.extra_button = button
        self.extra_cancel = threading.Event()
        self.extra_jobs = 0
        self.pcs_busy = False
        self.lyrics_busy = False
        self.lyric_paths = {}
        self.pcs_login = None
        self.auto_lyrics_enabled = tk.BooleanVar(value=self.settings.get('auto_lyrics', True))
        default_pcs = next((data_dir / 'tools').glob('*/BaiduPCS-Go.exe'), Path('')) if (data_dir / 'tools').exists() else Path('')
        self.pcs_path = tk.StringVar(value=self.settings.get('pcs_path') or (str(default_pcs) if default_pcs.is_file() else ''))
        self.extras_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.extras_tab, text='  歌词与网盘  ')
        outer = ttk.Frame(self.extras_tab, padding=22)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='给音乐补上歌词，让网盘链接接着下载', font=('Microsoft YaHei UI', 20, 'bold')).pack(anchor='w')
        ttk.Label(outer, text='歌词保存在音频旁边；百度分享可多选后批量转存并下载。', foreground='#7a847c').pack(anchor='w', pady=(5, 12))
        cloud = ttk.LabelFrame(outer, text='百度网盘 · BaiduPCS-Go', padding=12)
        cloud.pack(fill='x')
        entry_row = ttk.Frame(cloud)
        entry_row.pack(fill='x')
        ttk.Label(entry_row, text='工具位置').pack(side='left')
        ttk.Entry(entry_row, textvariable=self.pcs_path).pack(side='left', fill='x', expand=True, padx=8)
        button(entry_row, text='选择工具', command=self.choose_pcs).pack(side='left')
        cloud_buttons = ttk.Frame(cloud)
        cloud_buttons.pack(fill='x', pady=(9, 0))
        self.pcs_install_button = button(cloud_buttons, text='一键安装开源工具', command=self.install_pcs_tool)
        self.pcs_install_button.pack(side='left')
        button(cloud_buttons, text='登录 / 账号终端', command=self.login_pcs).pack(side='left', padx=6)
        button(cloud_buttons, text='检测登录', command=self.check_pcs).pack(side='left')
        self.pcs_download_button = button(cloud_buttons, text='下载清单中的百度分享', style='Accent.TButton', command=self.start_baidu)
        self.pcs_download_button.pack(side='left', padx=6)
        button(cloud_buttons, text='开源项目', command=lambda: webbrowser.open(extras.PCS_REPO)).pack(side='right')
        ttk.Label(cloud, text='首次在工具终端完成登录。转存到“/拾音下载/分享编号”；暂停会保留转存文件与下载进度。', wraplength=1040, foreground='#7a847c').pack(anchor='w', pady=(8, 0))
        lyrics = ttk.LabelFrame(outer, text='歌词 · LRCLIB', padding=12)
        lyrics.pack(fill='both', expand=True, pady=(14, 0))
        ttk.Checkbutton(lyrics, text='音频下载完成后自动匹配歌词（优先 LRC，无时间轴时保存 TXT）', variable=self.auto_lyrics_enabled, command=self.save).pack(anchor='w')
        ttk.Label(lyrics, text='读取歌曲标签和时长；没有标签时尝试“歌手 - 歌名”。已有歌词保留，不改动音乐文件。', foreground='#7a847c', wraplength=1040).pack(anchor='w', pady=(4, 9))
        row = ttk.Frame(lyrics)
        row.pack(fill='x')
        button(row, text='添加音频文件', command=self.add_lyric_files).pack(side='left')
        button(row, text='扫描下载目录', command=self.scan_lyrics).pack(side='left', padx=6)
        self.lyrics_button = button(row, text='批量补歌词', style='Accent.TButton', command=self.start_lyrics_batch)
        self.lyrics_button.pack(side='left')
        button(row, text='手动匹配所选', command=self.manual_lyrics).pack(side='left', padx=6)
        button(row, text='停止歌词 / 网盘', command=self.extra_cancel.set).pack(side='left')
        button(row, text='清空列表', command=self.clear_lyric_list).pack(side='right')
        table = ttk.Frame(lyrics)
        table.pack(fill='both', expand=True, pady=(10, 0))
        self.lyric_tree = ttk.Treeview(table, columns=('name', 'artist', 'status'), show='headings', selectmode='extended', height=4)
        for key, title, width in [('name', '歌曲 / 文件名', 420), ('artist', '歌手', 200), ('status', '歌词状态', 330)]:
            self.lyric_tree.heading(key, text=title)
            self.lyric_tree.column(key, width=width, minwidth=100)
        self.lyric_tree.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(table, orient='vertical', command=self.lyric_tree.yview)
        scroll.pack(side='right', fill='y')
        self.lyric_tree.configure(yscrollcommand=scroll.set)
        self.extra_status = ttk.Label(outer, text='准备就绪 · 歌词查询只发送歌名、歌手与专辑信息。', foreground='#356455', wraplength=1050)
        self.extra_status.pack(fill='x', pady=(10, 0))

    def extra_settings(self):
        return {'auto_lyrics': self.auto_lyrics_enabled.get(), 'pcs_path': self.pcs_path.get().strip()}

    def extra_job(self, function):
        if self.closing:
            return
        if not self.extra_jobs:
            self.extra_cancel.clear()
        self.extra_jobs += 1
        def work():
            try:
                function()
            except extras.Cancelled as error:
                self.emit('extra_message', str(error))
            except Exception as error:
                # Only our bridge errors are surfaced; no raw tool stdout.
                self.emit('extra_message', '任务未完成：' + str(error)[:180])
            finally:
                self.emit('extra_done', None)
        threading.Thread(target=work, daemon=True).start()

    def handle_extra_event(self, kind, value):
        if kind == 'extra_message':
            self.extra_status.configure(text=value)
            self.log(value)
        elif kind == 'extra_done':
            self.extra_jobs -= 1
        elif kind == 'lyrics_finished':
            self.lyrics_busy = False
            self.lyrics_button.configure(state='normal')
        elif kind == 'pcs_finished':
            self.pcs_busy = False
            self.pcs_download_button.configure(state='normal')
        elif kind == 'pcs_installed':
            self.pcs_path.set(str(value))
            self.save()
        elif kind == 'pcs_install_done':
            self.pcs_install_button.configure(state='normal')
        elif kind == 'lyric_file':
            path, status = value
            self.show_lyric_path(path, status)
        elif kind == 'lyric_metadata':
            track = value
            self.show_lyric_path(track.path, '正在匹配……')
            self.lyric_tree.set(self.lyric_paths[str(track.path.resolve())], 'artist', track.artist)
        elif kind == 'lyric_scan':
            for path in value:
                self.show_lyric_path(path, '已有歌词' if extras.sidecar_exists(path) else '待匹配')
        elif kind == 'lyric_candidates':
            callback, records = value
            callback(records)

    def choose_pcs(self):
        path = filedialog.askopenfilename(title='选择 BaiduPCS-Go.exe', filetypes=[('BaiduPCS-Go', '*.exe')])
        if path:
            self.pcs_path.set(path)
            self.save()

    def require_pcs(self):
        path = Path(self.pcs_path.get()).expanduser()
        if not path.is_file() or path.suffix.lower() != '.exe':
            self.notebook.select(self.extras_tab)
            messagebox.showinfo('首次设置百度工具', '请先点击“一键安装开源工具”，或选择已有的 BaiduPCS-Go.exe，然后完成登录。')
            return None
        if self.pcs_login is not None and self.pcs_login.poll() is None:
            messagebox.showinfo('账号终端运行中', '请先退出账号终端（输入 quit），再运行下载或账号检测。')
            return None
        return path.resolve()

    def install_pcs_tool(self):
        self.pcs_install_button.configure(state='disabled')
        self.extra_status.configure(text='正在从开源项目官方 Release 下载并校验工具……')
        def work():
            try:
                path, version = extras.install_pcs(self.extra_data / 'tools')
                self.emit('pcs_installed', path)
                self.emit('extra_message', f'工具 {version} 已安装并通过 SHA-256 校验，请打开账号终端完成登录。')
            finally:
                self.emit('pcs_install_done', None)
        self.extra_job(work)

    def login_pcs(self):
        if self.pcs_busy:
            messagebox.showinfo('网盘任务运行中', '先停止网盘任务并等待结束，再打开账号终端。')
            return
        path = self.require_pcs()
        if not path:
            return
        try:
            # A visible terminal is intentional: credentials are entered in the
            # upstream client itself, never in Shiyin settings or session logs.
            self.pcs_login = subprocess.Popen([str(path)], env=extras.pcs_env(self.extra_data / 'baidupcs'),
                                              creationflags=subprocess.CREATE_NEW_CONSOLE)
            self.extra_status.configure(text='已打开账号终端。按开源项目说明登录，完成后输入 quit 退出；再点击“检测登录”。')
        except OSError as error:
            messagebox.showerror('无法启动工具', str(error))

    def check_pcs(self):
        if self.pcs_busy:
            return
        path = self.require_pcs()
        if not path:
            return
        self.pcs_busy = True
        def work():
            try:
                extras.check_pcs_login(path, self.extra_data / 'baidupcs', self.extra_cancel)
                self.emit('extra_message', '百度账号检测通过，可以选择分享链接开始下载。')
            finally:
                self.emit('pcs_finished', None)
        self.extra_job(work)

    def start_baidu(self):
        if self.pcs_busy or self.closing:
            return
        items = [i.copy() for i in (self.selected() or list(self.items.values()))
                 if i['kind'] == '网盘' and extras.up.urlsplit(i['url']).hostname in ('pan.baidu.com', 'yun.baidu.com')]
        if not items:
            messagebox.showinfo('没有百度分享', '请先在“搜集与下载”中加入百度网盘分享链接。支持多选；未选中时下载全部百度分享。')
            return
        path = self.require_pcs()
        if not path:
            return
        try:
            folder = Path(self.folder.get()).expanduser().resolve()
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            messagebox.showerror('目录不可用', str(error))
            return
        self.save()
        self.pcs_busy = True
        self.pcs_download_button.configure(state='disabled')
        automatic = self.auto_lyrics_enabled.get()
        def work():
            try:
                for item in items:
                    if self.extra_cancel.is_set():
                        break
                    url = item['url']
                    update = lambda text: self.emit('status', (url, text))
                    update('百度：检测账号 / 转存')
                    try:
                        local = extras.download_baidu(path, item, folder, self.extra_data / 'baidupcs', self.extra_cancel, update)
                        update('百度下载完成')
                        if automatic:
                            for audio in extras.audio_files(local):
                                if self.extra_cancel.is_set():
                                    break
                                self.match_lyrics_file(audio, self.extra_cancel)
                    except extras.Cancelled:
                        update('百度已停止（可重试续传）')
                        break
                    except Exception as error:
                        update('百度失败：' + str(error)[:90])
                        self.emit('extra_message', str(error)[:180])
                self.emit('extra_message', '百度下载队列已结束。歌词只处理已下载的音频；压缩包可解压后扫描目录。')
            finally:
                self.emit('pcs_finished', None)
        self.extra_job(work)

    def show_lyric_path(self, path, status='待匹配'):
        path = Path(path).resolve()
        key = str(path)
        if key not in self.lyric_paths:
            # Tag parsing happens in workers, not on the Tk event thread.
            self.lyric_paths[key] = self.lyric_tree.insert('', 'end', values=(path.name, '', status))
        else:
            self.lyric_tree.set(self.lyric_paths[key], 'status', status)

    def add_lyric_files(self):
        paths = filedialog.askopenfilenames(title='选择已有音频', filetypes=[('音频', ' '.join('*' + e for e in sorted(extras.AUDIO_EXTS))), ('所有文件', '*.*')])
        for path in paths:
            if Path(path).suffix.lower() in extras.AUDIO_EXTS:
                self.show_lyric_path(path, '已有歌词' if extras.sidecar_exists(path) else '待匹配')

    def scan_lyrics(self):
        folder = Path(self.folder.get()).expanduser()
        if not folder.is_dir():
            messagebox.showinfo('目录不存在', '请先在搜集页设置已有音频所在的下载目录。')
            return
        def work():
            batch, total = [], 0
            for path in extras.audio_files(folder):
                if self.extra_cancel.is_set():
                    break
                batch.append(path)
                total += 1
                if len(batch) == 100:
                    self.emit('lyric_scan', batch)
                    batch = []
            self.emit('lyric_scan', batch)
            self.emit('extra_message', f'扫描结束：发现 {total} 个音频文件。可多选补歌词，也可全部处理。')
        self.extra_job(work)

    def match_lyrics_file(self, path, cancel):
        try:
            self.emit('lyric_metadata', extras.read_track(path))
            status = extras.auto_lyrics(path, cancel)
        except Exception as error:
            status = '歌词未完成：' + str(error)[:80]
        self.emit('lyric_file', (path, status))
        return status

    def start_lyrics_batch(self):
        if self.lyrics_busy or self.closing:
            return
        selection = set(self.lyric_tree.selection())
        paths = [Path(path) for path, row in self.lyric_paths.items() if not selection or row in selection]
        if not paths:
            messagebox.showinfo('没有音频', '先添加音频文件，或扫描下载目录。')
            return
        self.lyrics_busy = True
        self.lyrics_button.configure(state='disabled')
        def work():
            count = 0
            try:
                for path in paths:
                    if self.extra_cancel.is_set():
                        break
                    self.emit('lyric_file', (path, '正在匹配……'))
                    self.match_lyrics_file(path, self.extra_cancel)
                    count += 1
                    self.extra_cancel.wait(0.25)
                self.emit('extra_message', f'歌词队列结束：已处理 {count}/{len(paths)} 首。未可靠匹配的可用“手动匹配所选”。')
            finally:
                self.emit('lyrics_finished', None)
        self.extra_job(work)

    def clear_lyric_list(self):
        if self.lyrics_busy:
            return
        self.lyric_tree.delete(*self.lyric_tree.get_children())
        self.lyric_paths.clear()

    def manual_lyrics(self):
        selected = set(self.lyric_tree.selection())
        path = next((Path(path) for path, row in self.lyric_paths.items() if row in selected), None)
        if path is None:
            messagebox.showinfo('选择一首歌', '请先在歌词列表中选择一首音频。')
            return
        track = extras.read_track(path)
        dialog = tk.Toplevel(self.root)
        dialog.title('手动匹配歌词 · ' + path.name)
        dialog.geometry('860x650')
        dialog.configure(bg='#f5f1e9')
        top = ttk.Frame(dialog, padding=14)
        top.pack(fill='both', expand=True)
        fields = ttk.Frame(top)
        fields.pack(fill='x')
        title, artist = tk.StringVar(value=track.title), tk.StringVar(value=track.artist)
        for label, variable in [('歌名', title), ('歌手', artist)]:
            ttk.Label(fields, text=label).pack(side='left')
            ttk.Entry(fields, textvariable=variable, width=22).pack(side='left', padx=8)
        records = []
        table = ttk.Treeview(top, columns=('title', 'artist', 'album', 'duration', 'type'), show='headings', height=5)
        for key, label, width in [('title', '歌名', 180), ('artist', '歌手', 140), ('album', '专辑', 220), ('duration', '秒', 65), ('type', '歌词', 90)]:
            table.heading(key, text=label)
            table.column(key, width=width)
        table.pack(fill='x', pady=12)
        preview = tk.Text(top, wrap='word', font=('Microsoft YaHei UI', 10), state='disabled')
        preview.pack(fill='both', expand=True)
        def show():
            choice = table.selection()
            if not choice:
                return
            record = records[int(choice[0])]
            preview.configure(state='normal')
            preview.delete('1.0', 'end')
            preview.insert('1.0', record.get('syncedLyrics') or record.get('plainLyrics') or '纯音乐，无歌词')
            preview.configure(state='disabled')
        table.bind('<<TreeviewSelect>>', lambda _: show())
        def receive(found):
            if not dialog.winfo_exists():
                return
            search_button.configure(state='normal')
            records[:] = found
            table.delete(*table.get_children())
            for index, record in enumerate(found):
                table.insert('', 'end', iid=str(index), values=(record['trackName'], record.get('artistName', ''), record.get('albumName', ''), record.get('duration', ''), 'LRC' if record.get('syncedLyrics') else '纯音乐' if record.get('instrumental') else 'TXT'))
            note.configure(text=f'找到 {len(found)} 个版本，请核对专辑、时长和预览后保存。')
        def search():
            query = replace(track, title=title.get().strip(), artist=artist.get().strip())
            search_button.configure(state='disabled')
            def work():
                try:
                    found = extras.search_lyrics(query)
                except Exception as error:
                    self.emit('extra_message', '歌词搜索失败：' + str(error)[:100])
                    found = []
                self.emit('lyric_candidates', (receive, found))
            self.extra_job(work)
        def save():
            choice = table.selection()
            if choice:
                try:
                    status = extras.save_lyrics(track, records[int(choice[0])])
                    self.show_lyric_path(path, status)
                    note.configure(text=status)
                except OSError as error:
                    note.configure(text=str(error))
        actions = ttk.Frame(top)
        actions.pack(fill='x', pady=10)
        search_button = self.extra_button(fields, text='搜索歌词', command=search)
        search_button.pack(side='left')
        note = ttk.Label(actions, text='歌词来源 LRCLIB；保存同名文件，已有歌词不会覆盖。')
        note.pack(side='left')
        self.extra_button(actions, text='保存所选歌词', style='Accent.TButton', command=save).pack(side='right')
