"""vidgrab 冒烟测试：不联网、不需要 pytest。

用法：  python tests/smoke.py        （在仓库根目录执行）

为什么需要它：CI 里的 `compileall` 只能发现**语法**问题，
而 Python 3.9~3.11 上「运行时不支持 `dict[str, int]` 这类下标」的写法
只有真正跑一遍才会暴露，所以这里补一层运行时检查。
"""

from __future__ import annotations

import contextlib
import io
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))          # 以便导入 build_standalone

import vidgrab  # noqa: E402
import vidgrab.cli as cli  # noqa: E402
import vidgrab.config as config  # noqa: E402
import vidgrab.core as core  # noqa: E402
import vidgrab.ui as ui  # noqa: E402

FAILURES: list[str] = []


def check(name: str, fn) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        FAILURES.append(f"{name}: {type(exc).__name__}: {exc}")
        traceback.print_exc()
    else:
        print(f"  ok  {name}")


def silent_stdout():
    return contextlib.redirect_stdout(io.StringIO())


# ------------------------------------------------------------------ 用例

def test_模块导入与版本() -> None:
    assert isinstance(vidgrab.__version__, str) and vidgrab.__version__
    for mod in (cli, config, core, ui):
        assert mod is not None


def test_UI_ASCII开关与符号() -> None:
    ui.set_ascii(False)
    assert ui._s("✓", "OK") == "✓"
    ui.set_ascii(True)
    assert ui._s("✓", "OK") == "OK"
    ui.set_ascii(False)
    assert ui.human_size(1024) == "1.0KiB"
    assert ui.human_time(65) == "01:05"
    assert ui.human_time(3661) == "1:01:01"
    assert ui.human_time(None) == "--:--"


def test_交互菜单组件_两个分支() -> None:
    """覆盖 ui.choose 的 quit_token 提示行（Unicode / ASCII 都要走一遍）。

    这一行曾因「多行表达式写进 f-string」在 Python <3.12 上是语法错误。
    """
    for ascii_mode in (False, True):
        ui.set_ascii(ascii_mode)
        old_stdin = sys.stdin
        try:
            sys.stdin = io.StringIO("q\n")
            with silent_stdout():
                got = ui.choose("请选择", [("a", "A"), ("b", "B")],
                                default=1, quit_token="quit")
            assert got == "quit", f"ascii={ascii_mode} 得到 {got!r}"

            sys.stdin = io.StringIO("2\n")
            with silent_stdout():
                got = ui.choose("请选择", [("a", "A"), ("b", "B")], default=1)
            assert got == "b", f"ascii={ascii_mode} 得到 {got!r}"
        finally:
            sys.stdin = old_stdin
            ui.set_ascii(False)


def test_画质预设全部可翻译() -> None:
    for quality, expr in config.QUALITY_FORMATS.items():
        s = config.Settings()
        s.quality = quality
        d = core.Downloader(s, show_progress=False)
        assert d.build_opts()["format"] == expr, quality


def test_音频模式与后处理器() -> None:
    s = config.Settings()
    s.audio_only = True
    s.audio_format = "mp3"
    opts = core.Downloader(s, show_progress=False).build_opts()
    assert opts["format"] == "ba/b"
    keys = [pp["key"] for pp in opts.get("postprocessors", [])]
    assert "FFmpegExtractAudio" in keys, keys
    assert "FFmpegMetadata" in keys, keys


def test_字幕选项() -> None:
    s = config.Settings()
    s.subtitles = True
    s.embed_subs = True
    s.subtitle_langs = "zh-Hans,en"
    opts = core.Downloader(s, show_progress=False).build_opts()
    assert opts["writesubtitles"] is True
    assert opts["subtitleslangs"] == ["zh-Hans", "en"]
    assert opts["embedsubtitles"] is True


def test_文件名模板与作者子目录() -> None:
    d = core.Downloader(config.Settings(), show_progress=False)
    assert d._outtmpl().endswith(config.DEFAULT_TEMPLATE)

    s = config.Settings()
    s.subdir_by_uploader = True
    d = core.Downloader(s, show_progress=False)
    assert d._outtmpl().endswith(Path(config.DEFAULT_TEMPLATE).name)
    assert "uploader" in d._outtmpl()


def test_播放列表与并发参数() -> None:
    s = config.Settings()
    s.playlist = False
    s.playlist_limit = 3
    s.concurrent_fragments = 8
    s.retries = 5
    opts = core.Downloader(s, show_progress=False).build_opts()
    assert opts["noplaylist"] is True
    assert opts["playlistend"] == 3
    assert opts["concurrent_fragment_downloads"] == 8
    assert opts["retries"] == 5


def test_搜索结果前缀构造() -> None:
    assert config.SEARCH_PROVIDERS["bilibili"] == "bilisearch"
    assert "bilisearch" in f"{config.SEARCH_PROVIDERS['bilibili']}5:关键词"
    assert config.SEARCH_PROVIDERS["youtube"] == "ytsearch"
    assert "bilibili" in config.SEARCH_NEEDS_IMPERSONATE


def test_链接拆分() -> None:
    urls = cli.split_urls("http://a.com/1, http://b.com/2\nhttp://c.com/3\t")
    assert urls == ["http://a.com/1", "http://b.com/2", "http://c.com/3"], urls
    assert cli.split_urls("  ") == []


def test_结果对象统计() -> None:
    s = core.BatchSummary(results=[
        core.TaskResult(url="a", ok=True),
        core.TaskResult(url="b", ok=False),
        core.TaskResult(url="c", ok=True, partial=True),
    ])
    assert (s.total, s.ok_count, s.fail_count, s.partial_count) == (3, 2, 1, 1)


def test_单文件版与源码同步() -> None:
    import build_standalone

    assert build_standalone.check_current() == 0


def main() -> int:
    tests = [(n[5:].replace("_", " "), f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    print(f"运行 {len(tests)} 项冒烟测试（Python {sys.version.split()[0]}）\n")
    for name, fn in tests:
        check(name, fn)
    print()
    if FAILURES:
        print(f"x 失败 {len(FAILURES)} 项：")
        for f in FAILURES:
            print(f"   {f}")
        return 1
    print(f"OK 全部 {len(tests)} 项通过")
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass
    raise SystemExit(main())
