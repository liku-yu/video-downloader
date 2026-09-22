# vidgrab · 跨平台视频下载器（Windows）

[![CI](https://github.com/liku-yu/video-downloader/actions/workflows/ci.yml/badge.svg)](https://github.com/liku-yu/video-downloader/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/liku-yu/video-downloader)](https://github.com/liku-yu/video-downloader/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%20%7C%203.13-blue.svg)](pyproject.toml)
[![Powered by yt-dlp](https://img.shields.io/badge/powered%20by-yt--dlp-red.svg)](https://github.com/yt-dlp/yt-dlp)

基于 [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) 内核的视频 / 音频 / 字幕下载工具，
内置 **1751 个站点**解析器，用 [`uv`](https://docs.astral.sh/uv/) 管理依赖，**双击 `run.bat` 即用**。

> ⚠️ **免责声明**：仅用于下载**你有权保存的内容**。请遵守目标平台协议与当地版权法律。
> 本工具不包含也不支持任何绕过 DRM / 付费墙的代码（Netflix、爱奇艺 VIP 等无法下载）。

## 一、快速开始

| | 方式 A：文件夹版 | 方式 B：单文件版 |
|---|---|---|
| 需要复制 | `run.bat` + `main.py` + `pyproject.toml` + `uv.lock` + `src/` | **只需 `vidgrab-standalone.bat`** |
| 适合 | 长期使用、想改代码 | 快速试用、发给别人 |

> 单文件版可直接从 [**Releases**](https://github.com/liku-yu/video-downloader/releases/latest) 下载，不用克隆仓库。

- 双击 → 自动装 uv → 同步依赖 → 打开菜单。首次需联网下载约 40 MB，之后秒开；
- 把 `urls.txt` 拖到 bat 上 → 按该文件内容批量下载；
- **`.venv/` 不要复制**：那是 Linux 上建的，Windows 用不了，uv 会自动重建。

```
  ▸ 1. 下载链接                2. 编辑 urls.txt 链接清单并批量下载
    3. 仅下载音频（MP3）        4. 查看链接信息与可用画质
    5. 按关键词搜索并下载        6. 快速设置
    7. 查看支持的站点           8. 打开下载目录         9. 退出程序
```

任何提问处输入 `0` 或 `q` 可直接退出 / 取消，不会下载任何内容。

### 批量下载清单 urls.txt

首次运行自动生成，是纯文本，直接用记事本编辑：

```
# 每行一个链接；# 开头是注释，空行会被忽略
https://www.bilibili.com/video/BV1xx411c7mD
https://www.youtube.com/watch?v=xxxxxxxxxxx
```

三种用法：① 首次运行时问你要不要打开编辑；② 菜单第 2 项（编辑 → 保存关闭 → 自动批量下载）；
③ 把文件拖到 bat 上，按现有内容下载。

## 二、下载进度

```
[1/2] [████████████░░░░░░░░░░░░]  50.4%  2.0MiB/4.0MiB  3.1MiB/s  ETA 00:00  │ 总  25.2%
[1/2] ✓ 【标题】  │ 总  50.0%
```

`50.4%` 是当前文件进度；`│ 总 25.2%` 是整批任务进度（按进度加权，只增不减）。
终端字体缺字导致乱码时，取消 `run.bat` 里 `set "VIDGRAB_ASCII=1"` 的注释可切纯 ASCII 样式。

## 三、命令行用法

```bat
uv run python main.py "<链接>"                                   :: 最高画质
uv run python main.py -q 1080p -o "D:/Videos" "<链接1>" "<链接2>"
uv run python main.py --audio --audio-format mp3 "<链接>"
uv run python main.py -f urls.txt --jobs 3                       :: 批量 + 3 并发
uv run python main.py -i "<链接>"                                 :: 只看信息，不下载
uv run python main.py --search "关键词" --search-site bilibili --search-limit 5
uv run python main.py --cookies-from-browser chrome "<链接>"      :: 登录态（B站高清）
```

## 四、关键词搜索

把关键词交给平台搜索接口 → 取回候选列表 → 你按序号挑选 → 下载。
入口：菜单第 5 项，或命令行的 `--search`（平台用 `--search-site` 指定）。

- 平台：`bilibili` / `youtube` / `youtube-date` / `soundcloud` / `niconico` / `google` / `yahoo`
- 实测耗时：B站约 3 秒，YouTube 约 27 秒，SoundCloud 约 58 秒
- B站搜索是概率性风控（会间歇返回 412），已内置**自动重试 3 次 + 退避**；仍失败可加
  `--cookies-from-browser chrome` 提供登录态
- ⚠️ **只有 10 个站点支持关键词搜索**（yt-dlp 内核限制），并非全部 1751 个

## 五、参数速查

| 分类 | 参数 | 说明 |
|---|---|---|
| 画质 | `-q/--quality` | `best` `2160p` `1440p` `1080p` `720p` `480p` `360p` `worst` |
| 输出 | `-o/--output` · `--subdir` · `--overwrite` | 目录 · 按作者建子目录 · 覆盖已有文件 |
| 音频 | `-a/--audio` · `--audio-format` | 仅音频 · `mp3` `m4a` `opus` `wav` `flac` |
| 批量 | `-f/--file` · `--jobs N` | 从文件读链接 · 同时下载的链接数 |
| 列表 | `--playlist-limit N` · `--no-playlist` | 列表只下 N 个 · 只下当前视频 |
| 字幕 | `--subs` · `--sub-langs` · `--embed-subs` | 下载字幕 · 指定语言 · 嵌入视频 |
| 元数据 | `--no-thumbnail` · `--no-metadata` · `--write-info-json` | 封面 · 元数据 · JSON |
| 搜索 | `--search` · `--search-site` · `--search-limit N` | 关键词 · 平台 · 取前 N 个 |
| 网络 | `--proxy` · `--rate-limit 2M` · `--sleep-interval 3` · `--retries N` | 代理 · 限速 · 请求间隔 · 重试次数 |
| 认证 | `--cookies FILE` · `--cookies-from-browser chrome` | cookies.txt · 直接读浏览器 |
| 反爬 | `--impersonate chrome` | 伪装浏览器指纹 |
| 其它 | `-i/--info` · `--dry-run` · `--ascii` · `-v/--verbose` | 只看信息 · 打印参数 · 纯ASCII · 详细日志 |

完整参数：`uv run python main.py --help`

## 六、依赖源

本机实测 `pypi.org` 被 DNS 解析到 fake-ip（`198.18.0.x`，出口走透明代理），
索引页速度仅 **~15 KB/s**，装一次 yt-dlp 要 2 分多钟；阿里云镜像 **~1.6 MB/s**。
因此**默认使用阿里云镜像**，同步失败会自动换清华源重试，再失败退回最小依赖。

想切回官方源（你的网络能直连时）：取消 `run.bat` 里这行的注释

```bat
rem set "UV_DEFAULT_INDEX=https://pypi.org/simple"
```

> ⚠️ **锁文件与镜像源是绑定的**：`uv.lock` 会记录每个包是从哪个索引解析来的，
> 当前锁文件里的 888 处引用全部指向阿里云镜像。因此在用**官方源**的环境里执行
> `uv sync` 时，uv 会判定锁文件过期并重新解析（`uv.lock` 会被改写、`git status` 变脏）。
>
> 想让仓库默认走官方源（例如主要面向海外用户），执行下面这条重新生成锁文件，
> 并把 `run.bat` / 单文件版里的 `UV_DEFAULT_INDEX` 默认值改成官方源：
>
> ```bat
> uv lock --default-index https://pypi.org/simple
> ```

## 七、常见问题

| 现象 | 处理 |
|---|---|
| 提示「未找到 ffmpeg」 | `run.bat` 默认已装内置 `imageio-ffmpeg`；仍不行就 `--ffmpeg-location "C:\ffmpeg\bin"` |
| B站只有 360P / 480P | 未登录只给低清。加 `--cookies-from-browser chrome`（**先完全退出浏览器**），或 `--cookies cookies.txt` |
| 读浏览器 Cookie 报错 | 浏览器锁住了 Cookie 库，先关掉浏览器；或改用导出的 cookies.txt |
| 抖音 / TikTok / 小红书 解析失败 | 先升级内核 `uv lock --upgrade-package yt-dlp && uv sync`，再加 `--impersonate chrome` |
| 下载慢 / 频繁中断 | 调低 `--rate-limit`、加 `--sleep-interval 3`、提高 `--retries 20`；境外站点配 `--proxy` |
| 双击 run.bat 一闪而过 | 右键「在终端中打开」手动执行，或在 `@echo off` 下临时加 `echo on` 看报错 |
| 目录里冒出 `例如`/`打开交互菜单`/`nul` 等空文件 | 批处理注释里的 `->` 被 cmd 当成重定向符（**Windows 上也会发生**）。当前版本已改为全角 `→` 并加入生成自检；旧版本手动删掉这些空壳文件即可 |

`.bat` 不是跨平台格式，**别在 Linux / macOS 上执行**；在 Kali 上用 `uv run python main.py`。

## 八、项目结构

```
video-downloader/
├─ run.bat                  # 【方式A】双击启动：装 uv + 同步依赖 + 打开菜单
├─ vidgrab-standalone.bat   # 【方式B】单文件版，可单独复制使用
├─ build_standalone.py      # 生成上面那个单文件 bat，--check 可校验其是否与源码同步
├─ main.py                  # 运行入口
├─ pyproject.toml / uv.lock # 依赖声明与版本锁定
├─ urls.txt                 # 批量下载清单
├─ LICENSE                  # MIT
├─ .github/workflows/ci.yml # CI：语法 / 导入 / 冒烟 / 单文件版同步校验
├─ tests/smoke.py           # 冒烟测试（不联网、无需 pytest）
└─ src/vidgrab/
   ├─ cli.py                # 命令行参数 + 交互菜单
   ├─ core.py               # 下载核心（yt-dlp 选项、进度、批量调度）
   ├─ config.py             # 画质预设与运行参数
   └─ ui.py                 # 控制台适配（ANSI/ASCII）、进度条、菜单组件
```

部署到 Windows 最少需要：`run.bat` + `main.py` + `pyproject.toml` + `src/`（`uv.lock` 建议带上）。

## 九、开发

```bat
uv sync --extra ffmpeg      :: 建环境
uv run python main.py -h    :: 运行
uv lock --upgrade           :: 升级依赖（含 yt-dlp 内核，建议定期执行）
uv run python tests/smoke.py              :: 冒烟测试（CI 同款）
uv run python build_standalone.py         :: 改完源码后重新生成单文件版
uv run python build_standalone.py --check :: 校验单文件版是否与源码同步（CI 同款）
```

改完源码别忘了重新生成单文件版；`--check` 会在产物过期时非零退出。

支持的 Python 版本为 **3.9+**，CI 会在 3.9 与 3.13 上分别验证（注意：
**多行表达式不能写进 f-string 的 `{}` 里**，那是 3.12+ 才有的语法）。
