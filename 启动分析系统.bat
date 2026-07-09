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
"C:\Users\outzb\.workbuddy\binaries\python\envs\default\Scripts\python.exe" "C:\Users\outzb\WorkBuddy\Claw\stock-credibility-analysis\app.py"
pause
