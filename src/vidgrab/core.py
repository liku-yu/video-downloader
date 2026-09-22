"""下载核心：把 Settings 翻译成 yt-dlp 选项，并执行批量下载。"""

from __future__ import annotations

import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from . import ui
from .config import AUDIO_CODECS, QUALITY_FORMATS, Settings

try:  # 延迟到运行时才强制要求依赖
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError
    YT_DLP_AVAILABLE = True
except ImportError:  # pragma: no cover
    YoutubeDL = None  # type: ignore
    DownloadError = Exception  # type: ignore
    YT_DLP_AVAILABLE = False


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def parse_impersonate(value: str):
    """yt-dlp 的 Python API 要求 ImpersonateTarget 对象，命令行才接受字符串。"""
    try:
        from yt_dlp.networking.impersonate import ImpersonateTarget

        return ImpersonateTarget.from_str(value)
    except Exception:
        return value


# ---------------------------------------------------------------- ffmpeg

def detect_ffmpeg(explicit: Optional[str] = None) -> Optional[str]:
    """按 显式路径 -> PATH -> imageio-ffmpeg 内置二进制 的顺序定位 ffmpeg。"""
    if explicit:
        p = Path(explicit).expanduser()
        if p.exists():
            return str(p)
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:  # 可选依赖：自带 ffmpeg 二进制
        import imageio_ffmpeg  # type: ignore

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).exists():
            return exe
    except Exception:
        pass
    return None


def ffmpeg_hint() -> str:
    return (
        "未找到 ffmpeg，高清视频/音频的合并与转码会受限。\n"
        "  安装方式任选其一：\n"
        "    · 本项目已带内置版：uv sync --extra ffmpeg\n"
        "    · Windows: winget install Gyan.FFmpeg\n"
        "    · macOS:   brew install ffmpeg\n"
        "    · Debian/Kali: sudo apt install ffmpeg"
    )


# ---------------------------------------------------------------- 结果对象

@dataclass
class TaskResult:
    url: str
    ok: bool = False
    partial: bool = False          # 播放列表里部分条目成功
    skipped: bool = False
    title: str = ""
    filepath: str = ""
    error: str = ""


@dataclass
class BatchSummary:
    results: list[TaskResult] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    elapsed: float = 0.0

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if not r.ok)

    @property
    def partial_count(self) -> int:
        return sum(1 for r in self.results if r.ok and r.partial)

    @property
    def total(self) -> int:
        return len(self.results)


# ---------------------------------------------------------------- 日志适配

class _Logger:
    """把 yt-dlp 的输出接到我们的 UI 上。"""

    def __init__(self, verbose: bool = False, quiet: bool = False, prefix: str = "",
                 lock: Optional[threading.Lock] = None,
                 sink: Optional[dict[str, Any]] = None):
        self.verbose = verbose
        self.quiet = quiet
        self.prefix = prefix
        self.lock = lock or threading.Lock()
        self.sink = sink if sink is not None else {}

    def debug(self, msg: str) -> None:
        if not self.verbose or self.quiet:
            return
        if msg.startswith("[debug] "):
            return
        with self.lock:
            ui.say(f"  {ui.dim(msg)}", lock=False)

    def info(self, msg: str) -> None:
        return

    def warning(self, msg: str) -> None:
        if self.quiet:
            return
        with self.lock:
            ui.say(f"  {ui.yellow('!')} {msg}", lock=False)

    def error(self, msg: str) -> None:
        # yt-dlp 在 ignoreerrors=True 时不会抛异常，错误只从这里出来，
        # 因此必须记录下来，否则失败任务会被误判为成功。
        self.sink.setdefault("errors", []).append(msg)
        with self.lock:
            ui.say(f"{self.prefix}  {ui.red('✗')} {msg}", err=True, lock=False)


class _SilentLogger:
    """什么都不输出的 logger，用于内部探测/搜索重试。"""

    def debug(self, msg: str) -> None: return
    def info(self, msg: str) -> None: return
    def warning(self, msg: str) -> None: return
    def error(self, msg: str) -> None: return


# ---------------------------------------------------------------- Downloader

class Downloader:
    def __init__(self, settings: Settings, *, show_progress: bool = True):
        self.s = settings
        self.show_progress = show_progress
        self.ffmpeg = detect_ffmpeg(settings.ffmpeg_location)
        self._lock = threading.Lock()
        # 整批下载的状态，供进度条显示「总 xx%」
        self._batch = {"done": 0, "total": 0}

    def _overall(self) -> tuple[int, int]:
        return self._batch["done"], self._batch["total"]

    # -------------------------------------------------- 选项构造

    def _outtmpl(self) -> str:
        name = self.s.template
        if self.s.subdir_by_uploader:
            name = "%(uploader,channel,creator|未知作者)s/" + name
        return str(Path(self.s.output_dir).expanduser() / name)

    def _format_selector(self) -> str:
        if self.s.audio_only:
            return "ba/b"
        return QUALITY_FORMATS.get(self.s.quality, QUALITY_FORMATS["best"])

    def build_opts(self, progress_hook: Optional[Callable[[dict], None]] = None,
                   pp_hook: Optional[Callable[[dict], None]] = None,
                   logger: Optional[_Logger] = None) -> dict[str, Any]:
        s = self.s
        opts: dict[str, Any] = {
            "outtmpl": self._outtmpl(),
            "format": self._format_selector(),
            "noplaylist": not s.playlist,
            "ignoreerrors": True,
            "retries": s.retries,
            "fragment_retries": s.retries,
            "concurrent_fragment_downloads": max(1, s.concurrent_fragments),
            "continuedl": True,
            "nooverwrites": s.no_overwrite,
            "noprogress": True,            # 我们自渲染进度
            "quiet": True,
            "no_warnings": s.quiet,
            "nocheckcertificate": True,
            "windowsfilenames": True,
            "trim_file_name": 180,
            "logger": logger or _Logger(verbose=s.verbose, quiet=s.quiet),
        }

        if s.playlist_limit:
            opts["playlistend"] = s.playlist_limit
        if s.rate_limit:
            opts["ratelimit"] = s.rate_limit
        if s.proxy:
            opts["proxy"] = s.proxy
        if s.sleep_interval:
            opts["sleep_interval"] = s.sleep_interval
        if s.cookies:
            opts["cookiefile"] = str(Path(s.cookies).expanduser())
        if s.cookies_from_browser:
            browser = s.cookies_from_browser
            opts["cookiesfrombrowser"] = (
                tuple(browser.split("+")) if "+" in browser else (browser,)
            )
        if s.username:
            opts["username"] = s.username
        if s.password:
            opts["password"] = s.password
        if s.impersonate:
            opts["impersonate"] = parse_impersonate(s.impersonate)
        if self.ffmpeg and self.ffmpeg != shutil.which("ffmpeg"):
            opts["ffmpeg_location"] = self.ffmpeg
        if s.archive:
            Path(s.output_dir).expanduser().mkdir(parents=True, exist_ok=True)
            opts["download_archive"] = str(
                Path(s.output_dir).expanduser() / ".vidgrab-archive.txt"
            )

        # ---- 字幕
        if s.subtitles:
            opts.update(
                writesubtitles=True,
                writeautomaticsub=True,
                subtitleslangs=[x.strip() for x in s.subtitle_langs.split(",") if x.strip()],
                subtitlesformat="srt/best",
            )
            if s.embed_subs:
                opts["embedsubtitles"] = True

        # ---- 元数据
        if s.embed_thumbnail:
            opts["writethumbnail"] = True
        if s.write_thumbnail:
            opts["writethumbnail"] = True
        if s.write_info_json:
            opts["writeinfojson"] = True

        # ---- 后处理器
        pps: list[dict[str, Any]] = []
        if s.audio_only:
            pps.append({
                "key": "FFmpegExtractAudio",
                "preferredcodec": AUDIO_CODECS.get(s.audio_format, "mp3"),
                "preferredquality": s.audio_quality,
            })
        if s.embed_metadata:
            pps.append({"key": "FFmpegMetadata", "add_metadata": True})
        if s.embed_thumbnail:
            pps.append({"key": "EmbedThumbnail", "already_have_thumbnail": False})
        if s.embed_subs:
            pps.append({"key": "FFmpegEmbedSubtitle", "already_have_subtitle": False})
        if s.sponsorblock:
            pps.append({"key": "SponsorBlock", "categories": ["sponsor", "selfpromo", "intro", "outro"],
                        "when": "after_filter"})
            pps.append({"key": "ModifyChapters", "remove_sponsor_segments":
                        ["sponsor", "selfpromo", "intro", "outro"]})
        if pps:
            opts["postprocessors"] = pps

        if progress_hook:
            opts["progress_hooks"] = [progress_hook]
        if pp_hook:
            opts["postprocessor_hooks"] = [pp_hook]
        return opts

    # -------------------------------------------------- 单个任务

    def _make_hooks(self, prefix: str, sink: dict[str, Any]):
        printer = ui.ProgressPrinter(prefix=prefix,
                                     enabled=self.show_progress and self.s.jobs == 1,
                                     overall=self._overall)

        def on_progress(d: dict) -> None:
            if d.get("status") == "finished":
                sink["finished"] = sink.get("finished", 0) + 1
            info = d.get("info_dict") or {}
            if info.get("title") and not sink.get("title"):
                sink["title"] = info["title"]
            printer.update(d)

        def on_pp(d: dict) -> None:
            if d.get("status") == "finished":
                fp = d.get("filepath") or (d.get("info_dict") or {}).get("filepath")
                if fp:
                    sink["filepath"] = fp

        return on_progress, on_pp, printer

    def _cleanup_thumbnails(self, filepath: str) -> None:
        """嵌图完成后删掉残留的缩略图文件。"""
        if not filepath or self.s.write_thumbnail:
            return
        stem = Path(filepath).with_suffix("")
        for ext in IMAGE_EXTS:
            p = stem.with_suffix(ext)
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass

    def _download_one(self, url: str, index: int, total: int) -> TaskResult:
        prefix = f"[{index}/{total}] " if total > 1 else ""
        res = TaskResult(url=url)
        sink: dict[str, Any] = {}
        on_progress, on_pp, printer = self._make_hooks(prefix, sink)
        logger = _Logger(verbose=self.s.verbose, quiet=self.s.quiet, prefix=prefix,
                         lock=self._lock, sink=sink)
        opts = self.build_opts(on_progress, on_pp, logger)

        if not self.s.quiet and self.s.jobs > 1:
            with self._lock:
                ui.say(f"{prefix}{ui.dim('开始：')}{url}")

        retcode = 0
        try:
            with YoutubeDL(opts) as ydl:
                retcode = ydl.download([url]) or 0
        except DownloadError as exc:
            res.error = str(exc).strip() or "下载失败"
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001
            res.error = f"{type(exc).__name__}: {exc}"

        res.title = sink.get("title", "")
        res.filepath = sink.get("filepath", "")
        errors: list[str] = sink.get("errors") or []
        finished: int = sink.get("finished", 0)

        if res.error:
            res.ok = False
        elif retcode != 0 or errors:
            first = (errors[0].splitlines()[0].strip() if errors else "")
            if finished > 0:                      # 列表里部分成功
                res.ok, res.partial = True, True
                res.error = first or "部分条目下载失败"
            else:                                 # 整体失败
                res.ok = False
                res.error = first or "下载失败（原因未明，可加 -v 查看详情）"
        else:
            res.ok = True

        self._cleanup_thumbnails(res.filepath)
        self._batch["done"] += 1

        if not self.s.quiet:
            shown = res.title or url
            overall = printer.overall_text(0.0)  # done 已递增，此处不再叠加当前文件进度
            with self._lock:
                if res.ok and res.partial:
                    ui.say(f"{prefix}{ui.yellow(ui._s('⚠', '!'))} {shown}"
                           f"  {ui.dim('（部分条目失败）')}{ui.dim(overall)}")
                elif res.ok:
                    ui.say(f"{prefix}{ui.green(ui._s('✓', 'OK'))} {shown}{ui.dim(overall)}")
                if res.ok and res.filepath:
                    ui.say(f"{prefix}  {ui.dim(ui._s('→', '->') + ' ' + res.filepath)}")
        return res

    # -------------------------------------------------- 批量

    def download(self, urls: Iterable[str]) -> BatchSummary:
        url_list = [u.strip() for u in urls if u and u.strip() and not u.strip().startswith("#")]
        summary = BatchSummary()
        if not url_list:
            return summary

        self._batch["done"] = 0
        self._batch["total"] = len(url_list)
        if not self.s.quiet:
            ui.say()
            ui.rule(f"开始下载 {len(url_list)} 个任务")
            ui.info(f"输出目录：{Path(self.s.output_dir).expanduser()}")
            ui.info(f"画质：{'仅音频 ' + self.s.audio_format if self.s.audio_only else self.s.quality}")
            ui.say()

        jobs = max(1, min(self.s.jobs, len(url_list)))
        try:
            if jobs == 1:
                for i, url in enumerate(url_list, 1):
                    summary.results.append(self._download_one(url, i, len(url_list)))
            else:
                with ThreadPoolExecutor(max_workers=jobs) as pool:
                    futures = {
                        pool.submit(self._download_one, u, i, len(url_list)): u
                        for i, u in enumerate(url_list, 1)
                    }
                    for fut in futures:
                        summary.results.append(fut.result())
        except KeyboardInterrupt:
            ui.say()
            ui.warn("已被用户中断（Ctrl+C），已完成的文件不受影响")

        summary.elapsed = time.time() - summary.started_at
        return summary

    # -------------------------------------------------- 关键词搜索

    def search(self, query: str, limit: int = 10, *, fill_titles: bool = True,
               attempts: int = 3) -> list[dict[str, Any]]:
        """关键词搜索，返回候选条目。

        query 形如 "bilisearch10:关键词" / "ytsearch5:keyword"。

        两个要点：

        1. **flat 优先**：先用 flat 模式一次请求拿到列表，再对缺标题的条目
           小并发补全。某些平台的 flat 搜索只返回 id（如 B 站），不补的话
           列表里只有一串 av 号；而直接非 flat 搜索会因连续快速请求被风控。
        2. **带退避的重试**：B 站等平台的搜索接口是**概率性风控**——
           实测相同参数连续请求成功率约 4/6，会间歇性返回 HTTP 412。
           因此这里失败后自动等待重试，而不是直接报错。
        """
        info = None
        last_exc: Optional[Exception] = None
        for attempt in range(1, max(1, attempts) + 1):
            opts = self.build_opts(logger=_SilentLogger())
            opts.update(quiet=True, skip_download=True, ignoreerrors=False,
                        retries=1, extract_flat="in_playlist",
                        playlistend=max(1, limit))
            try:
                with YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(query, download=False)
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < attempts:
                    time.sleep(1.5 * attempt)      # 1.5s / 3s 退避
        if info is None:
            raise last_exc or RuntimeError("搜索失败")

        entries = [e for e in ((info or {}).get("entries") or []) if e]
        if not entries or not fill_titles:
            return entries

        missing = [e for e in entries if not e.get("title")]
        if missing:
            with ThreadPoolExecutor(max_workers=min(4, len(missing))) as pool:
                pool.map(self._fill_entry, missing)
        return entries

    def _fill_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        """补全单条搜索结果的标题/时长等信息；失败就保持原样（不报错）。"""
        url = entry.get("url") or entry.get("webpage_url")
        if not url or entry.get("title"):
            return entry
        try:
            opts = self.build_opts(logger=_SilentLogger())
            opts.update(quiet=True, skip_download=True, noplaylist=True,
                        ignoreerrors=False, retries=1)
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False) or {}
            for key in ("title", "uploader", "channel", "creator", "duration",
                        "duration_string", "view_count", "webpage_url"):
                if info.get(key) and not entry.get(key):
                    entry[key] = info[key]
        except Exception:
            pass
        return entry

    # -------------------------------------------------- 只取信息

    def probe(self, url: str) -> dict[str, Any]:
        opts = self.build_opts()
        opts.update(quiet=True, skip_download=True, noplaylist=True)
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if info and info.get("entries"):
            info = list(info["entries"])[0]
        return info or {}


def print_probe(info: dict[str, Any]) -> None:
    """把 extract_info 的结果打印成人能看的格式。"""
    ui.rule("链接信息")
    fields = [
        ("标题", info.get("title")),
        ("作者", info.get("uploader") or info.get("channel") or info.get("creator")),
        ("时长", ui.human_time(info.get("duration"))),
        ("发布日期", (info.get("upload_date") or "")[:8]),
        ("播放量", info.get("view_count")),
        ("站点", info.get("extractor_key") or info.get("extractor")),
        ("描述", (info.get("description") or "")[:300].replace("\n", " ")),
    ]
    for k, v in fields:
        if v not in (None, "", "?"):
            ui.say(f"  {ui.bold(k)}: {v}")

    entries = info.get("entries")
    if entries:
        entries = list(entries)
        ui.say(f"  {ui.bold('播放列表')}: 共 {len(entries)} 个条目")
        for i, e in enumerate(entries[:15], 1):
            if e:
                ui.say(f"    {i:>3}. {e.get('title')}")
        if len(entries) > 15:
            ui.say(f"    … 其余 {len(entries) - 15} 个省略")
        return

    fmts = info.get("formats") or []
    if fmts:
        ui.say()
        ui.say(f"  {ui.bold('可用格式')}（共 {len(fmts)} 种，仅列前 20）:")
        rows = [f for f in fmts if f.get("vcodec") != "none" or f.get("acodec") != "none"]
        for f in rows[-20:][::-1]:
            rid = f.get("format_id", "?")
            ext = f.get("ext", "?")
            res = f.get("resolution") or f"{f.get('width')}x{f.get('height')}"
            fps = f.get("fps")
            vcodec = (f.get("vcodec") or "none").split(".")[0]
            acodec = (f.get("acodec") or "none").split(".")[0]
            size = ui.human_size(f.get("filesize") or f.get("filesize_approx"))
            note = " (仅视频)" if acodec == "none" else (" (仅音频)" if vcodec == "none" else "")
            ui.say(f"    [{rid:>6}] {ext:<5} {str(res):<12} {fps or '':<4} "
                   f"{vcodec}/{acodec}{note}  {size}")
    ui.rule()
