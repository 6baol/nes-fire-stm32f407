#!/usr/bin/env python3
"""NesFire 导入助手 — 图形化管理 SD 卡上的 ROM、封面与目录。

普通用户不需要记命令行：

  1. 选择 ROM 来源文件夹和 SD 卡上的 NES 文件夹；
  2. 点“扫描”，表格会标出 Hack/汉化、缺封面、重复；
  3. 选中要导入的游戏，点“导入选中”；
  4. 封面页可以把一张图片做成 .COV；不生成也没关系，游戏机第一次
     启动该 ROM 时会自动截取开始画面作为默认海报；
  5. 维护页可以安全去重（Hack/汉化受保护）、按英文名排序、重建目录。

直接运行: python tools/nes_import_gui.py
Windows 双击: tools/NesImportGUI.bat
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import traceback
import webbrowser
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

ROM_SUFFIXES = {'.nes', '.fds'}
HACK_TAGS = {
    'hack', 'kaizo', 'kaoshi', 'translation', 'pirate', 'bootleg', 'unl',
    'proto', 'beta', 'demo', 'homebrew', 'patch', 'trainer', 'sample',
}
TRANSLATION_RE = re.compile(
    r't[+-]?(eng|chi|chinese|jpn|japanese|rus|ger|fre|spa|ita|kor|por|dut|swe)$',
    re.IGNORECASE)
HACK_BRACKET_RE = re.compile(r'\[h\d*\]|\[h[ab]\]', re.IGNORECASE)
TAG_RE = re.compile(r'\(([^)]*)\)|\[([^\]]*)\]')
STATE_FILE = Path.home() / '.nesfire_import.json'

try:
    from PIL import Image, ImageTk
    HAVE_PIL = True
except Exception:
    Image = ImageTk = None
    HAVE_PIL = False

try:
    from cover_codec import decode_cover, encode_cover_image
    HAVE_COVER_CODEC = HAVE_PIL
except Exception:
    HAVE_COVER_CODEC = False

try:
    import dedup_sd
    import make_pinyin
    import sort_catalog
    HAVE_MAINTENANCE = True
except Exception:
    dedup_sd = make_pinyin = sort_catalog = None
    HAVE_MAINTENANCE = False


# --------------------------------------------------------------------------- #
# ROM 命名解析
# --------------------------------------------------------------------------- #
def english_title(path: Path) -> str:
    stem = path.stem
    match = re.match(r'^\[[^\]]*\]\[[^\]]*\](.*)$', stem)
    rest = match.group(1) if match else stem
    return re.split(r'\s*[\(\[]', rest, maxsplit=1)[0].strip()


def normalized(title: str) -> str:
    return re.sub(r'[^0-9a-z]+', '', title.lower())


def tags_of(path: Path) -> list[str]:
    return [(m[0] or m[1]).strip() for m in TAG_RE.findall(path.stem) if (m[0] or m[1]).strip()]


def is_hack(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    if 'hacks' in parts or 'hack' in parts:
        return True
    if HACK_BRACKET_RE.search(path.stem):
        return True
    for tag in tags_of(path):
        low = tag.lower()
        if low in HACK_TAGS or TRANSLATION_RE.match(low):
            return True
        if low.startswith(('hack', 'kaizo', 'translat')):
            return True
    return False


def region_of(path: Path) -> str:
    tags = [t for t in tags_of(path) if t]
    known = [t for t in tags if t in
             ('World', 'USA', 'Japan', 'Europe', 'Japan, USA', 'USA, Japan',
              'Australia', 'China', 'Korea', 'Brazil', 'Germany', 'France',
              'Spain', 'Italy', 'Sweden', 'Canada')]
    return ', '.join(known) if known else ''


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def cover_for(rom: Path) -> Path | None:
    for suffix in ('.COV', '.cov'):
        candidate = rom.with_suffix(suffix)
        if candidate.is_file():
            return candidate
    return None


def human_size(size: int) -> str:
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024 or unit == 'GB':
            return f'{size:.0f} {unit}' if unit == 'B' else f'{size:.1f} {unit}'
        size /= 1024.0
    return f'{size:.1f} GB'


@dataclass
class RomEntry:
    path: Path
    rel: str
    title: str
    region: str
    tags: list[str]
    hack: bool
    cover: Path | None
    size: int
    sha: str = ''
    duplicate: str = ''


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def detect_nes_roots() -> list[Path]:
    """Find X:/NES folders on mounted drives."""
    found = []
    for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
        drive = Path(f'{letter}:/')
        try:
            if not drive.exists():
                continue
        except OSError:
            continue
        candidate = drive / 'NES'
        try:
            if candidate.is_dir():
                found.append(candidate)
        except OSError:
            pass
    return found


def unique_destination(folder: Path, name: str, source_hash: str | None = None) -> Path | None:
    """Return a free target path, or None when the same file already exists."""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    if not target.exists():
        return target
    if source_hash and target.is_file():
        try:
            if target.stat().st_size and sha256_file(target) == source_hash:
                return None
        except OSError:
            pass
    stem, suffix = target.stem, target.suffix
    for index in range(2, 1000):
        candidate = folder / f'{stem} ({index}){suffix}'
        if not candidate.exists():
            return candidate
    raise RuntimeError(f'无法为 {name} 找到可用文件名')


def read_cover_image(path: Path):
    """Decode an NCV1 .COV into a PIL image."""
    width, height, bits, values = decode_cover(path.read_bytes())
    image = Image.new('RGB', (width, height))
    pixels = []
    for value in values:
        pixels.append((((value >> 11) & 0x1F) << 3,
                       ((value >> 5) & 0x3F) << 2,
                       (value & 0x1F) << 3))
    image.putdata(pixels)
    return image


# --------------------------------------------------------------------------- #
# 主窗口
# --------------------------------------------------------------------------- #
class ImportAssistant(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('NesFire 导入助手')
        self.geometry('1120x760')
        self.minsize(940, 640)
        self.configure(bg='#101216')

        self.rows: list[RomEntry] = []
        self.row_by_iid: dict[str, RomEntry] = {}
        self.cover_rows: list[RomEntry] = []
        self.cover_by_iid: dict[str, RomEntry] = {}
        self._preview_photo = None
        self._busy = False
        self._sort_desc: dict[str, bool] = {}

        self.source_var = tk.StringVar()
        self.nes_var = tk.StringVar()
        self.filter_var = tk.StringVar(value='全部')
        self.search_var = tk.StringVar()
        self.status_var = tk.StringVar(value='就绪')
        self.keep_tree_var = tk.BooleanVar(value=False)
        self.copy_covers_var = tk.BooleanVar(value=True)
        self.dedup_dir_var = tk.StringVar()

        self._load_state()
        self._build_style()
        self._build_ui()
        self._autodetect()
        self.protocol('WM_DELETE_WINDOW', self._on_close)

    # ---------------------------------------------------------------- style
    def _build_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass
        style.configure('.', background='#101216', foreground='#e6e9ef')
        style.configure('TFrame', background='#101216')
        style.configure('TLabel', background='#101216', foreground='#e6e9ef')
        style.configure('Muted.TLabel', foreground='#8a93a5')
        style.configure('Title.TLabel', font=('Segoe UI', 16, 'bold'))
        style.configure('TButton', padding=(10, 5))
        style.configure('Accent.TButton', background='#2f81f7', foreground='#ffffff')
        style.map('Accent.TButton', background=[('active', '#4a95ff')])
        style.configure('TNotebook', background='#101216', borderwidth=0)
        style.configure('TNotebook.Tab', padding=(16, 8))
        style.configure('Treeview', background='#171a21', fieldbackground='#171a21',
                        foreground='#e6e9ef', rowheight=24, borderwidth=0)
        style.configure('Treeview.Heading', background='#232833', foreground='#c8cfdb')
        style.map('Treeview', background=[('selected', '#2f81f7')])
        style.configure('TEntry', fieldbackground='#171a21', foreground='#e6e9ef')
        style.configure('TCombobox', fieldbackground='#171a21', foreground='#e6e9ef')

    # ------------------------------------------------------------------ ui
    def _build_ui(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill='both', expand=True)

        header = ttk.Frame(root)
        header.pack(fill='x', pady=(0, 10))
        ttk.Label(header, text='NesFire 导入助手', style='Title.TLabel').pack(side='left')
        ttk.Label(header, text='外部 ROM / Hack 导入 · 封面 · 目录维护',
                  style='Muted.TLabel').pack(side='left', padx=12)
        ttk.Label(header, textvariable=self.status_var,
                  style='Muted.TLabel').pack(side='right')

        paned = ttk.PanedWindow(root, orient='vertical')
        paned.pack(fill='both', expand=True)

        self.notebook = ttk.Notebook(paned)
        paned.add(self.notebook, weight=4)

        self.import_tab = ttk.Frame(self.notebook, padding=10)
        self.cover_tab = ttk.Frame(self.notebook, padding=10)
        self.maintain_tab = ttk.Frame(self.notebook, padding=10)
        self.help_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.import_tab, text='导入 ROM')
        self.notebook.add(self.cover_tab, text='封面')
        self.notebook.add(self.maintain_tab, text='维护')
        self.notebook.add(self.help_tab, text='说明')

        self._build_import_tab()
        self._build_cover_tab()
        self._build_maintain_tab()
        self._build_help_tab()

        log_frame = ttk.Frame(paned, padding=(0, 6, 0, 0))
        paned.add(log_frame, weight=1)
        ttk.Label(log_frame, text='日志', style='Muted.TLabel').pack(anchor='w')
        log_body = ttk.Frame(log_frame)
        log_body.pack(fill='both', expand=True, pady=(4, 0))
        self.log_text = tk.Text(log_body, height=8, bg='#0b0d11', fg='#c8cfdb',
                                insertbackground='#c8cfdb', relief='flat',
                                font=('Consolas', 9), wrap='word')
        scroll = ttk.Scrollbar(log_body, orient='vertical', command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.log_text.configure(state='disabled')

    def _path_picker(self, parent, label, variable, row):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky='w', padx=(0, 8), pady=4)
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=1, sticky='ew', pady=4)
        ttk.Button(parent, text='浏览…', command=lambda: self._pick_folder(variable)).grid(
            row=row, column=2, padx=(8, 0), pady=4)
        ttk.Button(parent, text='打开', command=lambda: self._open_folder(variable.get())).grid(
            row=row, column=3, padx=(6, 0), pady=4)

    def _build_import_tab(self):
        tab = self.import_tab
        tab.columnconfigure(1, weight=1)
        self._path_picker(tab, 'ROM 来源', self.source_var, 0)
        self._path_picker(tab, 'SD 卡 NES 目录', self.nes_var, 1)

        options = ttk.Frame(tab)
        options.grid(row=2, column=0, columnspan=4, sticky='ew', pady=(6, 8))
        ttk.Checkbutton(options, text='保留来源子目录', variable=self.keep_tree_var).pack(side='left')
        ttk.Checkbutton(options, text='同时导入同名 .COV', variable=self.copy_covers_var).pack(
            side='left', padx=16)

        ttk.Label(options, text='筛选').pack(side='left', padx=(24, 6))
        combo = ttk.Combobox(options, textvariable=self.filter_var, width=12, state='readonly',
                             values=['全部', '仅 Hack/汉化', '非 Hack', '缺封面', '重复'])
        combo.pack(side='left')
        combo.bind('<<ComboboxSelected>>', lambda _e: self._refresh_table())
        ttk.Label(options, text='搜索').pack(side='left', padx=(16, 6))
        search = ttk.Entry(options, textvariable=self.search_var, width=18)
        search.pack(side='left')
        search.bind('<KeyRelease>', lambda _e: self._refresh_table())

        actions = ttk.Frame(tab)
        actions.grid(row=3, column=0, columnspan=4, sticky='ew', pady=(0, 8))
        ttk.Button(actions, text='扫描', command=self.scan_source).pack(side='left')
        ttk.Button(actions, text='全选', command=lambda: self._select_all(True)).pack(
            side='left', padx=6)
        ttk.Button(actions, text='清空', command=lambda: self._select_all(False)).pack(side='left')
        ttk.Button(actions, text='导入选中', style='Accent.TButton',
                   command=self.import_selected).pack(side='left', padx=(18, 6))
        ttk.Button(actions, text='让游戏机重建目录',
                   command=lambda: self.rebuild_catalog(confirm=True)).pack(side='right')
        self.import_progress = ttk.Progressbar(actions, mode='determinate', length=200)
        self.import_progress.pack(side='right', padx=10)

        columns = ('name', 'title', 'region', 'tags', 'hack', 'cover', 'dup', 'size')
        headings = {'name': '文件', 'title': '英文标题', 'region': '区域', 'tags': '标记',
                    'hack': '改版', 'cover': '封面', 'dup': '重复', 'size': '大小'}
        widths = {'name': 300, 'title': 240, 'region': 90, 'tags': 150,
                  'hack': 55, 'cover': 55, 'dup': 90, 'size': 75}
        self.tree = ttk.Treeview(tab, columns=columns, show='headings', selectmode='extended')
        for column in columns:
            self.tree.heading(column, text=headings[column],
                              command=lambda c=column: self._sort_table(c))
            self.tree.column(column, width=widths[column],
                             anchor='w' if column in ('name', 'title', 'tags') else 'center')
        self.tree.tag_configure('hack', foreground='#ffb86b')
        self.tree.tag_configure('dup', background='#2a2418')
        self.tree.tag_configure('missing', foreground='#8a93a5')
        self.tree.grid(row=4, column=0, columnspan=4, sticky='nsew')
        tab.rowconfigure(4, weight=1)
        scroll_y = ttk.Scrollbar(tab, orient='vertical', command=self.tree.yview)
        scroll_y.grid(row=4, column=4, sticky='ns')
        self.tree.configure(yscrollcommand=scroll_y.set)
        self.tree.bind('<<TreeviewSelect>>', lambda _e: self._update_selection_status())

    def _build_cover_tab(self):
        tab = self.cover_tab
        tab.columnconfigure(0, weight=3)
        tab.columnconfigure(1, weight=2)
        tab.rowconfigure(2, weight=1)

        bar = ttk.Frame(tab)
        bar.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 8))
        ttk.Button(bar, text='刷新列表', command=self.refresh_covers).pack(side='left')
        ttk.Button(bar, text='用图片生成封面…', style='Accent.TButton',
                   command=self.cover_from_image).pack(side='left', padx=6)
        ttk.Button(bar, text='删除封面（首玩自动截取）',
                   command=self.cover_delete).pack(side='left')
        ttk.Button(bar, text='打开封面文件夹',
                   command=self._open_current_cover_folder).pack(side='left', padx=6)

        ttk.Label(tab, text='游戏机第一次启动没有 .COV 的 ROM 时，会自动截取开始画面并写回封面。',
                  style='Muted.TLabel').grid(row=1, column=0, columnspan=2, sticky='w',
                                             pady=(0, 6))

        self.cover_tree = ttk.Treeview(tab, columns=('name', 'cover', 'size'),
                                       show='headings', selectmode='browse')
        for column, text, width in (('name', '文件', 330), ('cover', '封面', 80),
                                    ('size', '大小', 80)):
            self.cover_tree.heading(column, text=text)
            self.cover_tree.column(column, width=width,
                                   anchor='w' if column == 'name' else 'center')
        self.cover_tree.grid(row=2, column=0, sticky='nsew')
        self.cover_tree.tag_configure('missing', foreground='#ffb86b')
        self.cover_tree.bind('<<TreeviewSelect>>', lambda _e: self._show_cover_preview())

        preview = ttk.Frame(tab, padding=(12, 0, 0, 0))
        preview.grid(row=2, column=1, sticky='nsew')
        ttk.Label(preview, text='预览', style='Muted.TLabel').pack(anchor='w')
        self.preview_label = tk.Label(preview, bg='#0b0d11', fg='#8a93a5',
                                      text='选择左侧游戏查看封面', width=34, height=16)
        self.preview_label.pack(fill='both', expand=True, pady=6)
        self.cover_info = ttk.Label(preview, text='', style='Muted.TLabel', wraplength=320)
        self.cover_info.pack(anchor='w')

    def _build_maintain_tab(self):
        tab = self.maintain_tab
        tab.columnconfigure(1, weight=1)

        ttk.Label(tab, text='安全去重', font=('Segoe UI', 11, 'bold')).grid(
            row=0, column=0, columnspan=4, sticky='w', pady=(0, 2))
        ttk.Label(tab, text='同英文标题只保留一个版本；Hack、汉化、Beta、Proto、Bootleg 永远不参与。',
                  style='Muted.TLabel').grid(row=1, column=0, columnspan=4, sticky='w',
                                             pady=(0, 6))
        self._path_picker(tab, '去重目录', self.dedup_dir_var, 2)
        row = ttk.Frame(tab)
        row.grid(row=3, column=0, columnspan=4, sticky='w', pady=(4, 14))
        ttk.Button(row, text='检查重复（只读）',
                   command=lambda: self.run_dedup(apply=False)).pack(side='left')
        ttk.Button(row, text='执行去重…', command=lambda: self.run_dedup(apply=True)).pack(
            side='left', padx=8)

        ttk.Separator(tab).grid(row=4, column=0, columnspan=4, sticky='ew', pady=6)

        ttk.Label(tab, text='目录与索引', font=('Segoe UI', 11, 'bold')).grid(
            row=5, column=0, columnspan=4, sticky='w', pady=(4, 2))
        ttk.Label(tab, text='目录由游戏机开机时重建；重建后可以用“按英文名排序”调整顺序。',
                  style='Muted.TLabel').grid(row=6, column=0, columnspan=4, sticky='w',
                                             pady=(0, 6))
        grid = ttk.Frame(tab)
        grid.grid(row=7, column=0, columnspan=4, sticky='w', pady=4)
        ttk.Button(grid, text='重建目录', command=lambda: self.rebuild_catalog(confirm=True)).pack(
            side='left')
        ttk.Button(grid, text='按英文名排序（预演）',
                   command=lambda: self.run_sort(apply=False)).pack(side='left', padx=8)
        ttk.Button(grid, text='应用排序', command=lambda: self.run_sort(apply=True)).pack(
            side='left')
        ttk.Button(grid, text='填充拼音索引', command=self.run_pinyin).pack(side='left', padx=8)

        ttk.Label(tab, text='提示：排序会保留每条记录的拼音字段；重建目录后需要重新排序。',
                  style='Muted.TLabel').grid(row=8, column=0, columnspan=4, sticky='w',
                                             pady=(10, 0))

        ttk.Separator(tab).grid(row=9, column=0, columnspan=4, sticky='ew', pady=10)
        ttk.Label(tab, text='FDS BIOS', font=('Segoe UI', 11, 'bold')).grid(
            row=10, column=0, columnspan=4, sticky='w', pady=(2, 2))
        ttk.Label(tab,
                  text='FDS 游戏需要 8 KiB 的 disksys.rom。卡上的 NES/DISKSYS.ROM 优先于固件内置 BIOS。',
                  style='Muted.TLabel').grid(row=11, column=0, columnspan=4, sticky='w')
        bios_row = ttk.Frame(tab)
        bios_row.grid(row=12, column=0, columnspan=4, sticky='w', pady=(6, 0))
        ttk.Button(bios_row, text='一键导入 disksys.rom…', style='Accent.TButton',
                   command=self.import_fds_bios).pack(side='left')
        ttk.Button(bios_row, text='刷新状态', command=self.refresh_bios_status).pack(
            side='left', padx=8)
        ttk.Button(bios_row, text='获取开源 BIOS', command=self.open_bios_page).pack(side='left')
        self.bios_status = ttk.Label(tab, text='', style='Muted.TLabel')
        self.bios_status.grid(row=13, column=0, columnspan=4, sticky='w', pady=(6, 0))

    def _build_help_tab(self):
        text = tk.Text(self.help_tab, bg='#0b0d11', fg='#c8cfdb', relief='flat',
                       wrap='word', font=('Segoe UI', 10), padx=14, pady=12)
        text.pack(fill='both', expand=True)
        text.insert('1.0', HELP_TEXT)
        text.configure(state='disabled')

    # -------------------------------------------------------------- helpers
    def log(self, message: str):
        self.after(0, lambda: self._append_log(message))

    def _append_log(self, message: str):
        self.log_text.configure(state='normal')
        self.log_text.insert('end', message.rstrip() + '\n')
        self.log_text.see('end')
        self.log_text.configure(state='disabled')

    def set_status(self, message: str):
        self.after(0, lambda: self.status_var.set(message))

    def _pick_folder(self, variable: tk.StringVar):
        initial = variable.get() or str(Path.home())
        chosen = filedialog.askdirectory(initialdir=initial)
        if chosen:
            variable.set(chosen)

    def _open_folder(self, path: str):
        if not path or not Path(path).is_dir():
            messagebox.showwarning('文件夹不存在', '请先选择一个存在的文件夹。')
            return
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except AttributeError:
            subprocess.Popen(['xdg-open', path])
        except OSError as error:
            messagebox.showerror('无法打开', str(error))

    def _open_current_cover_folder(self):
        entry = self._selected_cover()
        if entry is None:
            messagebox.showinfo('未选择', '请先在列表里选择一个游戏。')
            return
        self._open_folder(str(entry.path.parent))

    def _on_close(self):
        try:
            self._save_state()
        finally:
            self.destroy()

    def _load_state(self):
        try:
            data = json.loads(STATE_FILE.read_text('utf-8'))
        except Exception:
            return
        self.source_var.set(data.get('source', ''))
        self.nes_var.set(data.get('nes', ''))
        self.dedup_dir_var.set(data.get('dedup', ''))

    def _save_state(self):
        try:
            STATE_FILE.write_text(json.dumps({
                'source': self.source_var.get(),
                'nes': self.nes_var.get(),
                'dedup': self.dedup_dir_var.get(),
            }, ensure_ascii=False, indent=2), 'utf-8')
        except Exception:
            pass

    def _autodetect(self):
        if not self.nes_var.get():
            roots = detect_nes_roots()
            if roots:
                self.nes_var.set(str(roots[0]))
                self.log(f'已自动找到 SD 卡目录: {roots[0]}')
        self._sync_dedup_default()
        self.nes_var.trace_add('write', lambda *_: self._sync_dedup_default())

    def _sync_dedup_default(self):
        nes = Path(self.nes_var.get()) if self.nes_var.get() else None
        if not nes or not nes.exists():
            return
        famicom = nes / 'famicom'
        self.dedup_dir_var.set(str(famicom if famicom.is_dir() else nes))
        if hasattr(self, 'bios_status'):
            self.refresh_bios_status()

    # ---------------------------------------------------------------- scan
    def scan_source(self):
        if self._busy:
            return
        folder = Path(self.source_var.get())
        if not folder.is_dir():
            messagebox.showwarning('来源无效', '请选择包含 .nes/.fds 的文件夹。')
            return
        self._busy = True
        self.set_status('扫描中…')
        self.log(f'扫描 {folder} …')
        self.import_progress.configure(mode='indeterminate')
        self.import_progress.start(12)

        def work():
            try:
                entries = self._scan_folder(folder)
                self.after(0, lambda: self._populate(entries))
                self.log(f'扫描完成：{len(entries)} 个 ROM，'
                         f'{sum(1 for e in entries if e.hack)} 个 Hack/汉化，'
                         f'{sum(1 for e in entries if e.duplicate)} 个重复。')
                self.set_status(f'{len(entries)} 个 ROM')
            except Exception:
                self.log(traceback.format_exc())
                self.set_status('扫描失败')
            finally:
                self.after(0, self._scan_finished)

        threading.Thread(target=work, daemon=True).start()

    def _scan_finished(self):
        self.import_progress.stop()
        self.import_progress.configure(mode='determinate', value=0)
        self._busy = False

    def _scan_folder(self, folder: Path, hash_duplicates: bool = True) -> list[RomEntry]:
        files = sorted((p for p in folder.rglob('*')
                        if p.is_file() and p.suffix.lower() in ROM_SUFFIXES),
                       key=lambda p: str(p).lower())
        entries = []
        for path in files:
            try:
                size = path.stat().st_size
            except OSError:
                continue
            entries.append(RomEntry(
                path=path,
                rel=str(path.relative_to(folder)),
                title=english_title(path),
                region=region_of(path),
                tags=tags_of(path),
                hack=is_hack(path),
                cover=cover_for(path),
                size=size,
            ))

        if hash_duplicates:
            # Hash only same-size candidates: much cheaper on a 1500-ROM set.
            by_size: dict[int, list[RomEntry]] = {}
            for entry in entries:
                by_size.setdefault(entry.size, []).append(entry)
            for group in by_size.values():
                if len(group) < 2:
                    continue
                for entry in group:
                    try:
                        entry.sha = sha256_file(entry.path)
                    except OSError:
                        pass

        hash_counts = Counter(e.sha for e in entries if e.sha)
        title_counts = Counter(normalized(e.title) for e in entries if not e.hack)
        for entry in entries:
            if entry.sha and hash_counts[entry.sha] > 1:
                entry.duplicate = '完全相同'
            elif not entry.hack and title_counts[normalized(entry.title)] > 1:
                entry.duplicate = '同名'
        return entries

    def _populate(self, entries: list[RomEntry]):
        self.rows = entries
        self._refresh_table()

    def _visible_rows(self) -> list[RomEntry]:
        query = self.search_var.get().strip().lower()
        mode = self.filter_var.get()
        rows = self.rows
        if mode == '仅 Hack/汉化':
            rows = [e for e in rows if e.hack]
        elif mode == '非 Hack':
            rows = [e for e in rows if not e.hack]
        elif mode == '缺封面':
            rows = [e for e in rows if not e.cover]
        elif mode == '重复':
            rows = [e for e in rows if e.duplicate]
        if query:
            rows = [e for e in rows if query in e.rel.lower() or query in e.title.lower()]
        return rows

    def _refresh_table(self):
        self.tree.delete(*self.tree.get_children())
        self.row_by_iid.clear()
        for index, entry in enumerate(self._visible_rows()):
            iid = str(index)
            tags = []
            if entry.hack:
                tags.append('hack')
            if entry.duplicate:
                tags.append('dup')
            if not entry.cover:
                tags.append('missing')
            self.tree.insert('', 'end', iid=iid, tags=tags, values=(
                entry.rel, entry.title, entry.region, ', '.join(entry.tags),
                '是' if entry.hack else '', '有' if entry.cover else '缺',
                entry.duplicate, human_size(entry.size)))
            self.row_by_iid[iid] = entry
        self.set_status(f'显示 {len(self.row_by_iid)} / {len(self.rows)} 个 ROM')

    def _sort_table(self, column: str):
        entries = list(self.row_by_iid.values())
        if not entries:
            return
        key_map = {
            'name': lambda e: e.rel.lower(),
            'title': lambda e: e.title.lower(),
            'region': lambda e: e.region.lower(),
            'tags': lambda e: ','.join(e.tags).lower(),
            'hack': lambda e: e.hack,
            'cover': lambda e: bool(e.cover),
            'dup': lambda e: e.duplicate,
            'size': lambda e: e.size,
        }
        reverse = self._sort_desc.get(column, False)
        entries.sort(key=key_map[column], reverse=reverse)
        self._sort_desc[column] = not reverse
        self.tree.delete(*self.tree.get_children())
        self.row_by_iid.clear()
        for index, entry in enumerate(entries):
            iid = str(index)
            tags = []
            if entry.hack:
                tags.append('hack')
            if entry.duplicate:
                tags.append('dup')
            if not entry.cover:
                tags.append('missing')
            self.tree.insert('', 'end', iid=iid, tags=tags, values=(
                entry.rel, entry.title, entry.region, ', '.join(entry.tags),
                '是' if entry.hack else '', '有' if entry.cover else '缺',
                entry.duplicate, human_size(entry.size)))
            self.row_by_iid[iid] = entry

    def _select_all(self, state: bool):
        if state:
            self.tree.selection_set(self.tree.get_children())
        else:
            self.tree.selection_remove(self.tree.get_children())

    def _update_selection_status(self):
        selected = self.tree.selection()
        if not selected:
            self.set_status(f'{len(self.row_by_iid)} 个 ROM')
            return
        self.set_status(f'已选 {len(selected)} 个')

    # -------------------------------------------------------------- import
    def import_selected(self):
        if self._busy:
            return
        entries = [self.row_by_iid[iid] for iid in self.tree.selection() if iid in self.row_by_iid]
        if not entries:
            messagebox.showinfo('未选择', '请先在列表里选中要导入的游戏（可按住 Ctrl/Shift 多选）。')
            return
        nes_text = self.nes_var.get().strip()
        if not nes_text or not Path(nes_text).is_dir():
            messagebox.showwarning('目标无效', '请选择 SD 卡上的 NES 文件夹。')
            return
        nes = Path(nes_text)
        self._busy = True
        self.import_progress.configure(mode='determinate', maximum=len(entries), value=0)
        self.log(f'开始导入 {len(entries)} 个 ROM 到 {nes} …')

        def work():
            copied = skipped = failed = 0
            for index, entry in enumerate(entries, 1):
                try:
                    relative_parent = Path(entry.rel).parent
                    if entry.hack:
                        folder = nes / 'hacks'
                        if self.keep_tree_var.get() and str(relative_parent) != '.':
                            folder = folder / relative_parent
                    else:
                        folder = nes / 'imports'
                        if self.keep_tree_var.get() and str(relative_parent) != '.':
                            folder = folder / relative_parent
                    destination = unique_destination(
                        folder, entry.path.name,
                        entry.sha or sha256_file(entry.path))
                    if destination is None:
                        skipped += 1
                        self.log(f'  跳过（已存在）: {entry.rel}')
                    else:
                        shutil.copy2(entry.path, destination)
                        copied += 1
                        self.log(f'  {entry.rel} -> {destination.relative_to(nes)}')
                        if self.copy_covers_var.get() and entry.cover:
                            cover_destination = destination.with_suffix('.COV')
                            if not cover_destination.exists():
                                shutil.copy2(entry.cover, cover_destination)
                except Exception as error:
                    failed += 1
                    self.log(f'  失败 {entry.rel}: {error}')
                self.after(0, lambda v=index: self.import_progress.configure(value=v))

            self.log(f'导入完成：复制 {copied}，跳过 {skipped}，失败 {failed}。')
            self.set_status(f'导入完成：{copied} 个')
            self.after(0, lambda: self._import_finished(copied))

        threading.Thread(target=work, daemon=True).start()

    def _import_finished(self, copied: int):
        self._busy = False
        self.import_progress.configure(value=0)
        if copied and messagebox.askyesno(
                '导入完成',
                f'已复制 {copied} 个 ROM。\n\n'
                '现在让游戏机重建目录吗？\n'
                '（把 CATALOG.* 改名为 .OLD，下次开机自动重新扫描）'):
            self.rebuild_catalog(confirm=False)
        if self.notebook.index(self.notebook.select()) == 1:
            self.refresh_covers()

    # --------------------------------------------------------------- covers
    def refresh_covers(self):
        nes_text = self.nes_var.get().strip()
        if not nes_text or not Path(nes_text).is_dir():
            messagebox.showwarning('目标无效', '请先选择 SD 卡上的 NES 文件夹。')
            return
        self.set_status('读取封面列表…')

        def work():
            nes = Path(nes_text)
            entries = self._scan_folder(nes, hash_duplicates=False)
            entries.sort(key=lambda e: (bool(e.cover), str(e.rel).lower()))
            self.after(0, lambda: self._populate_covers(entries))

        threading.Thread(target=work, daemon=True).start()

    def _populate_covers(self, entries: list[RomEntry]):
        self.cover_rows = entries
        self.cover_tree.delete(*self.cover_tree.get_children())
        self.cover_by_iid.clear()
        for index, entry in enumerate(entries):
            iid = str(index)
            self.cover_tree.insert('', 'end', iid=iid,
                                   tags=[] if entry.cover else ['missing'],
                                   values=(entry.rel, '有' if entry.cover else '缺',
                                           human_size(entry.size)))
            self.cover_by_iid[iid] = entry
        missing = sum(1 for e in entries if not e.cover)
        self.set_status(f'{len(entries)} 个 ROM，{missing} 个缺封面')
        self.log(f'封面列表：{len(entries)} 个 ROM，{missing} 个缺封面。')

    def _selected_cover(self) -> RomEntry | None:
        selection = self.cover_tree.selection()
        return self.cover_by_iid.get(selection[0]) if selection else None

    def _show_cover_preview(self):
        entry = self._selected_cover()
        if entry is None:
            return
        if not entry.cover:
            self.preview_label.configure(
                image='', text='暂无封面\n\n首次启动该游戏时会\n自动截取开始画面')
            self._preview_photo = None
            self.cover_info.configure(text=f'{entry.rel}\n缺封面：可点“用图片生成封面…”或直接开玩。')
            return
        if not HAVE_COVER_CODEC:
            self.preview_label.configure(image='', text='缺少 Pillow / 编码器')
            return
        try:
            image = read_cover_image(entry.cover)
            preview = image.copy()
            preview.thumbnail((330, 260))
            self._preview_photo = ImageTk.PhotoImage(preview)
            self.preview_label.configure(image=self._preview_photo, text='')
            self.cover_info.configure(
                text=f'{entry.rel}\n封面 {image.width}×{image.height}，'
                     f'{entry.cover.stat().st_size} 字节')
        except Exception as error:
            self.preview_label.configure(image='', text='封面无法解码')
            self.cover_info.configure(text=f'{entry.rel}\n{error}')

    def cover_from_image(self):
        entry = self._selected_cover()
        if entry is None:
            messagebox.showinfo('未选择', '请先在列表里选择一个游戏。')
            return
        if not HAVE_COVER_CODEC:
            messagebox.showerror(
                '缺少依赖',
                '需要 Pillow：\n\n  pip install pillow\n\n'
                '安装后重新打开本程序。')
            return
        image_path = filedialog.askopenfilename(
            title='选择封面图片（PNG/JPG，建议 256×240 或更小）',
            filetypes=[('图片', '*.png *.jpg *.jpeg *.bmp *.webp'), ('所有文件', '*.*')])
        if not image_path:
            return
        try:
            image = Image.open(image_path).convert('RGB')
            packed = encode_cover_image(image)
            decode_cover(packed)
            target = entry.path.with_suffix('.COV')
            target.write_bytes(packed)
            entry.cover = target
            self.log(f'已生成封面 {target.name}（{image.width}×{image.height}）')
            self.refresh_covers()
        except Exception as error:
            messagebox.showerror('生成失败', str(error))

    def cover_delete(self):
        entry = self._selected_cover()
        if entry is None:
            messagebox.showinfo('未选择', '请先在列表里选择一个游戏。')
            return
        if not entry.cover:
            messagebox.showinfo('没有封面', '这个游戏本来就没有 .COV。')
            return
        if not messagebox.askyesno(
                '删除封面',
                f'删除 {entry.cover.name}？\n\n'
                '删除后，游戏机第一次启动这个 ROM 时会自动截取开始画面作为封面。'):
            return
        try:
            entry.cover.unlink()
            self.log(f'已删除 {entry.cover.name}，等待游戏机自动生成。')
            self.refresh_covers()
        except OSError as error:
            messagebox.showerror('删除失败', str(error))

    # ------------------------------------------------------------- maintain
    def _nes_path(self) -> Path | None:
        text = self.nes_var.get().strip()
        if not text:
            messagebox.showwarning('目标无效', '请先选择 SD 卡上的 NES 文件夹。')
            return None
        path = Path(text)
        if not path.is_dir():
            messagebox.showwarning('目标无效', f'文件夹不存在：\n{path}')
            return None
        return path

    def run_dedup(self, apply: bool):
        if self._busy:
            return
        source_text = self.dedup_dir_var.get().strip()
        if not source_text or not Path(source_text).is_dir():
            messagebox.showwarning('目录无效', '请选择要整理的去重目录（通常是 NES/famicom）。')
            return
        if apply and not messagebox.askyesno(
                '执行去重',
                '将把同名的多余版本移到 NES 文件夹外的隔离目录，\n'
                '并重命名 CATALOG.* 让游戏机重扫。\n\n'
                'Hack、汉化、Beta、Proto 不会被动。\n\n继续吗？'):
            return
        self.log(f'去重目录：{source_text}')
        self._start_task('去重', lambda: self._dedup_worker(source_text, apply))

    def run_sort(self, apply: bool):
        nes = self._nes_path()
        if nes is None:
            return
        catalog = nes / 'CATALOG.IDX'
        if not catalog.exists():
            messagebox.showinfo(
                '没有目录',
                'CATALOG.IDX 不存在。\n\n'
                '先让游戏机开机重建目录，或点“重建目录”后重新插卡开机。')
            return
        self._start_task('排序', lambda: self._sort_worker(catalog, apply))

    def rebuild_catalog(self, confirm: bool = True):
        nes = self._nes_path()
        if nes is None:
            return
        targets = [nes / name for name in ('CATALOG.IDX', 'CATALOG.NEW', 'CATALOG.BAK')]
        existing = [path for path in targets if path.exists()]
        if not existing:
            messagebox.showinfo('没有目录文件', '没有找到 CATALOG.IDX / .NEW / .BAK。')
            return
        if confirm and not messagebox.askyesno(
                '重建目录',
                '把以下文件改名为 .OLD：\n\n'
                + '\n'.join(path.name for path in existing)
                + '\n\n下次开机游戏机会重新扫描全部 ROM。继续吗？'):
            return
        for path in existing:
            target = path.with_name(path.name + '.OLD')
            try:
                if target.exists():
                    target.unlink()
                path.replace(target)
                self.log(f'重建：{path.name} -> {target.name}')
            except OSError as error:
                self.log(f'重建失败 {path.name}: {error}')
        self.set_status('目录已标记重建')

    def run_pinyin(self):
        nes = self._nes_path()
        if nes is None:
            return
        catalog = nes / 'CATALOG.IDX'
        if not catalog.exists():
            messagebox.showinfo('没有目录', '请先重建目录并让游戏机开机扫描一次。')
            return
        self._start_task('拼音', lambda: self._pinyin_worker(catalog))

    @staticmethod
    def install_fds_bios(source: Path, nes: Path) -> Path:
        data = Path(source).read_bytes()
        if len(data) != 8192:
            raise ValueError(f'disksys.rom 必须是 8192 字节，当前为 {len(data)} 字节。')
        vector = data[0x1FFC] | (data[0x1FFD] << 8)
        if vector < 0xE000:
            raise ValueError(f'复位向量 0x{vector:04X} 无效，可能不是 FDS BIOS。')
        if len(set(data)) < 8:
            raise ValueError('文件内容不像 8 KiB BIOS。')
        target = Path(nes) / 'DISKSYS.ROM'
        target.write_bytes(data)
        return target

    def import_fds_bios(self):
        nes = self._nes_path()
        if nes is None:
            return
        path = filedialog.askopenfilename(
            title='选择 disksys.rom（8192 字节）',
            filetypes=[('FDS BIOS', '*.rom *.bin'), ('所有文件', '*.*')])
        if not path:
            return
        target = nes / 'DISKSYS.ROM'
        if target.exists() and not messagebox.askyesno(
                '覆盖 BIOS',
                f'{target} 已存在。\n\n用新文件覆盖吗？游戏机重启后生效。'):
            return
        try:
            saved = self.install_fds_bios(Path(path), nes)
        except Exception as error:
            messagebox.showerror('导入失败', str(error))
            return
        self.log(f'已导入 FDS BIOS：{saved}（重启游戏机后生效）')
        self.refresh_bios_status()
        messagebox.showinfo(
            '已导入',
            'BIOS 已写入 NES/DISKSYS.ROM。\n\n'
            '重启游戏机后生效；卡上 BIOS 优先于固件内置 BIOS。')

    def refresh_bios_status(self):
        if not hasattr(self, 'bios_status'):
            return
        text = self.nes_var.get().strip()
        if not text:
            self.bios_status.configure(text='未选择 NES 目录')
            return
        target = Path(text) / 'DISKSYS.ROM'
        if not target.exists():
            self.bios_status.configure(
                text='未导入：使用固件内置 BIOS（Release 固件已内置开源 OpenDiskSysROM）')
            return
        try:
            data = target.read_bytes()
        except OSError as error:
            self.bios_status.configure(text=f'无法读取：{error}')
            return
        if len(data) != 8192:
            self.bios_status.configure(
                text=f'大小异常：{len(data)} 字节（应为 8192）')
            return
        vector = data[0x1FFC] | (data[0x1FFD] << 8)
        if vector < 0xE000:
            self.bios_status.configure(
                text=f'已导入，但复位向量 0x{vector:04X} 异常')
            return
        self.bios_status.configure(
            text=f'已导入：DISKSYS.ROM（8192 字节，向量 0x{vector:04X}），重启后生效')

    def open_bios_page(self):
        url = 'https://github.com/6baol/nes-fire-stm32f407/releases'
        self.log(f'开源 BIOS 下载/源码：{url}')
        self.log('OpenDiskSysROM 源码：https://github.com/RetrolariumLab/OpenDiskSysROM')
        webbrowser.open(url)

    def _start_task(self, label: str, worker):
        if self._busy:
            return
        self._busy = True
        self.set_status(f'{label}中…')

        def run():
            try:
                worker()
                self.set_status(f'{label}完成')
            except Exception:
                self.log(traceback.format_exc())
                self.set_status(f'{label}失败')
            finally:
                self.after(0, lambda: setattr(self, '_busy', False))

        threading.Thread(target=run, daemon=True).start()

    def _dedup_worker(self, source: str, apply: bool):
        if not HAVE_MAINTENANCE:
            self.log('去重模块未加载；请使用源码版运行。')
            return
        buffer = io.StringIO()
        old_argv = sys.argv
        sys.argv = ['dedup_sd.py', source] + (['--apply'] if apply else [])
        try:
            with contextlib.redirect_stdout(buffer):
                dedup_sd.main()
        except SystemExit as exit_code:
            buffer.write(f'\n[结束] {exit_code}\n')
        finally:
            sys.argv = old_argv
        self.log(buffer.getvalue().strip())

    def _sort_worker(self, catalog: Path, apply: bool):
        if not HAVE_MAINTENANCE:
            self.log('排序模块未加载；请使用源码版运行。')
            return
        result = sort_catalog.sort_catalog(catalog.read_bytes())
        count = struct.unpack_from('<I', result, 8)[0]
        if apply:
            self._write_atomic(catalog, result)
            self.log(f'已按英文名排序 {count} 条')
        else:
            self.log(f'预演：{count} 条会按英文名排序（未写入）')

    def _pinyin_worker(self, catalog: Path):
        if not HAVE_MAINTENANCE:
            self.log('拼音模块未加载；请使用源码版运行。')
            return
        try:
            data, filled = make_pinyin.fill_catalog(catalog.read_bytes())
        except ImportError as error:
            self.log(f'拼音功能需要 pypinyin：{error}')
            return
        count = struct.unpack_from('<I', data, 8)[0]
        self._write_atomic(catalog, data)
        self.log(f'已填充拼音 {filled}/{count} 条')

    @staticmethod
    def _write_atomic(path: Path, data: bytes):
        temp = path.with_name(path.name + '.TMP')
        temp.write_bytes(data)
        temp.replace(path)


HELP_TEXT = """NesFire 导入助手
================

一、导入外部 ROM
  1. “ROM 来源”选择电脑上存放 .nes / .fds 的文件夹。
  2. “SD 卡 NES 目录”选择卡里的 NES 文件夹，程序会自动识别盘符。
  3. 点“扫描”。表格里：
       · 橙色文字 = Hack / 汉化 / 改版
       · “缺” = 没有 .COV 封面
       · “重复” = 完全相同的文件或同名版本
  4. 选中游戏，点“导入选中”。
       · 正常 ROM 进入 NES/imports/
       · Hack/汉化进入 NES/hacks/
       · 同名文件不会覆盖，会自动加 (2)、(3)

二、封面
  · 有 .COV 时直接显示。
  · 没有 .COV 也不用管：游戏机第一次启动该 ROM 时，会等待约 2-3 秒
    让它进入标题/开始画面，然后自动截图并写回 <同名>.COV。
    以后再进菜单就有海报了。
  · 想手动指定：选中游戏 -> “用图片生成封面…” -> 选一张图。
    建议使用 256×240 的 NES 截图；其他尺寸也能用，但可能变形。
  · “删除封面”会移除 .COV，让游戏机下次启动重新自动截取。

三、维护
  · 检查/执行去重：同英文标题只留一个版本。Hack、汉化、Beta、Proto、
    Bootleg 受保护，永远不会被移动。
  · 重建目录：把 CATALOG.* 改名为 .OLD，游戏机下次开机会重新扫描。
    导入 ROM 后通常需要这一步。
  · 按英文名排序：目录重建后运行，让菜单顺序按英文标题排列。
  · 填充拼音索引：给中文标题补拼音，方便搜索。

四、FDS BIOS
  · FDS 游戏需要 8 KiB 的 disksys.rom。
  · 卡上的 NES/DISKSYS.ROM 优先；没有时使用固件内置 BIOS。
  · 维护页 -> FDS BIOS -> “一键导入 disksys.rom…”；重启游戏机后生效。
  · Release 固件内置开源 OpenDiskSysROM（LGPL-3.0），
    源码：https://github.com/RetrolariumLab/OpenDiskSysROM
  · 也可以导入你自己合法拥有的 FDS BIOS。

五、注意
  · 操作前建议先备份 NES 文件夹。
  · 去重会把文件移到 NES 文件夹外的 _dedup_removed_* 目录，不会直接删除。
  · 本程序不会修改 ROM 内容，也不会上传数据；只有“获取开源 BIOS”会打开浏览器。
"""


def main():
    if sys.platform == 'win32':
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    app = ImportAssistant()
    app.mainloop()


if __name__ == '__main__':
    main()
