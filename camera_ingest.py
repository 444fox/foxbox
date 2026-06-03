"""
Camera Ingest Tool  v2
  Tab 1 — Ingest : scan SD → rename by capture time → copy to USB + server → verify → delete
  Tab 2 — Safe Delete : scan SD + server, match by SHA256 hash, delete confirmed copies from SD
"""

import os
import json
import shutil
import hashlib
import threading
import concurrent.futures
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from datetime import datetime
from pathlib import Path

try:
    from PIL import Image
    from PIL.ExifTags import TAGS
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

try:
    from hachoir.parser import createParser
    from hachoir.metadata import extractMetadata
    HACHOIR_AVAILABLE = True
except ImportError:
    HACHOIR_AVAILABLE = False

# ── Extension sets ─────────────────────────────────────────────────────────────
PHOTO_EXT = {'.jpg','.jpeg','.png','.cr2','.cr3','.nef','.arw',
             '.dng','.heic','.heif','.tif','.tiff','.raf','.orf'}
VIDEO_EXT = {'.mp4','.mov','.avi','.mts','.m2ts','.mkv',
             '.mxf','.3gp','.wmv'}
ALL_EXT   = PHOTO_EXT | VIDEO_EXT

# ── Theme ──────────────────────────────────────────────────────────────────────
BG      = '#1a1d23'
PANEL   = '#22262f'
BLUE    = '#4fa3e0'
RED     = '#e05c4f'
ORANGE  = '#e08c4f'
TEXT    = '#d8dde8'
DIM     = '#6b7280'
GREEN   = '#4caf7d'
YELLOW  = '#e0a84f'
MONO    = ('Consolas', 9)
UI      = ('Segoe UI', 10)
LABEL   = ('Segoe UI Semibold', 10)
TITLE   = ('Segoe UI Light', 22)
SUB     = ('Segoe UI', 11)
SEMIBOLD= ('Segoe UI Semibold', 11)

# ── Shared helpers ─────────────────────────────────────────────────────────────

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


# ── Hash cache ────────────────────────────────────────────────────────────────
# Stored next to the script as .camera_ingest_cache.json
# Format: { "abs_path_str": {"hash": "...", "size": N, "mtime": F}, ... }

CACHE_FILE = Path(__file__).parent / '.camera_ingest_cache.json'

def _load_cache() -> dict:
    try:
        if CACHE_FILE.exists():
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _save_cache(cache: dict):
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f)
    except Exception:
        pass

def sha256_cached(path: Path, cache: dict) -> str:
    """
    Return SHA256 for path. Uses cache if file size+mtime unchanged.
    Updates cache entry if a fresh hash is computed.
    """
    key = str(path)
    try:
        st = path.stat()
        size, mtime = st.st_size, st.st_mtime
    except OSError:
        return sha256_file(path)

    entry = cache.get(key)
    if entry and entry.get('size') == size and abs(entry.get('mtime', 0) - mtime) < 1.0:
        return entry['hash']

    h = sha256_file(path)
    cache[key] = {'hash': h, 'size': size, 'mtime': mtime}
    return h


def get_capture_time(path: Path):
    ext = path.suffix.lower()
    if PILLOW_AVAILABLE and ext in PHOTO_EXT:
        try:
            img = Image.open(path)
            exif = img._getexif()
            if exif:
                for tid, val in exif.items():
                    tag = TAGS.get(tid, tid)
                    if tag in ('DateTimeOriginal','DateTimeDigitized','DateTime'):
                        return datetime.strptime(val, '%Y:%m:%d %H:%M:%S')
        except Exception:
            pass
    if HACHOIR_AVAILABLE and ext in VIDEO_EXT:
        try:
            parser = createParser(str(path))
            if parser:
                with parser:
                    meta = extractMetadata(parser)
                    if meta:
                        for item in meta.exportPlaintext():
                            if 'creation date' in item.lower():
                                parts = item.split(': ', 1)
                                if len(parts) == 2:
                                    raw = parts[1].strip()
                                    for fmt in ('%Y-%m-%d %H:%M:%S','%Y-%m-%dT%H:%M:%S'):
                                        try:
                                            return datetime.strptime(raw[:19], fmt)
                                        except ValueError:
                                            pass
        except Exception:
            pass
    try:
        s = path.stat()
        return datetime.fromtimestamp(min(s.st_mtime, s.st_ctime))
    except Exception:
        return None


def scan_media(root: Path) -> list:
    found = []
    for dp, _, fns in os.walk(root):
        for fn in fns:
            if Path(fn).suffix.lower() in ALL_EXT:
                found.append(Path(dp) / fn)
    return found


def build_dest_name(src: Path, capture_time, existing: set) -> str:
    base = capture_time.strftime('%Y%m%d%H%M%S')
    ext  = src.suffix.lower()
    name = base + ext
    n = 1
    while name in existing:
        name = f"{base}_{n}{ext}"
        n += 1
    existing.add(name)
    return name


def copy_verify(src: Path, dst: Path, log_fn) -> bool:
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        log_fn(f"  → Copying to {dst}")
        shutil.copy2(src, dst)
        if sha256_file(src) == sha256_file(dst):
            log_fn(f"  ✓ Verified  {dst.name}", 'ok')
            return True
        else:
            log_fn(f"  ✗ HASH MISMATCH — removing bad copy", 'error')
            dst.unlink(missing_ok=True)
            return False
    except Exception as e:
        log_fn(f"  ✗ Copy error: {e}", 'error')
        return False


# ── Log widget factory ─────────────────────────────────────────────────────────

def make_log(parent) -> scrolledtext.ScrolledText:
    w = scrolledtext.ScrolledText(parent, bg='#111318', fg=TEXT,
                                  font=MONO, state='disabled',
                                  relief='flat', bd=6, wrap='word')
    w.tag_config('ok',     foreground=GREEN)
    w.tag_config('warn',   foreground=YELLOW)
    w.tag_config('error',  foreground=RED)
    w.tag_config('accent', foreground=BLUE)
    w.tag_config('orange', foreground=ORANGE)
    w.tag_config('dim',    foreground=DIM)
    return w


def wlog(widget, msg: str, tag='info'):
    widget.configure(state='normal')
    ts = datetime.now().strftime('%H:%M:%S')
    widget.insert('end', f"[{ts}] {msg}\n", tag)
    widget.see('end')
    widget.configure(state='disabled')


# ── Path row helper ────────────────────────────────────────────────────────────

def path_row(parent, label, var, browse_cmd, row):
    tk.Label(parent, text=label, font=LABEL, bg=PANEL, fg=TEXT,
             width=28, anchor='w').grid(row=row, column=0, padx=(12,6), pady=6, sticky='w')
    tk.Entry(parent, textvariable=var, bg='#2c3140', fg=TEXT,
             insertbackground=TEXT, relief='flat', font=UI
             ).grid(row=row, column=1, padx=(0,6), pady=6, sticky='ew')
    tk.Button(parent, text="Browse…", command=browse_cmd,
              bg=BG, fg=BLUE, activebackground=BLUE, activeforeground=BG,
              relief='flat', font=UI, cursor='hand2', padx=10, pady=3
              ).grid(row=row, column=2, padx=(0,12), pady=6)


def lf(parent, title):
    """Styled LabelFrame."""
    return tk.LabelFrame(parent, text=f"  {title}  ",
                         bg=PANEL, fg=DIM, font=LABEL,
                         bd=1, relief='flat',
                         highlightbackground=DIM, highlightthickness=1)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Ingest
# ══════════════════════════════════════════════════════════════════════════════

class IngestTab(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self._sd_var      = tk.StringVar()
        self._local_var   = tk.StringVar()
        self._remote_var  = tk.StringVar()
        self._status_var  = tk.StringVar(value="Ready.")
        self._prog_var    = tk.DoubleVar(value=0.0)
        self._delete_var  = tk.BooleanVar(value=True)
        self._subdir_var  = tk.BooleanVar(value=True)
        self._running     = False
        self._names: set  = set()
        self._build()

    def _build(self):
        c = tk.Frame(self, bg=BG)
        c.pack(fill='both', expand=True, padx=28, pady=18)

        # Paths
        pf = lf(c, "Paths")
        pf.pack(fill='x', pady=(0,14))
        pf.grid_columnconfigure(1, weight=1)
        path_row(pf, "SD Card / Source",           self._sd_var,     lambda: self._browse(self._sd_var,     "Select SD Card Root"),           0)
        path_row(pf, "Local USB Destination",       self._local_var,  lambda: self._browse(self._local_var,  "Select Local USB Destination"),   1)
        path_row(pf, "Remote Server Destination",   self._remote_var, lambda: self._browse(self._remote_var, "Select Remote Server Destination"),2)

        # Options
        of = lf(c, "Options")
        of.pack(fill='x', pady=(0,14))
        for col, (text, var) in enumerate([
            ("Delete source files after verified copy", self._delete_var),
            ("Organize into YYYY/MM subfolders",        self._subdir_var),
        ]):
            tk.Checkbutton(of, text=text, variable=var,
                           bg=PANEL, fg=TEXT, activebackground=PANEL,
                           selectcolor=BG, font=UI
                           ).grid(row=0, column=col, padx=16, pady=8, sticky='w')

        # Progress
        tk.Label(c, textvariable=self._status_var, bg=BG, fg=DIM,
                 font=UI, anchor='w').pack(fill='x', pady=(0,4))
        style = ttk.Style()
        style.configure("I.Horizontal.TProgressbar",
                        troughcolor=PANEL, background=BLUE,
                        bordercolor=PANEL, lightcolor=BLUE, darkcolor=BLUE)
        ttk.Progressbar(c, variable=self._prog_var, maximum=100,
                        style="I.Horizontal.TProgressbar"
                        ).pack(fill='x', pady=(0,10))

        # Log
        lframe = lf(c, "Activity Log")
        lframe.pack(fill='both', expand=True, pady=(0,14))
        self._log = make_log(lframe)
        self._log.pack(fill='both', expand=True, padx=4, pady=4)

        # Buttons
        br = tk.Frame(c, bg=BG)
        br.pack(fill='x')
        self._start_btn = tk.Button(br, text="▶  START INGEST",
                                    command=self._start,
                                    bg=BLUE, fg=BG,
                                    activebackground='#7bbfe8', activeforeground=BG,
                                    relief='flat', font=SEMIBOLD,
                                    cursor='hand2', padx=22, pady=8)
        self._start_btn.pack(side='left')
        tk.Button(br, text="Clear Log",
                  command=lambda: (self._log.configure(state='normal'),
                                   self._log.delete('1.0','end'),
                                   self._log.configure(state='disabled')),
                  bg=PANEL, fg=DIM, activebackground=BG,
                  relief='flat', font=UI, cursor='hand2', padx=14, pady=8
                  ).pack(side='left', padx=(10,0))

    def _browse(self, var, title):
        p = filedialog.askdirectory(title=title)
        if p: var.set(p)

    def log(self, msg, tag='info'):
        wlog(self._log, msg, tag)

    def _start(self):
        if self._running: return
        sd, local, remote = (self._sd_var.get().strip(),
                             self._local_var.get().strip(),
                             self._remote_var.get().strip())
        if not sd or not local or not remote:
            messagebox.showerror("Missing Paths", "Please set all three paths.")
            return
        sd_p = Path(sd)
        if not sd_p.exists():
            messagebox.showerror("Not Found", f"SD card path not found:\n{sd}")
            return
        self._running = True
        self._start_btn.configure(state='disabled', text="⏳  Running…")
        self._names.clear()
        self._prog_var.set(0)
        threading.Thread(target=self._run,
                         args=(sd_p, Path(local), Path(remote)),
                         daemon=True).start()

    def _run(self, sd_p, local_p, remote_p):
        log = self.log
        do_del = self._delete_var.get()
        do_sub = self._subdir_var.get()
        try:
            self._status_var.set("Scanning SD card…")
            log("═"*60, 'accent')
            log(f"Source      : {sd_p}", 'accent')
            log(f"Local dest  : {local_p}", 'accent')
            log(f"Remote dest : {remote_p}", 'accent')
            log("═"*60, 'accent')

            files = scan_media(sd_p)
            if not files:
                log("No media files found.", 'warn')
                self._status_var.set("No files found.")
                return
            log(f"Found {len(files)} media file(s).", 'ok')

            self._status_var.set("Reading timestamps…")
            timed = [(f, get_capture_time(f)) for f in files]
            timed.sort(key=lambda x: (x[1] is None, x[1] or datetime.min, x[0].name))

            total = len(timed)
            success, failed = [], []

            for i, (src, ct) in enumerate(timed, 1):
                self._prog_var.set((i-1)/total*100)
                self._status_var.set(f"Processing {i}/{total}: {src.name}")
                log(f"\n[{i}/{total}] {src.name}", 'accent')

                if ct:
                    log(f"  Captured : {ct.strftime('%Y-%m-%d %H:%M:%S')}", 'dim')
                    dest_name = build_dest_name(src, ct, self._names)
                else:
                    log("  ⚠  No capture time — keeping original filename", 'warn')
                    dest_name = src.name
                    self._names.add(dest_name)

                log(f"  Renamed  : {dest_name}", 'dim')
                sub = (Path(ct.strftime('%Y')) / ct.strftime('%m')) if (do_sub and ct) else Path('')

                def _log_line(msg, tag='info'): log(msg, tag)

                ok_l = copy_verify(src, local_p  / sub / dest_name, _log_line)
                ok_r = copy_verify(src, remote_p / sub / dest_name, _log_line)

                if ok_l and ok_r:
                    success.append(src)
                    if do_del:
                        try:
                            src.unlink()
                            log(f"  🗑  Deleted source: {src.name}", 'ok')
                        except Exception as e:
                            log(f"  ✗ Could not delete source: {e}", 'error')
                    else:
                        log("  (Source kept — delete disabled)", 'dim')
                else:
                    failed.append(src)
                    log("  ✗ SKIPPED deletion — copy failed on one or both destinations", 'error')

            self._prog_var.set(100)
            log("\n"+"═"*60, 'accent')
            log(f"DONE  —  {len(success)} succeeded, {len(failed)} failed",
                'ok' if not failed else 'warn')
            if failed:
                log("Files NOT deleted (copy error):", 'error')
                for f in failed: log(f"  • {f}", 'error')
            self._status_var.set(f"Complete: {len(success)}/{total} transferred.")

        except Exception as e:
            import traceback
            log(f"\n✗ Unexpected error: {e}", 'error')
            log(traceback.format_exc(), 'error')
            self._status_var.set("Error — see log.")
        finally:
            self._running = False
            self.after(0, lambda: self._start_btn.configure(
                state='normal', text="▶  START INGEST"))


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Safe Delete
# ══════════════════════════════════════════════════════════════════════════════

class SafeDeleteTab(tk.Frame):
    """
    Scan SD card + file server.
    Match files by SHA256 hash (works even after rename).
    Show a preview list, then delete confirmed files from SD only.
    """
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self._sd_var     = tk.StringVar()
        self._server_var = tk.StringVar()
        self._status_var = tk.StringVar(value="Ready. Set paths and click Scan.")
        self._prog_var   = tk.DoubleVar(value=0.0)
        self._running          = False
        self._cancel_requested = False
        # Results: list of (sd_path, server_path, hash)
        self._matches: list = []
        self._build()

    def _build(self):
        c = tk.Frame(self, bg=BG)
        c.pack(fill='both', expand=True, padx=28, pady=18)

        # Info banner
        info = tk.Frame(c, bg='#1e2a1e', padx=14, pady=10)
        info.pack(fill='x', pady=(0,14))
        tk.Label(info,
                 text="🛡  Safe Delete compares files by content (SHA256 hash), not filename.\n"
                      "    Files are only removed from the SD card once a byte-perfect copy is confirmed on the server.",
                 bg='#1e2a1e', fg=GREEN, font=UI, justify='left'
                 ).pack(anchor='w')

        # Paths
        pf = lf(c, "Paths")
        pf.pack(fill='x', pady=(0,14))
        pf.grid_columnconfigure(1, weight=1)
        path_row(pf, "SD Card / Source",     self._sd_var,
                 lambda: self._browse(self._sd_var,     "Select SD Card Root"), 0)
        path_row(pf, "File Server to Check", self._server_var,
                 lambda: self._browse(self._server_var, "Select Server Folder to Search"), 1)

        # Progress
        tk.Label(c, textvariable=self._status_var, bg=BG, fg=DIM,
                 font=UI, anchor='w').pack(fill='x', pady=(0,4))
        style = ttk.Style()
        style.configure("SD.Horizontal.TProgressbar",
                        troughcolor=PANEL, background=ORANGE,
                        bordercolor=PANEL, lightcolor=ORANGE, darkcolor=ORANGE)
        ttk.Progressbar(c, variable=self._prog_var, maximum=100,
                        style="SD.Horizontal.TProgressbar"
                        ).pack(fill='x', pady=(0,10))

        # Results pane (two-column: SD file | Server match)
        rf = lf(c, "Scan Results — Files Found on Server")
        rf.pack(fill='both', expand=True, pady=(0,14))

        cols = ('sd_file', 'sd_size', 'server_match', 'status')
        self._tree = ttk.Treeview(rf, columns=cols, show='headings', selectmode='none')
        style.configure("Treeview",
                        background='#111318', foreground=TEXT,
                        fieldbackground='#111318', rowheight=22,
                        font=MONO)
        style.configure("Treeview.Heading",
                        background=PANEL, foreground=DIM, font=LABEL)
        style.map("Treeview", background=[('selected','#2a3040')])

        self._tree.heading('sd_file',      text='SD Card File')
        self._tree.heading('sd_size',      text='Size')
        self._tree.heading('server_match', text='Server Copy Found At')
        self._tree.heading('status',       text='Status')
        self._tree.column('sd_file',      width=220, anchor='w')
        self._tree.column('sd_size',      width=80,  anchor='e')
        self._tree.column('server_match', width=340, anchor='w')
        self._tree.column('status',       width=90,  anchor='center')

        self._tree.tag_configure('matched',   foreground=GREEN)
        self._tree.tag_configure('unmatched', foreground=DIM)
        self._tree.tag_configure('deleted',   foreground=ORANGE)

        vsb = ttk.Scrollbar(rf, orient='vertical', command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side='left', fill='both', expand=True, padx=(4,0), pady=4)
        vsb.pack(side='right', fill='y', pady=4, padx=(0,4))

        # Log
        lframe = lf(c, "Activity Log")
        lframe.pack(fill='x', pady=(0,14))
        self._log = make_log(lframe)
        self._log.configure(height=7)
        self._log.pack(fill='x', padx=4, pady=4)

        # Buttons
        br = tk.Frame(c, bg=BG)
        br.pack(fill='x')

        self._scan_btn = tk.Button(br, text="🔍  SCAN",
                                   command=self._start_scan,
                                   bg=BLUE, fg=BG,
                                   activebackground='#7bbfe8', activeforeground=BG,
                                   relief='flat', font=SEMIBOLD,
                                   cursor='hand2', padx=20, pady=8)
        self._scan_btn.pack(side='left')

        self._cancel_btn = tk.Button(br, text="✕  CANCEL",
                                     command=self._cancel_scan,
                                     bg=RED, fg=BG,
                                     activebackground='#f07070', activeforeground=BG,
                                     relief='flat', font=SEMIBOLD,
                                     cursor='hand2', padx=16, pady=8,
                                     state='disabled')
        self._cancel_btn.pack(side='left', padx=(10,0))

        self._del_btn = tk.Button(br, text="🗑  DELETE MATCHED FROM SD",
                                  command=self._confirm_delete,
                                  bg=ORANGE, fg=BG,
                                  activebackground='#f0a060', activeforeground=BG,
                                  relief='flat', font=SEMIBOLD,
                                  cursor='hand2', padx=20, pady=8,
                                  state='disabled')
        self._del_btn.pack(side='left', padx=(10,0))

        tk.Button(br, text="Clear Log",
                  command=lambda: (self._log.configure(state='normal'),
                                   self._log.delete('1.0','end'),
                                   self._log.configure(state='disabled')),
                  bg=PANEL, fg=DIM, activebackground=BG,
                  relief='flat', font=UI, cursor='hand2', padx=14, pady=8
                  ).pack(side='left', padx=(10,0))

        tk.Button(br, text="Clear Hash Cache",
                  command=self._clear_cache,
                  bg=PANEL, fg=YELLOW, activebackground=BG,
                  relief='flat', font=UI, cursor='hand2', padx=14, pady=8
                  ).pack(side='right')

    def _clear_cache(self):
        try:
            if CACHE_FILE.exists():
                CACHE_FILE.unlink()
            self.log("Hash cache cleared — next scan will re-hash all server files.", 'warn')
        except Exception as e:
            self.log(f"Could not clear cache: {e}", 'error')

    def _cancel_scan(self):
        if self._running:
            self._cancel_requested = True
            self._cancel_btn.configure(state='disabled', text="Cancelling…")
            self._status_var.set("Cancelling — finishing current file…")

    def _browse(self, var, title):
        p = filedialog.askdirectory(title=title)
        if p: var.set(p)

    def log(self, msg, tag='info'):
        wlog(self._log, msg, tag)

    # ── Scan ──────────────────────────────────────────────────────────────────

    def _start_scan(self):
        if self._running: return
        sd     = self._sd_var.get().strip()
        server = self._server_var.get().strip()
        if not sd or not server:
            messagebox.showerror("Missing Paths", "Please set both the SD card and server paths.")
            return
        sd_p = Path(sd); srv_p = Path(server)
        if not sd_p.exists():
            messagebox.showerror("Not Found", f"SD card path not found:\n{sd}")
            return
        if not srv_p.exists():
            messagebox.showerror("Not Found", f"Server path not found:\n{server}")
            return

        # Clear previous results
        for row in self._tree.get_children():
            self._tree.delete(row)
        self._matches.clear()
        self._del_btn.configure(state='disabled')
        self._prog_var.set(0)
        self._running = True
        self._cancel_requested = False
        self._scan_btn.configure(state='disabled', text="⏳  Scanning…")
        self._cancel_btn.configure(state='normal', text="✕  CANCEL")

        threading.Thread(target=self._run_scan,
                         args=(sd_p, srv_p), daemon=True).start()

    def _run_scan(self, sd_p: Path, srv_p: Path):
        log = self.log
        WORKERS = 8   # parallel threads — tune up/down for your network
        try:
            log("═"*60, 'orange')
            log(f"SD Card : {sd_p}", 'orange')
            log(f"Server  : {srv_p}", 'orange')
            log("═"*60, 'orange')

            cache      = _load_cache()
            lock       = threading.Lock()
            match_lock = threading.Lock()

            def cancelled():
                """Check flag and log if set. Call at phase boundaries."""
                if self._cancel_requested:
                    log("─"*60, 'dim')
                    log("Scan cancelled by user.", 'warn')
                    self._status_var.set("Scan cancelled.")
                    if self._matches:
                        self.after(0, lambda: self._del_btn.configure(state='normal'))
                        log(f"{len(self._matches)} file(s) already confirmed before cancel — delete button enabled.", 'warn')
                    return True
                return False

            # ══════════════════════════════════════════════════════════════════
            # PHASE 1 — Scan both sides (no hashing yet, just metadata)
            # ══════════════════════════════════════════════════════════════════
            self._status_var.set("Scanning file lists…")
            log("Phase 1 — Scanning file lists (no hashing yet)…", 'dim')

            sd_files     = scan_media(sd_p)
            server_files = scan_media(srv_p)
            log(f"  SD card : {len(sd_files)} file(s)", 'dim')
            log(f"  Server  : {len(server_files)} file(s)", 'dim')

            # Build server name index: lowercase stem → [Path, ...]
            # (one name can appear in multiple folders)
            server_by_name: dict = {}
            for sf in server_files:
                key = sf.name.lower()
                server_by_name.setdefault(key, []).append(sf)

            # ══════════════════════════════════════════════════════════════════
            # PHASE 2 — Name-match SD files against server, split into buckets
            # ══════════════════════════════════════════════════════════════════
            log("Phase 2 — Name matching…", 'dim')
            self._status_var.set("Matching by filename…")

            # name_pairs  : [(sd_path, server_path)]  — need hash verification
            # no_name_hit : [sd_path]                 — no name match at all
            name_pairs:  list = []
            no_name_hit: list = []

            for sf in sd_files:
                candidates = server_by_name.get(sf.name.lower(), [])
                if candidates:
                    # Use the first candidate for now; hash will confirm
                    name_pairs.append((sf, candidates[0]))
                else:
                    no_name_hit.append(sf)

            log(f"  {len(name_pairs)} SD file(s) have a filename match on server.", 'dim')
            log(f"  {len(no_name_hit)} SD file(s) have NO filename match — will need full index.", 'dim')

            if cancelled(): return

            # ══════════════════════════════════════════════════════════════════
            # PHASE 3 — Hash the name-matched pairs to verify (fast path)
            # ══════════════════════════════════════════════════════════════════
            self._matched_confirmed: list = []   # (sd, srv, hash) — confirmed
            self._hash_failed_pairs: list = []   # (sd, srv) — name matched but hash differs

            matched   = 0
            unmatched = 0
            phase3_done = [0]

            # MP4/MOV containers often have embedded timestamps rewritten by
            # SMB shares or NAS devices on copy, changing a few header bytes.
            # For video files: if name AND size match, accept as confirmed.
            # For everything else: require hash match.
            CONTAINER_EXTS = {'.mp4', '.mov', '.mts', '.m2ts', '.mkv',
                               '.mxf', '.3gp', '.wmv', '.avi'}

            def verify_pair(pair):
                nonlocal matched, unmatched
                sd_f, srv_f = pair
                try:
                    sd_stat  = sd_f.stat()
                    srv_stat = srv_f.stat()
                    sd_size  = sd_stat.st_size
                    srv_size = srv_stat.st_size
                    sz       = self._fmt_size(sd_size)
                    rel      = str(srv_f.relative_to(srv_p))
                    ext      = sd_f.suffix.lower()
                    is_video = ext in CONTAINER_EXTS

                    with lock:
                        phase3_done[0] += 1
                        n = phase3_done[0]
                    total_pairs = len(name_pairs)
                    self._prog_var.set(n / max(total_pairs, 1) * 40)
                    self._status_var.set(f"Verifying {n}/{total_pairs}: {sd_f.name}")

                    # ── Size check (fast, always run first) ───────────────────
                    if sd_size != srv_size:
                        # Sizes differ — definitely not the same file
                        with lock:
                            self._hash_failed_pairs.append((sd_f, None))
                            unmatched += 1
                        log(f"  ✗ {sd_f.name}  size mismatch "
                            f"(SD {self._fmt_size(sd_size)} vs "
                            f"srv {self._fmt_size(srv_size)}) — queuing fallback", 'warn')
                        return

                    # ── Video files: name + size is sufficient ─────────────────
                    # MP4/MOV containers get header bytes rewritten by some NAS/
                    # SMB implementations (creation-date atoms, free atoms, etc.)
                    # which changes the hash even though the content is identical.
                    # Name + identical size is an extremely strong match signal.
                    if is_video:
                        with match_lock:
                            self._matches.append((sd_f, srv_f, None))
                            matched += 1
                        self.after(0, lambda sd_f=sd_f, sz=sz, rel=rel:
                                   self._tree.insert('', 'end',
                                       values=(sd_f.name, sz, rel, '✓ Name+Size'),
                                       tags=('matched',)))
                        log(f"  ✓ {sd_f.name}  →  {rel}  (name+size match)", 'ok')
                        return

                    # ── Photos/other: full hash verification ───────────────────
                    h_sd = sha256_file(sd_f)

                    # Hash server file — use cache if size+mtime unchanged
                    key   = str(srv_f)
                    entry = cache.get(key)
                    cached = (entry and
                              entry.get('size') == srv_size and
                              abs(entry.get('mtime', 0) - srv_stat.st_mtime) < 1.0)
                    h_srv = entry['hash'] if cached else sha256_file(srv_f)
                    if not cached:
                        with lock:
                            cache[key] = {'hash': h_srv,
                                          'size': srv_size,
                                          'mtime': srv_stat.st_mtime}

                    self._status_var.set(
                        f"Verifying {n}/{total_pairs}: {sd_f.name}"
                        + (" [srv cached]" if cached else ""))

                    if h_sd == h_srv:
                        with match_lock:
                            self._matches.append((sd_f, srv_f, h_sd))
                            matched += 1
                        self.after(0, lambda sd_f=sd_f, sz=sz, rel=rel:
                                   self._tree.insert('', 'end',
                                       values=(sd_f.name, sz, rel, '✓ Verified'),
                                       tags=('matched',)))
                        log(f"  ✓ {sd_f.name}  →  {rel}", 'ok')
                    else:
                        # Same name, same size, different hash — very unusual.
                        # Log detail and queue for fallback just in case.
                        with lock:
                            self._hash_failed_pairs.append((sd_f, h_sd))
                            unmatched += 1
                        log(f"  ≠ {sd_f.name}  name+size match but hash differs "
                            f"— queuing for full search", 'warn')

                except Exception as e:
                    log(f"  ✗ Error verifying {sd_f.name}: {e}", 'error')

            if name_pairs:
                log(f"Phase 3 — Verifying {len(name_pairs)} name-match pair(s) by hash…", 'dim')
                with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
                    list(pool.map(verify_pair, name_pairs))
                _save_cache(cache)

            if cancelled(): return

            # ══════════════════════════════════════════════════════════════════
            # PHASE 4 — Full server index for files with no name match
            #           (only runs if needed, and only after user confirms)
            # ══════════════════════════════════════════════════════════════════
            fallback_sd = no_name_hit + [pair[0] for pair in self._hash_failed_pairs]
            # Pre-computed hashes for hash-failed pairs (avoid re-hashing SD side)
            precomputed = {pair[0]: pair[1] for pair in self._hash_failed_pairs}

            if fallback_sd:
                # ── Pause and ask before doing expensive full server hash ─────
                # Build a readable list of the unresolved files for the dialog
                unresolved_names = [f.name for f in fallback_sd]
                file_list = "\n".join(f"  \u2022 {n}" for n in unresolved_names[:20])
                if len(unresolved_names) > 20:
                    file_list += f"\n  \u2026 and {len(unresolved_names)-20} more"

                already_indexed_names = {p.name.lower() for _, p in name_pairs}
                server_to_index = [sf for sf in server_files
                                   if sf.name.lower() not in already_indexed_names]

                msg = (
                    f"{len(fallback_sd)} file(s) on the SD card were not found "
                    f"on the server by filename:\n\n"
                    f"{file_list}\n\n"
                    f"These may not have been ingested yet, or they may have been "
                    f"renamed differently on the server.\n\n"
                    f"To search for them by content, the tool needs to hash "
                    f"{len(server_to_index):,} server file(s) — this may take "
                    f"a while depending on cache coverage.\n\n"
                    f"Proceed with full hash search?"
                )

                # Show dialog on main thread and wait for response
                proceed = [None]
                done_event = threading.Event()

                def ask():
                    proceed[0] = messagebox.askyesno(
                        "Unresolved Files — Full Hash Search?",
                        msg,
                        icon='question')
                    done_event.set()

                self.after(0, ask)
                done_event.wait()   # block background thread until user answers

                if not proceed[0]:
                    # User said no — mark all fallback files as skipped in the tree
                    log("─"*60, 'dim')
                    log(f"Full hash search skipped by user.", 'warn')
                    log(f"{len(fallback_sd)} file(s) left unresolved:", 'warn')
                    for sd_f in fallback_sd:
                        sz = self._fmt_size(sd_f.stat().st_size)
                        log(f"  ⊘ {sd_f.name}", 'warn')
                        self.after(0, lambda sd_f=sd_f, sz=sz:
                                   self._tree.insert('', 'end',
                                       values=(sd_f.name, sz,
                                               '— hash search skipped —',
                                               'SKIPPED'),
                                       tags=('unmatched',)))
                    # Jump straight to summary with what we have
                    self._prog_var.set(100)
                    log("─"*60, 'dim')
                    log(f"Scan complete — {matched} confirmed, "
                        f"{len(fallback_sd)} skipped/not found.", 'orange')
                    self._status_var.set(
                        f"Done: {matched} confirmed, {len(fallback_sd)} unresolved.")
                    if matched > 0:
                        self.after(0, lambda: self._del_btn.configure(state='normal'))
                        log(f"Ready to delete {matched} confirmed file(s) from SD card.", 'orange')
                    else:
                        log("Nothing to delete.", 'warn')
                    return   # skip Phase 4 entirely

                log(f"Phase 4 — {len(fallback_sd)} file(s) need full server hash index…", 'dim')

                log(f"  Hashing {len(server_to_index)} remaining server file(s) "
                    f"(cache-accelerated)…", 'dim')

                server_hash_index: dict = {}   # hash → Path
                srv_done = [0]
                cache_hits = [0]

                def index_server_file(sf: Path):
                    if self._cancel_requested:
                        return
                    try:
                        key = str(sf)
                        st  = sf.stat()
                        entry = cache.get(key)
                        cached = (entry and
                                  entry.get('size') == st.st_size and
                                  abs(entry.get('mtime', 0) - st.st_mtime) < 1.0)
                        if cached:
                            h = entry['hash']
                            with lock:
                                cache_hits[0] += 1
                        else:
                            h = sha256_file(sf)
                            with lock:
                                cache[key] = {'hash': h,
                                              'size': st.st_size,
                                              'mtime': st.st_mtime}
                        with lock:
                            server_hash_index[h] = sf
                            srv_done[0] += 1
                            n = srv_done[0]
                        total = len(server_to_index)
                        self._prog_var.set(40 + n / max(total, 1) * 40)
                        self._status_var.set(
                            f"Indexing server {n}/{total}: {sf.name}"
                            + (" [cached]" if cached else ""))
                    except Exception as e:
                        log(f"  ⚠  Could not hash server file {sf.name}: {e}", 'warn')

                with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
                    list(pool.map(index_server_file, server_to_index))

                _save_cache(cache)
                fresh4 = len(server_to_index) - cache_hits[0]
                log(f"  Server index built — {cache_hits[0]} cached, {fresh4} freshly hashed.", 'dim')

                if cancelled(): return

                # Now check each fallback SD file against the full index
                fb_done = [0]
                log(f"  Checking {len(fallback_sd)} SD file(s) against full index…", 'dim')

                def check_fallback(sd_f: Path):
                    if self._cancel_requested:
                        return
                    nonlocal matched, unmatched
                    try:
                        # Reuse hash if already computed in phase 3
                        h = precomputed.get(sd_f) or sha256_file(sd_f)
                        sz = self._fmt_size(sd_f.stat().st_size)
                        with lock:
                            fb_done[0] += 1
                            n = fb_done[0]
                        self._prog_var.set(80 + n / max(len(fallback_sd), 1) * 20)
                        self._status_var.set(f"Fallback check {n}/{len(fallback_sd)}: {sd_f.name}")

                        if h in server_hash_index:
                            srv_f = server_hash_index[h]
                            rel   = str(srv_f.relative_to(srv_p))
                            with match_lock:
                                self._matches.append((sd_f, srv_f, h))
                                matched += 1
                                if sd_f in [p[0] for p in self._hash_failed_pairs]:
                                    pass  # was already counted as unmatched tentatively
                                else:
                                    pass
                            self.after(0, lambda sd_f=sd_f, sz=sz, rel=rel:
                                       self._tree.insert('', 'end',
                                           values=(sd_f.name, sz, rel, '✓ Hash match'),
                                           tags=('matched',)))
                            log(f"  ✓ {sd_f.name}  →  {rel}  (found by hash)", 'ok')
                        else:
                            with match_lock:
                                unmatched += 1
                            self.after(0, lambda sd_f=sd_f, sz=sz:
                                       self._tree.insert('', 'end',
                                           values=(sd_f.name, sz,
                                                   '— not found on server —',
                                                   'NOT FOUND'),
                                           tags=('unmatched',)))
                    except Exception as e:
                        log(f"  ✗ Error in fallback check {sd_f.name}: {e}", 'error')

                with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
                    list(pool.map(check_fallback, fallback_sd))
            else:
                log("Phase 4 — Skipped (all files resolved by name+hash).", 'dim')
                self._prog_var.set(100)

            # ══════════════════════════════════════════════════════════════════
            # Summary
            # ══════════════════════════════════════════════════════════════════
            self._prog_var.set(100)
            log("─"*60, 'dim')
            log(f"Scan complete — {matched} confirmed on server, "
                f"{unmatched} not found.", 'orange')
            self._status_var.set(
                f"Done: {matched} confirmed, {unmatched} not on server.")

            if matched > 0:
                self.after(0, lambda: self._del_btn.configure(state='normal'))
                log(f"Ready to delete {matched} confirmed file(s) from SD card.", 'orange')
            else:
                log("Nothing to delete — no SD files confirmed on server.", 'warn')

        except Exception as e:
            import traceback
            log(f"\n✗ Unexpected error: {e}", 'error')
            log(traceback.format_exc(), 'error')
            self._status_var.set("Error — see log.")
        finally:
            self._running = False
            self._cancel_requested = False
            self.after(0, lambda: self._scan_btn.configure(
                state='normal', text="🔍  SCAN"))
            self.after(0, lambda: self._cancel_btn.configure(
                state='disabled', text="✕  CANCEL"))

    # ── Delete ────────────────────────────────────────────────────────────────

    def _confirm_delete(self):
        n = len(self._matches)
        if n == 0:
            messagebox.showinfo("Nothing to Delete", "No matched files to delete.")
            return
        ans = messagebox.askyesno(
            "Confirm Safe Delete",
            f"This will permanently delete {n} file(s) from the SD card.\n\n"
            "Each file has been confirmed to exist on the server by SHA256 hash.\n\n"
            "Proceed?",
            icon='warning')
        if ans:
            self._run_delete()

    def _run_delete(self):
        log = self.log
        log("─"*60, 'dim')
        log(f"Deleting {len(self._matches)} confirmed file(s) from SD card…", 'orange')

        deleted = 0
        errors  = 0
        # Update tree rows to show deletion status
        tree_items = self._tree.get_children()
        matched_items = [item for item in tree_items
                         if self._tree.item(item)['tags'] == ('matched',)]

        for idx, (sd_file, server_file, _) in enumerate(self._matches):
            try:
                sd_file.unlink()
                log(f"  🗑  Deleted: {sd_file.name}", 'ok')
                if idx < len(matched_items):
                    self._tree.item(matched_items[idx],
                                    values=(sd_file.name,
                                            self._fmt_size(server_file.stat().st_size)
                                            if server_file.exists() else '—',
                                            str(server_file),
                                            '🗑 Deleted'),
                                    tags=('deleted',))
                deleted += 1
            except Exception as e:
                log(f"  ✗ Could not delete {sd_file.name}: {e}", 'error')
                errors += 1

        self._matches.clear()
        self._del_btn.configure(state='disabled')
        log("─"*60, 'dim')
        log(f"Done — {deleted} deleted, {errors} error(s).", 'orange' if not errors else 'warn')
        self._status_var.set(f"Safe Delete complete: {deleted} removed, {errors} errors.")

    @staticmethod
    def _fmt_size(n: int) -> str:
        for unit in ('B','KB','MB','GB'):
            if n < 1024: return f"{n:.0f} {unit}"
            n /= 1024
        return f"{n:.1f} TB"


# ══════════════════════════════════════════════════════════════════════════════
# Main App Window
# ══════════════════════════════════════════════════════════════════════════════

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Camera Ingest")
        self.geometry("960x820")
        self.minsize(780, 640)
        self.configure(bg=BG)
        self._build()
        self._check_deps()

    def _build(self):
        # Header
        hdr = tk.Frame(self, bg=BG, pady=16)
        hdr.pack(fill='x', padx=28)
        tk.Label(hdr, text="CAMERA INGEST", font=TITLE, bg=BG, fg=TEXT).pack(side='left')
        tk.Label(hdr, text="SD → USB + Server  |  Safe Delete",
                 font=SUB, bg=BG, fg=DIM).pack(side='left', padx=(14,0), pady=(6,0))

        tk.Frame(self, bg=BLUE, height=2).pack(fill='x')

        # Notebook
        style = ttk.Style()
        style.theme_use('default')
        style.configure("App.TNotebook",
                        background=BG, borderwidth=0, tabmargins=0)
        style.configure("App.TNotebook.Tab",
                        background=PANEL, foreground=DIM,
                        font=LABEL, padding=[20, 8],
                        borderwidth=0)
        style.map("App.TNotebook.Tab",
                  background=[('selected', BG)],
                  foreground=[('selected', TEXT)])

        nb = ttk.Notebook(self, style="App.TNotebook")
        nb.pack(fill='both', expand=True)

        self._ingest_tab = IngestTab(nb)
        self._safe_tab   = SafeDeleteTab(nb)

        nb.add(self._ingest_tab, text="  ▶  Ingest  ")
        nb.add(self._safe_tab,   text="  🛡  Safe Delete  ")

    def _check_deps(self):
        log = self._ingest_tab.log
        if not PILLOW_AVAILABLE:
            log("⚠  Pillow not installed — EXIF photo timestamps unavailable.", 'warn')
            log("   pip install Pillow", 'dim')
        if not HACHOIR_AVAILABLE:
            log("⚠  hachoir not installed — video metadata timestamps unavailable.", 'warn')
            log("   pip install hachoir", 'dim')
        if not PILLOW_AVAILABLE or not HACHOIR_AVAILABLE:
            log("   Filesystem timestamps will be used as fallback.", 'dim')
            log("─"*60, 'dim')


if __name__ == '__main__':
    App().mainloop()
