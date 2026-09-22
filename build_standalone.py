#!/usr/bin/env python3
"""把 vidgrab 打包成「单文件」Windows 批处理 vidgrab-standalone.bat。

原理：
  1. 用 zipapp 把 src/vidgrab 打成单文件应用 vidgrab.pyz
  2. 把 .pyz 做 base64 编码，内嵌到 .bat 末尾（纯 ASCII，不受编码影响）
  3. .bat 运行时：
        findstr 定位载荷行 -> more 跳过前面的批处理代码提取 base64
        -> certutil -decode 还原 vidgrab.pyz
        -> uv run --with yt-dlp ... python vidgrab.pyz
  这样用户只需要这一个 .bat 文件。

用法：uv run python build_standalone.py
"""

from __future__ import annotations

import base64
import re
import shutil
import tempfile
import textwrap
import zipapp
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PKG_DIR = ROOT / "src" / "vidgrab"
OUT_BAT = ROOT / "vidgrab-standalone.bat"
PAYLOAD_MARK = "rem __VIDGRAB_PAYLOAD__"

MAIN_PY = '''"""vidgrab 单文件版入口。"""
import sys

from vidgrab.cli import main

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\\n已取消")
        sys.exit(130)
'''


# cmd 会把 rem/echo 行里未被引号包裹、未用 ^ 转义的 < > | & 当作重定向/管道符，
# 例如 `rem 双击 -> 打开菜单` 会在 Windows 上真的创建出一个名为「打开菜单」的文件。
_DANGER_RE = re.compile(r"(?<!\^)[<>|&]")


def audit_bat(text: str, label: str) -> list[str]:
    problems: list[str] = []
    for i, line in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
        st = line.strip()
        if not (st.startswith("rem") or st.startswith("echo") or st.startswith("@")):
            continue
        stripped = re.sub(r'"[^"]*"', '""', st)   # 引号内的字符是安全的
        for m in _DANGER_RE.finditer(stripped):
            problems.append(f"{label} 第 {i} 行出现 {m.group()!r}：{st[:70]}")
    return problems


def read_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    return m.group(1) if m else "0.0.0"


def build_pyz() -> bytes:
    """把包目录打包成单文件 zipapp。"""
    with tempfile.TemporaryDirectory() as td:
        stage = Path(td) / "app"
        stage.mkdir()
        shutil.copytree(
            PKG_DIR, stage / "vidgrab",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        (stage / "__main__.py").write_text(MAIN_PY, encoding="utf-8")
        out = Path(td) / "vidgrab.pyz"
        zipapp.create_archive(stage, out, compressed=True)
        return out.read_bytes()


BAT_TEMPLATE = r"""@echo off
chcp 65001 >nul 2>nul
title vidgrab 视频下载器
setlocal EnableExtensions
cd /d "%~dp0"

rem ==================================================================
rem  vidgrab 单文件版（Windows）
rem  只有这一个文件就能运行，不需要其它任何配套文件。
rem    双击本文件         → 打开交互菜单
rem    把 urls.txt 拖上来  → 批量下载该文件里的链接
rem    命令行传参         → 例如 vidgrab-standalone.bat -q 1080p "链接"
rem ==================================================================

set "VIDGRAB_VERSION=__VERSION__"
set "VIDGRAB_HOME=%LOCALAPPDATA%\vidgrab"
if not exist "%VIDGRAB_HOME%" mkdir "%VIDGRAB_HOME%" >nul 2>nul

rem ---- 依赖索引源：默认阿里云；能直连官方源就取消下一行注释 ----
rem set "UV_DEFAULT_INDEX=https://pypi.org/simple"
if not defined UV_DEFAULT_INDEX set "UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple/"

rem ---- 终端字体缺字/乱码时取消注释，改用纯 ASCII 界面 ----
rem set "VIDGRAB_ASCII=1"

echo ================================================================
echo   vidgrab 视频下载器  单文件版 v%VIDGRAB_VERSION%
echo   YouTube / B站 / 抖音 / 快手 / 小红书 / TikTok 等 1751+ 站点
echo ================================================================
echo.

rem ---------------------------------------------------------- 1. 定位 uv
set "UV="
call :find_uv
if defined UV goto :have_uv

echo [1/3] 未检测到 uv，正在自动安装（仅首次）...
echo.
call :install_uv
if errorlevel 1 goto :uv_fail
call :find_uv
if defined UV goto :have_uv
goto :uv_fail

rem ---------------------------------------------------------- 2. 还原程序
:have_uv
echo [2/3] 准备程序...
set "PYZ=%VIDGRAB_HOME%\vidgrab.pyz"
set "B64=%TEMP%\vidgrab_b64_%RANDOM%%RANDOM%.txt"

for /f "delims=:" %%i in ('findstr /n /b /e /c:"rem __VIDGRAB_PAYLOAD__" "%~f0"') do set "SKIP=%%i"
if not defined SKIP goto :decode_fail

more +%SKIP% "%~f0" > "%B64%" 2>nul
certutil -f -decode "%B64%" "%PYZ%" >nul 2>nul
if not errorlevel 1 goto :have_pyz

echo   * 首次解码失败，换用 PowerShell 重试...
powershell -NoProfile -Command "$l = Get-Content -LiteralPath '%~f0'; $i = [Array]::IndexOf($l, 'rem __VIDGRAB_PAYLOAD__'); ($l[($i + 1)..($l.Count - 1)]) -join \"`n\" | Set-Content -LiteralPath '%B64%' -Encoding Ascii" >nul 2>nul
certutil -f -decode "%B64%" "%PYZ%" >nul 2>nul
if errorlevel 1 goto :decode_fail

:have_pyz
del "%B64%" >nul 2>nul

rem ---------------------------------------------------------- 3. 运行
echo [3/3] 启动（首次运行需联网下载依赖，约 40MB）...
echo.
if "%~1"=="" goto :run_menu
if exist "%~1" goto :run_file
goto :run_args

:run_file
"%UV%" run --with "yt-dlp[default]" --with "curl_cffi" --with "imageio-ffmpeg" python "%PYZ%" @"%~1"
set "RC=%ERRORLEVEL%"
goto :finish

:run_args
"%UV%" run --with "yt-dlp[default]" --with "curl_cffi" --with "imageio-ffmpeg" python "%PYZ%" %*
set "RC=%ERRORLEVEL%"
goto :finish

:run_menu
"%UV%" run --with "yt-dlp[default]" --with "curl_cffi" --with "imageio-ffmpeg" python "%PYZ%"
set "RC=%ERRORLEVEL%"
goto :finish

rem ---------------------------------------------------------- 子过程
:find_uv
set "UV="
where uv >nul 2>nul && set "UV=uv"
if defined UV exit /b 0
if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe"
if defined UV exit /b 0
if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe" set "UV=%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe"
if defined UV exit /b 0
if exist "%APPDATA%\Python\Scripts\uv.exe" set "UV=%APPDATA%\Python\Scripts\uv.exe"
exit /b 0

:install_uv
where winget >nul 2>nul
if not errorlevel 1 (
    echo   - 尝试 winget 安装 ...
    winget install --id astral-sh.uv -e --silent --accept-source-agreements --accept-package-agreements
    if not errorlevel 1 exit /b 0
)
where python >nul 2>nul
if not errorlevel 1 (
    echo   - 尝试 pip 安装 ...
    python -m pip install -U uv -i %UV_DEFAULT_INDEX% --disable-pip-version-check
    if not errorlevel 1 exit /b 0
)
echo   - 尝试官方安装脚本 ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
if not errorlevel 1 exit /b 0
exit /b 1

:uv_fail
echo.
echo [错误] 自动安装 uv 失败，请手动安装后重试：
echo        1) winget install astral-sh.uv
echo        2) pip install uv
echo        3) https://docs.astral.sh/uv/
echo.
pause
exit /b 1

:decode_fail
echo.
echo [错误] 无法从本文件还原内嵌程序，文件可能被截断或修改过。
echo        请重新下载完整副本，或改用「文件夹版」的 run.bat。
echo.
pause
exit /b 1

:finish
echo.
echo ================================================================
if "%RC%"=="0" (
    echo   全部完成
) else (
    echo   已结束（退出码 %RC%，失败原因见上方日志）
)
echo   下载目录： %USERPROFILE%\Downloads\vidgrab
echo ================================================================
echo.
pause
exit /b %RC%
"""


def main() -> None:
    version = read_version()
    pyz = build_pyz()
    b64 = base64.b64encode(pyz).decode("ascii")
    payload = "\n".join(textwrap.wrap(b64, 76))

    bat = BAT_TEMPLATE.replace("__VERSION__", version)
    bat = bat + PAYLOAD_MARK + "\n" + payload + "\n"

    # Windows 批处理需要 CRLF 行尾
    OUT_BAT.write_bytes(bat.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))

    # ---- 自检：载荷标记行必须唯一，且 more 跳过后应恰好剩纯 base64 ----
    text = bat.replace("\r\n", "\n")
    lines = text.split("\n")
    marks = [i + 1 for i, l in enumerate(lines) if l == PAYLOAD_MARK]
    assert len(marks) == 1, f"载荷标记行必须唯一，实际出现 {len(marks)} 处: {marks}"

    skip = marks[0]
    rest = [l for l in lines[skip:] if l.strip()]
    assert len(rest) == len(payload.splitlines()), "跳过后剩余行数异常"
    decoded = base64.b64decode("".join(rest))
    assert decoded == pyz, "自检失败：从 bat 还原出的内容与 pyz 不一致"

    # ---- 自检：批处理注释里不能有会被 cmd 当成重定向的字符 ----
    problems = audit_bat(bat, OUT_BAT.name)
    run_bat = ROOT / "run.bat"
    if run_bat.exists():
        problems += audit_bat(run_bat.read_text(encoding="utf-8"), run_bat.name)
    if problems:
        print("✗ 自检失败：以下字符会被 cmd 当作重定向/管道符，会在 Windows 上生成垃圾文件")
        for item in problems:
            print("   ", item)
        raise SystemExit(1)

    print(f"已生成 {OUT_BAT.name}")
    print(f"  版本      : {version}")
    print(f"  pyz 大小  : {len(pyz):,} 字节")
    print(f"  bat 大小  : {OUT_BAT.stat().st_size:,} 字节")
    print(f"  payload 行: {len(payload.splitlines())}")


if __name__ == "__main__":
    main()
