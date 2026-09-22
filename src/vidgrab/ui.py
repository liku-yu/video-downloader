"""终端界面：彩色输出、进度渲染、交互菜单。"""

from __future__ import annotations

import os
import shutil
import sys
import threading
from typing import Callable, Optional, Sequence


# ---------------------------------------------------------------- Windows 控制台

def _enable_windows_vt() -> bool:
    """开启 Windows 控制台的 ANSI 转义支持。

    传统 cmd.exe 默认不解析 ANSI 序列，不开启的话彩色输出会显示成
    `←[32m` 之类的乱码，进度条也无法原地刷新。
    """
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.GetStdHandle(-11)          # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


_VT_READY = _enable_windows_vt()
_ASCII = bool(os.environ.get("VIDGRAB_ASCII"))


def set_ascii(on: bool) -> None:
    """切换到纯 ASCII 显示（老终端或字体缺字时用）。"""
    global _ASCII
    _ASCII = on


def ascii_mode() -> bool:
    return _ASCII


def _s(uni: str, ascii_: str) -> str:
    return ascii_ if _ASCII else uni


# ---------------------------------------------------------------- 颜色

def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return _VT_READY
    if os.name == "nt":
        return bool(_VT_READY and sys.stdout.isatty())
    return sys.stdout.isatty()


_COLOR = _supports_color()


def set_color(on: bool) -> None:
    global _COLOR
    _COLOR = on


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def green(t: str) -> str:  return _c("32", t)
def red(t: str) -> str:    return _c("31", t)
def yellow(t: str) -> str: return _c("33", t)
def blue(t: str) -> str:   return _c("36", t)
def bold(t: str) -> str:   return _c("1", t)
def dim(t: str) -> str:    return _c("2", t)


_print_lock = threading.Lock()


class _noop_lock:
    def __enter__(self): return self
    def __exit__(self, *a): return False


def say(msg: str = "", *, err: bool = False, lock: bool = True) -> None:
    stream = sys.stderr if err else sys.stdout
    with (_print_lock if lock else _noop_lock()):
        print(msg, file=stream, flush=True)


def ok(msg: str) -> None:   say(f"{green(_s('✓', 'OK'))} {msg}")
def warn(msg: str) -> None: say(f"{yellow(_s('!', '!'))} {msg}")
def fail(msg: str) -> None: say(f"{red(_s('✗', 'x'))} {msg}", err=True)
def info(msg: str) -> None: say(f"{blue(_s('·', '-'))} {msg}")


def rule(title: str = "", width: int = 64) -> None:
    if title:
        pad = max(min(width, _console_width()) - len(title) - 3, 2)
        say(bold(f"{_s('──', '--')} {title} " + _s("─", "-") * pad))
    else:
        say(bold(_s("─", "-") * min(width, _console_width())))


BANNER = r"""
 __     ___ ____  ____ ____      _    ____
 \ \   / (_)  _ \|  _ \ ___|    / \  | __ )
  \ \ / /| | | | | | | |_ |    / _ \ |  _ \
   \ V / | | |_| | |_| |/ /   / ___ \| |_) |
    \_/  |_|____/|____//___| /_/   \_\____/
"""


def banner(sites: Optional[int] = None) -> None:
    say(blue(BANNER.strip("\n")))
    sub = "跨平台视频下载器 · yt-dlp 内核"
    if sites:
        sub += f" · 已内置 {sites}+ 站点解析"
    say(dim("  " + sub))
    say()


# ---------------------------------------------------------------- 进度

def _console_width(default: int = 100) -> int:
    try:
        return shutil.get_terminal_size((default, 25)).columns
    except Exception:
        return default


def human_size(n: Optional[float]) -> str:
    if not n:
        return "?"
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    i = 0
    n = float(n)
    while n >= 1024 and i < len(units) - 1:
        n /= 1024.0
        i += 1
    return f"{n:.1f}{units[i]}"


def human_time(sec: Optional[float]) -> str:
    if sec is None:
        return "--:--"
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class ProgressPrinter:
    """渲染 yt-dlp 的进度数据。

    单个文件的进度行形如：

        [2/5] [████████░░░░░░░░]  52.3%  2.1MiB/4.0MiB  3.4MiB/s  ETA 00:01  | 总 24.6%

    - 终端（TTY）：用 \\r 原地刷新
    - 重定向到文件/管道：按 10% 分档节流输出，避免刷屏
    - overall 回调返回 (已完成任务数, 总任务数)，用于计算整批下载的总百分比
    """

    BUCKET = 10
    BAR_WIDTH = 24

    def __init__(self, prefix: str = "", enabled: bool = True,
                 overall: Optional[Callable[[], tuple[int, int]]] = None):
        self.prefix = prefix
        self.enabled = enabled
        self.tty = sys.stdout.isatty()
        self.bar_width = self.BAR_WIDTH
        self.overall = overall
        self._line_len = 0
        self._lock = threading.Lock()
        self._buckets: dict[str, int] = {}
        self._overall_peak = 0.0

    # ---- 总进度
    def overall_text(self, file_pct: float) -> str:
        if not self.overall:
            return ""
        try:
            done, total = self.overall()
        except Exception:
            return ""
        if total <= 1:
            return ""
        file_pct = max(0.0, min(file_pct, 100.0))
        pct = (done + file_pct / 100.0) / total * 100.0
        # 同一任务会有多条流（视频/音频分别下载），进度会重新计数，
        # 这里取历史峰值，保证「总进度」只增不减。
        if pct < self._overall_peak:
            pct = self._overall_peak
        else:
            self._overall_peak = pct
        return f"  {_s('│', '|')} 总 {pct:5.1f}%"

    # ---- 进度条
    def _bar(self, pct: float) -> str:
        if not self.bar_width:
            return ""
        filled = int(self.bar_width * pct / 100)
        return "[" + _s("█", "#") * filled + _s("░", "-") * (self.bar_width - filled) + "] "

    def update(self, d: dict) -> None:
        if not self.enabled:
            return
        status = d.get("status")
        if status == "finished":
            self._buckets.clear()
            self._render(f"100.0%  合并/转码中…{self.overall_text(100.0)}", final=True)
            return
        if status != "downloading":
            return

        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        done = d.get("downloaded_bytes") or 0
        pct = (done / total * 100) if total else 0.0

        if not self.tty:  # 节流：同一文件只在跨越 10% 档位时输出
            key = d.get("filename") or d.get("_filename") or "stream"
            bucket = int(pct // self.BUCKET)
            if self._buckets.get(key) == bucket:
                return
            self._buckets[key] = bucket

        text = (f"{self._bar(pct)}{pct:5.1f}%  {human_size(done)}/{human_size(total)}  "
                f"{human_size(d.get('speed'))}/s  ETA {human_time(d.get('eta'))}")
        if total:
            text += self.overall_text(pct)
        self._render(text)

    def _render(self, text: str, final: bool = False) -> None:
        line = f"{self.prefix}{text}"
        maxw = _console_width() - 1
        if maxw > 20 and len(line) > maxw:      # 防止换行破坏 \r 原地刷新
            line = line[:maxw]
        with self._lock:
            if self.tty:
                pad = max(self._line_len - len(line), 0)
                sys.stdout.write("\r" + line + " " * pad)
                sys.stdout.flush()
                self._line_len = 0 if final else len(line)
                if final:
                    sys.stdout.write("\n")
                    sys.stdout.flush()
            else:
                print(line, flush=True)


# ---------------------------------------------------------------- 菜单

def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"{bold(prompt)}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise
    return val or default


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    d = "Y/n" if default else "y/N"
    val = ask(f"{prompt} ({d})").lower()
    if not val:
        return default
    return val in ("y", "yes", "是", "1", "true")


def choose(prompt: str, options: Sequence[tuple[str, str]], default: int = 1,
           quit_token: Optional[str] = None) -> str:
    """options: [(值, 说明), ...]，返回被选中的值。

    传入 quit_token 时，输入 0 / q / quit / exit 会直接返回该标识（用于取消/退出）。
    """
    say()
    for i, (_, label) in enumerate(options, 1):
        mark = green(_s("▸", ">")) if i == default else " "
        say(f"  {mark} {bold(str(i))}. {label}")
    if quit_token:
        say(f"    {dim(_s('（输入 0 或 q 可退出 / 取消，不下载任何内容）',
                          '(0 or q to quit/cancel)'))}")
    while True:
        raw = ask(prompt, str(default)).strip().lower()
        if quit_token and raw in ("0", "q", "quit", "exit", "退出", "取消"):
            return quit_token
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        fail("请输入列表中的编号（或 0 / q 退出）")


def clear() -> None:
    if sys.stdout.isatty():
        os.system("cls" if os.name == "nt" else "clear")


def terminal_width(default: int = 64) -> int:
    return shutil.get_terminal_size((default, 24)).columns
