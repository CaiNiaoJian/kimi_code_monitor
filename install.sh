#!/bin/bash
# Kimi Code 额度监控 - 环境配置向导
# 支持: macOS / Linux (Ubuntu/Debian/CentOS/Arch)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/venv"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_ok()  { echo -e "${GREEN}[OK]${NC} $1"; }
print_warn(){ echo -e "${YELLOW}[WARN]${NC} $1"; }
print_err() { echo -e "${RED}[ERR]${NC} $1"; }

echo "================================================"
echo "  Kimi Code 额度监控 - 环境配置向导"
echo "================================================"
echo ""

# 1. 检查 Python
if ! command -v python3 &> /dev/null; then
    print_err "未检测到 Python3！"
    echo ""
    echo "请安装 Python 3.8+："
    echo "  macOS:   brew install python3"
    echo "  Ubuntu:  sudo apt update && sudo apt install python3 python3-venv python3-pip"
    echo "  CentOS:  sudo yum install python3 python3-venv"
    echo "  Arch:    sudo pacman -S python python-virtualenv"
    exit 1
fi

PYVER=$(python3 --version)
print_ok "检测到: ${PYVER}"
echo ""

# 2. 创建虚拟环境
if [ -d "$VENV_DIR" ]; then
    print_warn "虚拟环境已存在，跳过创建"
else
    echo "[1/4] 正在创建虚拟环境..."
    python3 -m venv "$VENV_DIR"
    print_ok "虚拟环境创建成功"
fi
echo ""

# 3. 安装依赖
echo "[2/4] 正在安装依赖包..."
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip -q

if pip install -r "${SCRIPT_DIR}/requirements.txt" 2>/dev/null; then
    print_ok "依赖安装完成"
else
    print_warn "部分依赖安装失败，但基础功能仍可运行"
    echo "        基础版无需任何依赖即可使用"
fi
echo ""

# 4. 检查 Kimi Code CLI
echo "[3/4] 检查 Kimi Code CLI..."
if command -v kimi-code &> /dev/null; then
    KIMIVER=$(kimi-code --version 2>/dev/null || echo "unknown")
    print_ok "检测到: ${KIMIVER}"
else
    print_warn "未检测到 kimi-code CLI"
    echo "        请访问 https://kimi.com/code 下载安装"
    echo "        或手动将 access_token 写入 ~/.kimi-code/credentials/kimi-code.json"
fi
echo ""

# 5. 初始化配置
echo "[4/4] 初始化监控配置..."
python "${SCRIPT_DIR}/kimi_monitor.py" --init > /dev/null 2>&1 || true
python "${SCRIPT_DIR}/kimi_monitor_pro.py" --init > /dev/null 2>&1 || true
print_ok "配置初始化完成"
echo ""

# 6. 完成提示
echo "================================================"
echo "  安装完成！你可以通过以下方式启动："
echo "================================================"
echo ""
echo "  [基础版 - 极简监控]"
echo "      venv/bin/python kimi_monitor.py --daemon"
echo ""
echo "  [Pro 版 - 智能开发辅助]"
echo "      venv/bin/python kimi_monitor_pro.py --daemon"
echo ""
echo "  [一键启动]"
echo "      ./start.sh"
echo ""
echo "  [查看帮助]"
echo "      venv/bin/python kimi_monitor_pro.py --help"
echo ""
