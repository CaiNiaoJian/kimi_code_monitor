#!/bin/bash
# Kimi Code 额度监控启动脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MONITOR_PY="${SCRIPT_DIR}/kimi_monitor.py"

echo "========================================"
echo " Kimi Code 额度监控与自动恢复系统"
echo "========================================"
echo ""

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未找到 python3，请先安装 Python 3.8+"
    exit 1
fi

# 检查脚本
if [ ! -f "$MONITOR_PY" ]; then
    echo "[错误] 未找到 kimi_monitor.py，请确保与本文件在同一目录"
    exit 1
fi

echo "[1/3] 正在检查额度状态..."
if ! python3 "$MONITOR_PY" --once; then
    echo ""
    echo "[提示] 首次使用请先运行: python3 kimi_monitor.py --init"
    echo "[提示] 并确保已运行: kimi-code login"
    exit 1
fi

echo ""
echo "[2/3] 检查通过，正在启动守护模式..."
echo "[3/3] 按 Ctrl+C 停止监控"
echo ""
python3 "$MONITOR_PY" --daemon

echo ""
echo "监控已停止。"
