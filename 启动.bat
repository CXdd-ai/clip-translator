@echo off
chcp 65001 >nul
cd /d "%~dp0"

where pythonw >nul 2>nul
if errorlevel 1 (
    echo.
    echo   [错误] 没找到 pythonw.exe
    echo   说明你的电脑上没装 Python，或者安装时没有勾选 "Add Python to PATH"。
    echo.
    pause
    exit /b 1
)

rem 用 pythonw 启动，不会弹出黑色命令行窗口
start "" pythonw "translator.py"
exit /b 0
