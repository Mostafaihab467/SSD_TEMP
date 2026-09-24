@echo off
cd /d "%~dp0"
set "PYTHON_EXE=C:\Users\mosta\AppData\Local\Programs\Python\Python311\pythonw.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=pythonw.exe"
start "" "%PYTHON_EXE%" "%~dp0nvme_monitor.py"
exit
