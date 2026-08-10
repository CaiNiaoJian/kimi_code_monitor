@echo off
chcp 65001 >nul
title Kimi Code 额度监控
echo ========================================
echo  Kimi Code 额度监控与自动恢复系统
echo ========================================
echo.

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)

REM 检查脚本存在
if not exist "%~dp0kimi_monitor.py" (
    echo [错误] 未找到 kimi_monitor.py，请确保与本文件在同一目录
    pause
    exit /b 1
)

echo [1/3] 正在检查额度状态...
python "%~dp0kimi_monitor.py" --once
if errorlevel 1 (
    echo.
    echo [提示] 首次使用请先运行: python kimi_monitor.py --init
    echo [提示] 并确保已运行: kimi-code login
    pause
    exit /b 1
)

echo.
echo [2/3] 检查通过，正在启动守护模式...
echo [3/3] 按 Ctrl+C 停止监控
echo.
python "%~dp0kimi_monitor.py" --daemon

echo.
echo 监控已停止。
pause
