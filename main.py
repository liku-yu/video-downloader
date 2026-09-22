#!/usr/bin/env python3
"""vidgrab 直接运行入口。

用法： uv run main.py [参数...]
"""

from __future__ import annotations

import sys
from pathlib import Path

# 允许未安装项目时直接 `python main.py`（把 src/ 挂到 sys.path）
_ROOT = Path(__file__).resolve().parent
_SRC = _ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

try:
    from vidgrab.cli import main
except ImportError as exc:  # pragma: no cover
    print(f"[错误] 无法导入 vidgrab：{exc}\n"
          f"请先安装依赖：uv sync --extra ffmpeg", file=sys.stderr)
    raise SystemExit(2)

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n已取消")
        raise SystemExit(130)
