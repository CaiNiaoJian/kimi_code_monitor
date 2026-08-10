@echo off
chcp 65001 >nul
title Kimi Code 额度监控 - 环境安装
echo ================================================
echo  Kimi Code 额度监控 - 环境配置向导
echo ================================================
echo.

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python！
    echo.
    echo 请先安装 Python 3.8 或更高版本：
    echo   1. 访问 https://www.python.org/downloads/
    echo   2. 下载并安装 Python 3.11+ (安装时勾选 "Add Python to PATH")
    echo   3. 重新运行此脚本
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%a in ('python --version') do set PYVER=%%a
echo [OK] 检测到: %PYVER%
echo.

REM 创建虚拟环境
set VENV_DIR=%~dp0venv
if exist "%VENV_DIR%" (
    echo [INFO] 虚拟环境已存在，跳过创建
) else (
    echo [1/4] 正在创建虚拟环境...
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [错误] 虚拟环境创建失败！
        echo [提示] 尝试以管理员身份运行此脚本
        pause
        exit /b 1
    )
    echo [OK] 虚拟环境创建成功
)
echo.

REM 激活虚拟环境并安装依赖
echo [2/4] 正在安装依赖包...
call "%VENV_DIR%\Scripts\activate.bat"
python -m pip install --upgrade pip
pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo [警告] 部分依赖安装失败，但基础功能仍可运行
    echo [提示] 基础版无需任何依赖即可使用
)
echo [OK] 依赖安装完成
echo.

REM 检查 Kimi Code CLI
echo [3/4] 检查 Kimi Code CLI...
kimi-code --version >nul 2>&1
if errorlevel 1 (
    echo [WARN] 未检测到 kimi-code CLI
    echo [提示] 请访问 https://kimi.com/code 下载安装
    echo [提示] 或手动将 access_token 写入 ~/.kimi-code/credentials/kimi-code.json
) else (
    for /f "tokens=*" %%a in ('kimi-code --version') do set KIMIVER=%%a
    echo [OK] 检测到: %KIMIVER%
)
echo.

REM 初始化配置
echo [4/4] 初始化监控配置...
call "%VENV_DIR%\Scripts\activate.bat"
python "%~dp0kimi_monitor.py" --init >nul 2>&1
python "%~dp0kimi_monitor_pro.py" --init >nul 2>&1
echo [OK] 配置初始化完成
echo.

REM 完成
echo ================================================
echo  安装完成！你可以通过以下方式启动：
echo ================================================
echo.
echo  [基础版 - 极简监控]
echo     venv\Scripts\python.exe kimi_monitor.py --daemon
echo.
echo  [Pro 版 - 智能开发辅助]
echo     venv\Scripts\python.exe kimi_monitor_pro.py --daemon
echo.
echo  [一键启动]
echo     start.bat
echo.
echo  [查看帮助]
echo     venv\Scripts\python.exe kimi_monitor_pro.py --help
echo.
pause
