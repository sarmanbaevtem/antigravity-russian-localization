@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "action="
echo Русификатор Google Antigravity 2.33.0
echo.
echo 1. Установить русский интерфейс
echo 2. Проверить установку
echo 3. Восстановить оригинал
echo 4. Выйти
choice /C 1234 /N /M "Выберите действие [1-4]: "
if errorlevel 4 exit /b 0
if errorlevel 3 (set "action=restore") else if errorlevel 2 (set "action=check") else if errorlevel 1 (set "action=apply")
if not defined action exit /b 1
py -3 -I -c "import sys; sys.exit(sys.version_info < (3,10))" >nul 2>&1
if errorlevel 1 goto try_python
py -3 -I -X utf8 "%~dp0localize.py" %action%
goto finish
:try_python
python -I -c "import sys; sys.exit(sys.version_info < (3,10))" >nul 2>&1
if errorlevel 1 goto missing
python -I -X utf8 "%~dp0localize.py" %action%
:finish
set "result=%errorlevel%"
pause
exit /b %result%
:missing
echo Требуется Python 3.10 или новее. Установите Python для Windows с python.org.
pause
exit /b 1
