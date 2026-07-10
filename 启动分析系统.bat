@echo off
chcp 65001 >nul
title 股票可信度分析系统 - 本地版 v2.5
echo ============================================================
echo   股票可信度分析系统 - 本地版 v2.5
echo ============================================================
echo.
echo   正在启动 Web 服务...
echo   浏览器访问: http://localhost:5000
echo   按 Ctrl+C 停止
echo.
echo ============================================================

REM 优先使用项目内 venv
if exist "%~dp0venv\Scripts\python.exe" (
    "%~dp0venv\Scripts\python.exe" "%~dp0app.py"
) else (
    REM 回退到系统 Python
    where python >nul 2>&1
    if %errorlevel%==0 (
        python "%~dp0app.py"
    ) else (
        echo [错误] 未找到 Python，请按以下步骤操作:
        echo   1. 安装 Python 3.10+: https://www.python.org/downloads/
        echo   2. 创建虚拟环境: python -m venv venv
        echo   3. 安装依赖: venv\Scripts\pip install -r requirements.txt
        echo   4. 再次双击本文件启动
    )
)
pause
