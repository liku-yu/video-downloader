@echo off
chcp 65001 >nul 2>nul
title vidgrab 视频下载器
cd /d "%~dp0"

rem ==================================================================
rem  vidgrab 一键启动脚本（Windows）
rem    · 双击本文件         → 打开交互菜单
rem    · 把 urls.txt 拖上来 → 批量下载该文件里的链接
rem ==================================================================

rem ---- 依赖索引源 --------------------------------------------------
rem  默认阿里云镜像（实测 ~1.6 MB/s）。
rem  官方源 pypi.org 在本机被解析到 fake-ip、速度仅 ~15 KB/s，
rem  同步同样依赖需 10 分钟以上，因此默认不用；
rem  若你的网络能直连官方源，取消下面一行的注释即可切换：
rem set "UV_DEFAULT_INDEX=https://pypi.org/simple"
if not defined UV_DEFAULT_INDEX set "UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple/"

rem ---- 界面改用纯 ASCII（终端字体缺字、显示乱码时取消注释）----
rem set "VIDGRAB_ASCII=1"

rem ---- 无 Python 时 uv 会自行下载解释器；国内网络可启用镜像 ----
rem set "UV_PYTHON_INSTALL_MIRROR=https://gh-proxy.com/https://github.com/astral-sh/python-build-standalone/releases/download"

echo ================================================================
echo   vidgrab 视频下载器
echo   YouTube / B站 / 抖音 / 快手 / 小红书 / TikTok 等 1751+ 站点
echo ================================================================
echo.

set "UV="
call :find_uv
if defined UV goto :have_uv

echo [0/3] 未检测到 uv，正在自动安装...
echo.
call :install_uv
if errorlevel 1 goto :uv_fail

call :find_uv
if defined UV goto :have_uv
goto :uv_fail

rem ------------------------------------------------------------------
:have_uv
echo [1/3] 同步依赖（首次运行约 40MB，请耐心等待）...
"%UV%" sync --extra ffmpeg
if not errorlevel 1 goto :sync_ok

echo   * 同步失败，换用清华镜像重试...
set "UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple"
"%UV%" sync --extra ffmpeg
if not errorlevel 1 goto :sync_ok

echo   * 仍失败，退回不含内置 ffmpeg 的最小依赖...
"%UV%" sync
if errorlevel 1 goto :sync_fail

:sync_ok
echo.
echo [2/3] 环境就绪
echo.
echo [3/3] 启动...
echo.

if "%~1"=="" goto :run_menu

:run_file
"%UV%" run python main.py -f "%~1"
set "RC=%ERRORLEVEL%"
goto :finish

:run_menu
"%UV%" run python main.py
set "RC=%ERRORLEVEL%"
goto :finish

rem ------------------------------------------------------------------
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
rem 依次尝试：winget、pip、官方脚本
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

rem ------------------------------------------------------------------
:uv_fail
echo.
echo [错误] 自动安装 uv 失败。请手动安装后重试，任选其一：
echo        1) winget install astral-sh.uv
echo        2) pip install uv
echo        3) 打开 https://docs.astral.sh/uv/ 按说明安装
echo.
pause
exit /b 1

:sync_fail
echo.
echo [错误] 依赖同步失败，通常是网络问题。可手动换源后重试：
echo          set UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
echo          uv sync --extra ffmpeg
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
