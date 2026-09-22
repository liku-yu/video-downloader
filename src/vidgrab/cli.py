"""命令行入口 + 交互式菜单。"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence

from . import __version__, ui
from .config import (APP_NAME, APP_TITLE, AUDIO_CODECS, DEFAULT_TEMPLATE,
                     QUALITY_FORMATS, SEARCH_NEEDS_IMPERSONATE,
                     SEARCH_PROVIDERS, Settings)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_URL_FILE = PROJECT_ROOT / "urls.txt"
SAMPLE_URLS = """# ============================================================
#  vidgrab 批量下载清单 —— 直接编辑本文件即可
# ------------------------------------------------------------
#  · 每行放一个链接，支持：视频 / 播放列表 / 频道主页 / 合集
#  · 以 # 开头的行为注释，空行会被忽略
#  · 编辑后保存（不用关程序），菜单里选「2」即可批量下载
# ============================================================
#
# 示例（把前面的 # 去掉，换成你自己的链接）：
# https://www.bilibili.com/video/BV1xx411c7mD
# https://www.youtube.com/watch?v=xxxxxxxxxxx
# https://www.douyin.com/video/7xxxxxxxxxxxxxxxxx
#
# 想给这批任务单独指定画质/保存目录？命令行更灵活，例如：
#   uv run python main.py -f urls.txt -q 1080p -o D:/Videos
# ------------------------------------------------------------
# ↓↓↓ 从下面这一行开始写你的链接 ↓↓↓
"""


# ---------------------------------------------------------------- 工具

def setup_console() -> None:
    """Windows 控制台强制 UTF-8，避免中文/符号乱码。"""
    if os.name == "nt":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
            except Exception:
                pass


def require_ytdlp() -> None:
    from .core import YT_DLP_AVAILABLE

    if not YT_DLP_AVAILABLE:
        ui.fail("缺少依赖 yt-dlp。请先执行：uv sync")
        raise SystemExit(2)


def count_sites() -> int:
    try:
        from yt_dlp.extractor import gen_extractor_classes

        return len(list(gen_extractor_classes()))
    except Exception:
        return 0


COMMON_SITES = [
    ("YouTube", "youtube.com / youtu.be"), ("哔哩哔哩", "bilibili.com / b23.tv"),
    ("抖音", "douyin.com"), ("快手", "kuaishou.com"), ("小红书", "xiaohongshu.com"),
    ("微博", "weibo.com"), ("腾讯视频", "v.qq.com"), ("优酷", "youku.com"),
    ("爱奇艺", "iqiyi.com"), ("西瓜视频", "ixigua.com"), ("知乎", "zhihu.com"),
    ("TikTok", "tiktok.com"), ("Twitter/X", "x.com / twitter.com"),
    ("Instagram", "instagram.com"), ("Facebook", "facebook.com"),
    ("Vimeo", "vimeo.com"), ("Twitch", "twitch.tv"), ("Dailymotion", "dailymotion.com"),
    ("Reddit", "reddit.com"), ("SoundCloud", "soundcloud.com"),
    ("Pinterest", "pinterest.com"), ("Tumblr", "tumblr.com"),
    ("VK", "vk.com"), ("Niconico", "nicovideo.jp"), ("Bilibili 番剧", "bangumi"),
]


def list_sites(verbose: bool = False) -> None:
    ui.rule("支持的站点")
    total = count_sites()
    ui.say(f"  yt-dlp 内核当前内置 {ui.bold(str(total))} 个站点解析器（extractor）。")
    ui.say()
    ui.say(f"  {ui.bold('常见平台：')}")
    for name, domain in COMMON_SITES:
        ui.say(f"    · {name:<12} {ui.dim(domain)}")
    ui.say()
    ui.say(f"  {ui.dim('完整列表：yt-dlp 官方 supported-sites 文档，或用 --list-sites --verbose 打印。')}")
    if verbose:
        try:
            from yt_dlp.extractor import gen_extractor_classes

            names = sorted(c.IE_NAME for c in gen_extractor_classes())
            ui.say()
            for i in range(0, len(names), 6):
                ui.say("    " + "  ".join(f"{n:<26}" for n in names[i:i + 6]).rstrip())
        except Exception as exc:  # noqa: BLE001
            ui.warn(f"无法枚举：{exc}")
    ui.rule()


def read_url_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    out: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def ensure_url_file(path: Path) -> Path:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(SAMPLE_URLS, encoding="utf-8")
    return path


def open_in_editor(path: Path) -> bool:
    """用系统编辑器打开文件，并**等待用户关闭**后再继续。

    Windows 用记事本（会一直占用进程直到窗口关闭）；
    macOS 用 TextEdit；Linux 优先 $EDITOR / $VISUAL。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("", encoding="utf-8")
    try:
        if os.name == "nt":
            return subprocess.call(["notepad.exe", str(path)]) == 0
        if sys.platform == "darwin":
            return subprocess.call(["open", "-t", "-W", str(path)]) == 0
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
        if editor:
            return subprocess.call([editor, str(path)]) == 0
        if shutil.which("xdg-open"):
            subprocess.call(["xdg-open", str(path)], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
            return True
    except Exception as exc:  # noqa: BLE001
        ui.warn(f"打开编辑器失败：{exc}")
    return False


def edit_and_download(s: Settings) -> None:
    """打开链接清单给用户编辑，保存关闭后按内容批量下载。"""
    path = ensure_url_file(DEFAULT_URL_FILE)
    ui.say()
    ui.info(f"链接清单：{path}")
    ui.info("即将打开编辑器 —— 把链接粘进去（每行一个），保存并关闭后会自动开始下载。")
    ui.say()

    if open_in_editor(path):
        ui.info("编辑器已关闭，读取清单…")
    else:
        ui.warn("没能自动打开编辑器，请手动编辑该文件")
        ui.ask("编辑完成后按回车继续")

    urls = read_url_file(path)
    if not urls:
        ui.warn("清单里还没有有效链接")
        ui.say(f"      {ui.dim('每行一个链接；以 # 开头的行是注释，不会被下载')}")
        return
    ui.info(f"读到 {len(urls)} 个链接")
    run_download(s, urls)


def open_folder(path: Path) -> None:
    p = str(path)
    try:
        if os.name == "nt":
            os.startfile(p)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", p])
        else:
            subprocess.Popen(["xdg-open", p],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:  # noqa: BLE001
        ui.warn(f"无法自动打开目录：{exc}")


JS_RUNTIMES = ("deno", "node", "bun", "qjs", "quickjs")


def js_runtime_missing() -> bool:
    return not any(shutil.which(x) for x in JS_RUNTIMES)


def split_urls(raw: str) -> list[str]:
    for ch in (",", "\n", "\t", "，"):
        raw = raw.replace(ch, " ")
    return [u for u in raw.split(" ") if u.strip()]


# ---------------------------------------------------------------- 参数

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=APP_NAME,
        description=f"{APP_TITLE} —— 支持 1800+ 站点的视频/音频/字幕下载",
        epilog=(
            "示例：\n"
            f"  {APP_NAME} https://www.bilibili.com/video/BVxxxx\n"
            f"  {APP_NAME} -q 1080p -o D:/Videos <链接1> <链接2>\n"
            f"  {APP_NAME} --audio --audio-format mp3 <链接>\n"
            f"  {APP_NAME} -f urls.txt --jobs 3\n"
            f"  {APP_NAME} -i <链接>          # 只看信息，不下载\n"
            f"  {APP_NAME} --search '关键词' --search-site bilibili --search-limit 5\n"
            f"  {APP_NAME}                    # 无参数时进入交互菜单\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("urls", nargs="*", help="一个或多个链接（也支持 @文件名 从文件读取）")

    g = p.add_argument_group("输出与画质")
    g.add_argument("-o", "--output", metavar="DIR", help="输出目录（默认 ~/Downloads/vidgrab）")
    g.add_argument("-q", "--quality", choices=list(QUALITY_FORMATS), default=None,
                   help="画质（默认 best 最高画质）")
    # 注意：帮助文本里的 % 必须转义为 %%，否则 argparse 会把它当格式化占位符
    g.add_argument("--template", metavar="TMPL",
                   help="文件名模板（yt-dlp 语法，默认 "
                        f"{DEFAULT_TEMPLATE.replace('%', '%%')}）")
    g.add_argument("--subdir", action="store_true", help="按作者/UP主建子目录")
    g.add_argument("--overwrite", action="store_true", help="覆盖已存在的文件（默认跳过）")

    g = p.add_argument_group("仅音频")
    g.add_argument("-a", "--audio", action="store_true", help="只下载音频")
    g.add_argument("--audio-format", choices=list(AUDIO_CODECS), default=None,
                   help="音频格式（默认 mp3）")
    g.add_argument("--audio-quality", default=None, metavar="0-10",
                   help="音频质量，0 最好 / 10 最小（默认 0）")

    g = p.add_argument_group("播放列表 / 批量")
    g.add_argument("-f", "--file", metavar="FILE", help="从文本文件批量读取链接")
    g.add_argument("--no-playlist", action="store_true", help="只下单个视频，忽略列表")
    g.add_argument("--playlist-limit", type=int, metavar="N", help="列表最多下载 N 个")
    g.add_argument("--jobs", type=int, metavar="N", help="同时下载的链接数（默认 1）")
    g.add_argument("--search", metavar="QUERY", help="按关键词搜索后下载")
    g.add_argument("--search-site", choices=list(SEARCH_PROVIDERS), default="youtube",
                   help="搜索平台（默认 youtube；国内推荐 bilibili）")
    g.add_argument("--search-limit", type=int, default=1, metavar="N",
                   help="取搜索结果的前 N 个（默认 1）")

    g = p.add_argument_group("字幕 / 元数据")
    g.add_argument("--subs", action="store_true", help="下载字幕")
    g.add_argument("--sub-langs", metavar="LANGS", help="字幕语言，逗号分隔（默认 zh-Hans,zh-CN,zh,en）")
    g.add_argument("--embed-subs", action="store_true", help="把字幕嵌入视频")
    g.add_argument("--write-thumbnail", action="store_true", help="保留封面图文件")
    g.add_argument("--no-thumbnail", action="store_true", help="不嵌入封面")
    g.add_argument("--no-metadata", action="store_true", help="不嵌入元数据")
    g.add_argument("--write-info-json", action="store_true", help="保存 .info.json")
    g.add_argument("--sponsorblock", action="store_true", help="用 SponsorBlock 去除赞助片段")

    g = p.add_argument_group("网络 / 认证")
    g.add_argument("--cookies", metavar="FILE", help="cookies.txt 文件路径")
    g.add_argument("--cookies-from-browser", metavar="BROWSER",
                   help="从浏览器读取 Cookie：chrome/edge/firefox/brave/safari（可写 chrome+Default）")
    g.add_argument("-u", "--username", help="账号")
    g.add_argument("-p", "--password", help="密码")
    g.add_argument("--proxy", metavar="URL", help="代理，如 http://127.0.0.1:7890")
    g.add_argument("--rate-limit", metavar="RATE", help="限速，如 2M / 500K")
    g.add_argument("--impersonate", metavar="TARGET", help="伪装指纹，如 chrome")
    g.add_argument("--sleep-interval", type=float, metavar="SEC", help="每个请求间隔秒数")
    g.add_argument("--concurrent-fragments", type=int, metavar="N", help="分片并发数（默认 4）")
    g.add_argument("--retries", type=int, metavar="N", help="失败重试次数（默认 10）")
    g.add_argument("--archive", action="store_true", help="记录已下载，避免重复下载")

    g = p.add_argument_group("其它")
    g.add_argument("-i", "--info", action="store_true", help="只查看链接信息与可用画质")
    g.add_argument("--list-sites", action="store_true", help="列出支持的站点")
    g.add_argument("--list-formats", action="store_true", help=argparse.SUPPRESS)
    g.add_argument("--dry-run", action="store_true", help="只打印将要使用的参数")
    g.add_argument("--ffmpeg-location", metavar="PATH", help="指定 ffmpeg 路径")
    g.add_argument("--no-color", action="store_true", help="关闭彩色输出")
    g.add_argument("--ascii", action="store_true",
                   help="纯 ASCII 显示（终端字体缺字或乱码时使用）")
    g.add_argument("-v", "--verbose", action="store_true", help="详细日志")
    g.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return p


def settings_from_args(args: argparse.Namespace) -> Settings:
    s = Settings()
    if args.output:
        s.output_dir = Path(args.output).expanduser()
    if args.quality:
        s.quality = args.quality
    if args.template:
        s.template = args.template
    s.subdir_by_uploader = bool(args.subdir)
    s.no_overwrite = not args.overwrite

    s.audio_only = bool(args.audio)
    if args.audio_format:
        s.audio_format = args.audio_format
    if args.audio_quality is not None:
        s.audio_quality = str(args.audio_quality)

    s.playlist = not args.no_playlist
    s.playlist_limit = args.playlist_limit
    if args.jobs:
        s.jobs = max(1, args.jobs)
    if args.concurrent_fragments:
        s.concurrent_fragments = max(1, args.concurrent_fragments)

    s.subtitles = bool(args.subs or args.embed_subs)
    if args.sub_langs:
        s.subtitle_langs = args.sub_langs
    s.embed_subs = bool(args.embed_subs)
    s.write_thumbnail = bool(args.write_thumbnail)
    s.embed_thumbnail = not args.no_thumbnail
    s.embed_metadata = not args.no_metadata
    s.write_info_json = bool(args.write_info_json)
    s.sponsorblock = bool(args.sponsorblock)

    if args.cookies:
        s.cookies = Path(args.cookies).expanduser()
    if args.cookies_from_browser:
        s.cookies_from_browser = args.cookies_from_browser
    s.username = args.username
    s.password = args.password
    s.proxy = args.proxy
    s.rate_limit = args.rate_limit
    s.impersonate = args.impersonate
    if args.sleep_interval is not None:
        s.sleep_interval = args.sleep_interval
    if args.retries is not None:
        s.retries = max(0, args.retries)
    s.archive = bool(args.archive)

    s.ffmpeg_location = args.ffmpeg_location
    s.verbose = bool(args.verbose)
    return s


# ---------------------------------------------------------------- 交互菜单

def status_line(s: Settings) -> None:
    mode = f"仅音频/{s.audio_format}" if s.audio_only else f"视频/{s.quality}"
    bits = [
        f"画质 {ui.blue(mode)}",
        f"目录 {ui.blue(str(Path(s.output_dir).expanduser()))}",
        f"并发 {ui.blue(str(s.jobs))}",
    ]
    if s.playlist:
        bits.append("播放列表 开")
    if s.cookies_from_browser:
        bits.append(f"Cookie {s.cookies_from_browser}")
    elif s.cookies:
        bits.append("Cookie 文件")
    if s.proxy:
        bits.append(f"代理 {s.proxy}")
    if s.subtitles:
        bits.append("字幕 开")
    ui.say("  " + ui.dim(" | ".join(bits)))


def _looks_like_youtube(urls: Sequence[str]) -> bool:
    return any(("youtube" in u.lower() or u.startswith(("ytsearch", "ytsearchdate")))
               for u in urls)


def run_download(s: Settings, urls: Sequence[str], *, probe: bool = False) -> int:
    from .core import Downloader, ffmpeg_hint, print_probe

    if not urls:
        ui.warn("没有拿到任何链接")
        return 1

    if probe:
        try:
            dl = Downloader(s, show_progress=False)
            info = dl.probe(urls[0])
            print_probe(info)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).strip() or "未知错误"
            ui.fail(f"获取信息失败：{type(exc).__name__}: {msg}")
            if s.verbose:
                import traceback

                traceback.print_exc()
            return 1
        return 0

    if _looks_like_youtube(urls) and js_runtime_missing():
        ui.warn("YouTube 需要 JS 运行时才能拿全清晰度，当前未检测到 deno / node。")
        ui.say(f"      {ui.dim('安装其一：winget install DenoLand.Deno  /  winget install OpenJS.NodeJS')}")
        ui.say()

    dl = Downloader(s)
    if not dl.ffmpeg:
        ui.warn(ffmpeg_hint())
    summary = dl.download(urls)

    ui.say()
    ui.rule("结果")
    line = (f"  成功 {ui.green(str(summary.ok_count))} / "
            f"失败 {ui.red(str(summary.fail_count))}")
    if summary.partial_count:
        line += f" / 部分成功 {ui.yellow(str(summary.partial_count))}"
    ui.say(line + f" / 共 {summary.total}")
    ui.say(f"  耗时 {ui.human_time(summary.elapsed)}")
    ui.say(f"  目录 {ui.blue(str(Path(s.output_dir).expanduser()))}")
    for r in summary.results:
        if r.ok and r.partial:
            ui.say(f"    {ui.yellow('⚠')} {r.url}")
            ui.say(f"      {ui.dim(r.error[:200])}")
        elif not r.ok:
            ui.say(f"    {ui.red('✗')} {r.url}")
            ui.say(f"      {ui.dim(r.error[:200])}")
    ui.rule()
    return 0 if summary.fail_count == 0 else 1


def quick_settings(s: Settings) -> None:
    while True:
        ui.say()
        ui.rule("快速设置")
        status_line(s)
        ui.say()
        options = [
            ("quality", "修改画质（当前 "
                        f"{s.audio_only and '仅音频' or s.quality}）"),
            ("audio", f"切换 仅音频模式（当前 {'开' if s.audio_only else '关'}）"),
            ("outdir", "修改输出目录"),
            ("cookie", "设置 Cookie（浏览器 / cookies.txt）"),
            ("proxy", "设置代理"),
            ("jobs", f"并发下载数（当前 {s.jobs}）"),
            ("subdir", f"按作者分目录（当前 {'开' if s.subdir_by_uploader else '关'}）"),
            ("subs", f"下载字幕（当前 {'开' if s.subtitles else '关'}）"),
            ("playlist", f"下载整个播放列表（当前 {'开' if s.playlist else '关'}）"),
            ("back", "返回主菜单"),
        ]
        key = ui.choose("请选择", options, default=len(options), quit_token="back")
        if key == "back":
            return
        if key == "quality":
            s.quality = ui.choose("选择画质", [(k, k) for k in QUALITY_FORMATS], default=1)
            s.audio_only = False
        elif key == "audio":
            s.audio_only = not s.audio_only
            if s.audio_only:
                s.audio_format = ui.choose(
                    "音频格式", [(k, k) for k in AUDIO_CODECS], default=1)
        elif key == "outdir":
            v = ui.ask("输入输出目录", str(Path(s.output_dir).expanduser()))
            s.output_dir = Path(v).expanduser()
        elif key == "cookie":
            mode = ui.choose("Cookie 来源", [
                ("browser", "从浏览器直接读取（推荐，需先关闭浏览器）"),
                ("file", "指定 cookies.txt 文件"),
                ("none", "清除 Cookie 设置"),
            ], default=1)
            if mode == "browser":
                s.cookies_from_browser = ui.ask("浏览器名 chrome/edge/firefox/brave", "chrome")
                s.cookies = None
            elif mode == "file":
                s.cookies = Path(ui.ask("cookies.txt 路径")).expanduser()
                s.cookies_from_browser = None
            else:
                s.cookies = None
                s.cookies_from_browser = None
        elif key == "proxy":
            s.proxy = ui.ask("代理地址（留空清除）", s.proxy or "") or None
        elif key == "jobs":
            s.jobs = max(1, int(ui.ask("并发数", str(s.jobs)) or s.jobs))
        elif key == "subdir":
            s.subdir_by_uploader = not s.subdir_by_uploader
        elif key == "subs":
            s.subtitles = not s.subtitles
        elif key == "playlist":
            s.playlist = not s.playlist


def search_and_pick(s: Settings) -> None:
    """按关键词搜索 -> 列出候选 -> 挑序号 -> 下载。"""
    from .core import Downloader

    site = ui.choose("选择搜索平台", [
        ("bilibili",   "哔哩哔哩（国内速度最快）"),
        ("youtube",    "YouTube（较慢，需 JS 运行时）"),
        ("soundcloud", "SoundCloud（以音频为主）"),
        ("niconico",   "Niconico 动画"),
    ], default=1, quit_token="__cancel__")
    if site == "__cancel__":
        ui.info("已取消")
        return

    q = ui.ask("搜索关键词（直接回车或输入 q 取消）")
    if not q or q.strip().lower() in ("q", "quit", "exit", "取消"):
        ui.info("已取消")
        return
    try:
        n = int(ui.ask("搜索条数", "10") or 10)
    except ValueError:
        n = 10
    n = max(1, min(n, 50))

    if site in SEARCH_NEEDS_IMPERSONATE and not s.impersonate:
        s.impersonate = "chrome"
        ui.info(f"{site} 的搜索接口有风控，已自动启用浏览器指纹伪装")

    prefix = SEARCH_PROVIDERS.get(site, "ytsearch")
    ui.say()
    ui.info(f"正在 {site} 搜索「{q}」…")
    try:
        entries = Downloader(s, show_progress=False).search(f"{prefix}{n}:{q}", n)
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).strip().splitlines()[0] if str(exc).strip() else "未知错误"
        ui.fail(f"搜索失败：{msg[:140]}")
        if "412" in msg or "Precondition" in msg:
            ui.say(f"      {ui.dim('该平台搜索接口有风控（已自动重试 3 次仍未通过）。可尝试：')}")
            ui.say(f"      {ui.dim('· 等十几秒再搜一次，或换个关键词')}")
            ui.say(f"      {ui.dim('· 提供登录态能显著降低被拦概率，例如 --cookies-from-browser chrome')}")
        return
    if not entries:
        ui.warn("没有搜到结果")
        return

    ui.say()
    ui.rule(f"搜索结果（{len(entries)} 条）")
    for i, e in enumerate(entries, 1):
        ui.say(f"  {i:>2}. {(e.get('title') or '?')[:64]}")
        meta = "  ".join(x for x in (
            (e.get("uploader") or e.get("channel") or "")[:20],
            e.get("duration_string") or ui.human_time(e.get("duration")),
        ) if x and x != "--:--")
        if meta:
            ui.say(f"      {ui.dim(meta)}")
    ui.say()

    raw = ui.ask("要下载哪些？输入序号（如 1,3,5），回车=全部，输入 q 取消", "")
    if raw.strip().lower() in ("q", "quit", "exit", "0", "取消"):
        ui.info("已取消，未下载任何内容")
        return
    picked: list[dict] = []
    if raw.strip():
        for part in raw.replace("，", ",").replace(" ", ",").split(","):
            part = part.strip()
            if part.isdigit() and 1 <= int(part) <= len(entries):
                picked.append(entries[int(part) - 1])
    else:
        picked = list(entries)

    links: list[str] = []
    for e in picked:
        u = e.get("webpage_url") or e.get("url") or ""
        if isinstance(u, str) and u.startswith("http"):
            links.append(u)
    if not links:
        ui.warn("没有选出可下载的链接")
        return

    run_download(s, links)


def interactive(s: Settings) -> int:
    sites = count_sites()
    while True:
        ui.clear()
        ui.banner(sites)
        status_line(s)
        ui.say()
        options = [
            ("url", "下载链接（单个或多个，直接粘贴）"),
            ("file", f"编辑 {DEFAULT_URL_FILE.name} 链接清单并批量下载"),
            ("audio", "仅下载音频（MP3）"),
            ("info", "查看链接信息与可用画质"),
            ("search", "按关键词搜索并下载"),
            ("settings", "快速设置"),
            ("sites", "查看支持的站点"),
            ("open", "打开下载目录"),
            ("quit", "退出程序"),
        ]
        key = ui.choose("请选择操作", options, default=1, quit_token="quit")

        if key == "quit":
            ui.say("\n再见！")
            return 0
        if key == "sites":
            ui.clear()
            list_sites()
            ui.ask("回车返回")
        elif key == "settings":
            quick_settings(s)
        elif key == "open":
            p = Path(s.output_dir).expanduser()
            p.mkdir(parents=True, exist_ok=True)
            open_folder(p)
        elif key == "file":
            if ui.ask_yes_no("打开编辑器编辑清单？（选否将直接用现有内容下载）", True):
                edit_and_download(s)
            else:
                urls = read_url_file(ensure_url_file(DEFAULT_URL_FILE))
                if not urls:
                    ui.warn("清单里还没有有效链接")
                else:
                    run_download(s, urls)
            ui.ask("回车返回")
        elif key == "url":
            raw = ui.ask("粘贴链接（多个用空格/逗号分隔）")
            urls = split_urls(raw)
            if urls:
                run_download(s, urls)
                ui.ask("回车返回")
        elif key == "audio":
            old = s.audio_only
            s.audio_only = True
            raw = ui.ask("粘贴链接（多个用空格/逗号分隔）")
            urls = split_urls(raw)
            if urls:
                run_download(s, urls)
                ui.ask("回车返回")
            s.audio_only = old
        elif key == "info":
            raw = ui.ask("粘贴链接")
            urls = split_urls(raw)
            if urls:
                run_download(s, urls[:1], probe=True)
                ui.ask("回车返回")
        elif key == "search":
            search_and_pick(s)
            ui.ask("回车返回")


# ---------------------------------------------------------------- main

def main(argv: Optional[Sequence[str]] = None) -> int:
    setup_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.no_color:
        ui.set_color(False)
    if args.ascii:
        ui.set_ascii(True)

    require_ytdlp()

    if args.list_sites:
        list_sites(verbose=args.verbose)
        return 0

    settings = settings_from_args(args)

    # ---- 收集 URL：位置参数 + -f 文件 + @文件 + --search
    urls: list[str] = []
    for u in args.urls:
        if u.startswith("@") and len(u) > 1:
            path = Path(u[1:]).expanduser()
            if not path.exists():
                ui.fail(f"找不到文件：{path}")
                return 2
            urls.extend(read_url_file(path))
        else:
            urls.append(u)
    if args.file:
        path = Path(args.file).expanduser()
        if not path.exists():
            ui.fail(f"找不到文件：{path}")
            return 2
        urls.extend(read_url_file(path))
    if args.search:
        prefix = SEARCH_PROVIDERS.get(args.search_site, "ytsearch")
        urls.append(f"{prefix}{max(1, args.search_limit)}:{args.search}")
        if args.search_site in SEARCH_NEEDS_IMPERSONATE and not settings.impersonate:
            settings.impersonate = "chrome"
            ui.info(f"{args.search_site} 的搜索接口有风控，已自动启用 --impersonate chrome")

    from .core import Downloader, detect_ffmpeg, ffmpeg_hint

    if args.dry_run:
        from .core import _Logger  # noqa: WPS450

        dl = Downloader(settings)
        opts = dl.build_opts(logger=_Logger(quiet=True))
        ui.rule("dry-run：将使用的参数")
        for k in sorted(opts):
            if k in ("postprocessors", "progress_hooks", "postprocessor_hooks", "logger"):
                val = f"<{len(opts[k]) if hasattr(opts[k], '__len__') else 1} 项>"
            else:
                val = opts[k]
            ui.say(f"  {ui.bold(k):<26} = {val}")
        ui.say(f"  {ui.bold('urls'):<26} = {urls}")
        ui.rule()
        return 0

    if not urls:
        if sys.stdin.isatty():
            fresh = not DEFAULT_URL_FILE.exists()
            path = ensure_url_file(DEFAULT_URL_FILE)
            try:
                if fresh:
                    ui.info(f"已自动生成批量下载清单：{path}")
                    if ui.ask_yes_no("现在打开编辑它吗（也可稍后在菜单里选「2」）", False):
                        open_in_editor(path)
                        ui.say()
                return interactive(settings)
            except KeyboardInterrupt:
                ui.say("\n已取消")
                return 130
        parser.print_help()
        return 0

    ff = detect_ffmpeg(settings.ffmpeg_location)
    if not ff and not args.info:
        ui.warn(ffmpeg_hint())
        ui.say()

    return run_download(settings, urls, probe=args.info)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
