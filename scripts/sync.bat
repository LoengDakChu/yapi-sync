@echo off
REM YApi 接口同步启动器（Windows）
REM 自动切换 UTF-8 编码并设置 Python 编码环境变量，避免中文乱码。
REM 用法：sync.bat <项目路径> [--dry-run] [--doc] [--doc-name="名称"] ...
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
python "%~dp0yapi_sync.py" %*
endlocal
