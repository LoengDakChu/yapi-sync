#!/usr/bin/env bash
# YApi 接口同步启动器（macOS / Linux）
# 自动设置 UTF-8 编码环境变量，避免中文乱码。
# 用法：sync.sh <项目路径> [--dry-run] [--doc] [--doc-name="名称"] ...
set -euo pipefail

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if command -v python3 >/dev/null 2>&1; then
    PY=python3
else
    PY=python
fi

"$PY" "$DIR/yapi_sync.py" "$@"
