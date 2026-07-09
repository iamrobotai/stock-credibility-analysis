@echo off
chcp 65001 >nul
title 股票可信度分析系统 - 本地版
echo ============================================================
echo   股票可信度分析系统 - 本地版
echo ============================================================
echo.
echo   正在启动 Web 服务...
echo   浏览器访问: http://localhost:5000
echo   按 Ctrl+C 停止
echo.
echo ============================================================
REM 尝试使用系统 Python（如已安装）
where python >nul 2>&1
if %errorlevel%==0 (
    python "%~dp0app.py"
) else (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    echo 下载: https://www.python.org/downloads/
)
pause
