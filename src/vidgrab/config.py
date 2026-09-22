"""全局配置：画质预设、默认参数、运行时设置对象。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

APP_NAME = "vidgrab"
APP_TITLE = "vidgrab 视频下载器"
__all__ = ["APP_NAME", "APP_TITLE", "QUALITY_FORMATS", "AUDIO_CODECS",
           "SEARCH_PROVIDERS", "SEARCH_NEEDS_IMPERSONATE",
           "DEFAULT_TEMPLATE", "Settings", "default_output_dir"]

# 画质 -> yt-dlp format 表达式
QUALITY_FORMATS: dict[str, str] = {
    "best":  "bv*+ba/b",                                  # 最高画质（自动合并音视频）
    "2160p": "bv*[height<=2160]+ba/b[height<=2160]",
    "1440p": "bv*[height<=1440]+ba/b[height<=1440]",
    "1080p": "bv*[height<=1080]+ba/b[height<=1080]",
    "720p":  "bv*[height<=720]+ba/b[height<=720]",
    "480p":  "bv*[height<=480]+ba/b[height<=480]",
    "360p":  "bv*[height<=360]+ba/b[height<=360]",
    "worst": "wv*+wa/w",                                  # 最小体积
}

# 音频转换目标格式 -> FFmpegExtractAudio 参数
AUDIO_CODECS: dict[str, str] = {
    "mp3": "mp3",
    "m4a": "m4a",
    "opus": "opus",
    "wav": "wav",
    "flac": "flac",
}

# 关键词搜索：平台 -> yt-dlp 的搜索前缀（伪 URL 形如 bilisearch10:关键词）
SEARCH_PROVIDERS: dict[str, str] = {
    "bilibili":     "bilisearch",    # 哔哩哔哩
    "youtube":      "ytsearch",      # YouTube
    "youtube-date": "ytsearchdate",  # YouTube（按上传日期排序）
    "soundcloud":   "scsearch",      # SoundCloud（音频为主）
    "niconico":     "nicosearch",    # ニコニコ動画
    "google":       "gvsearch",      # Google 视频
    "yahoo":        "yvsearch",      # Yahoo 视频
}

# 这些平台的搜索接口有风控，需要伪装浏览器指纹才能用
SEARCH_NEEDS_IMPERSONATE = {"bilibili"}

DEFAULT_TEMPLATE = "%(title).120s [%(id)s].%(ext)s"


def default_output_dir() -> Path:
    """默认下载目录：~/Downloads/vidgrab，不存在或不可写时退回当前目录。"""
    for base in (Path.home() / "Downloads", Path.home(), Path.cwd()):
        try:
            target = base / APP_NAME
            target.mkdir(parents=True, exist_ok=True)
            if os.access(target, os.W_OK):
                return target
        except OSError:
            continue
    return Path.cwd()


@dataclass
class Settings:
    """一次运行的全部可调参数（CLI 参数与交互菜单都写进这里）。"""

    output_dir: Path = field(default_factory=default_output_dir)

    # 画质 / 格式
    quality: str = "best"
    audio_only: bool = False
    audio_format: str = "mp3"
    audio_quality: str = "0"          # 0 = 最佳 VBR
    template: str = DEFAULT_TEMPLATE
    subdir_by_uploader: bool = False  # 按作者建子目录

    # 播放列表
    playlist: bool = True
    playlist_limit: Optional[int] = None

    # 字幕
    subtitles: bool = False
    subtitle_langs: str = "zh-Hans,zh-CN,zh,en"
    embed_subs: bool = False

    # 元数据
    embed_thumbnail: bool = True
    embed_metadata: bool = True
    write_thumbnail: bool = False
    write_info_json: bool = False
    sponsorblock: bool = False

    # 网络
    proxy: Optional[str] = None
    rate_limit: Optional[str] = None   # 例如 "2M"（2 MiB/s）
    retries: int = 10
    concurrent_fragments: int = 4
    jobs: int = 1                      # 同时下载的链接数
    sleep_interval: float = 0.0        # 每个请求间的等待，规避风控
    impersonate: Optional[str] = None  # 例如 "chrome"

    # 认证
    cookies: Optional[Path] = None
    cookies_from_browser: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None

    # 其它
    archive: bool = False
    no_overwrite: bool = False
    ffmpeg_location: Optional[str] = None
    verbose: bool = False
    quiet: bool = False
