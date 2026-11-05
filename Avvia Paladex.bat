@echo off
REM ============================================================
REM  Parodi Group - Honey Intelligence
REM  Doppio clic su questo file per avviare l'applicazione.
REM  Double-click this file to start the application.
REM ============================================================
setlocal
cd /d "%~dp0"
title Parodi Group - Honey Intelligence

REM The application's own Python: created on the first start, and again when it no longer runs or
REM is older than 3.11 (Python removed or replaced on this computer).
set "VPY=backend\.venv\Scripts\python.exe"
if not exist "%VPY%" goto :install
"%VPY%" -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul && goto :installed
rmdir /s /q backend\.venv

:install
set "PY="
py -3 -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul && set "PY=py -3"
if not defined PY (python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul && set "PY=python")
if not defined PY goto :nopython
echo  Prima installazione: preparo l'ambiente (qualche minuto)...
echo  First start: preparing the environment (a few minutes)...
%PY% -m venv backend\.venv || goto :error
"%VPY%" -m pip install --upgrade pip >nul 2>nul
"%VPY%" -m pip install -r backend\requirements.txt || goto :error

:installed
if not exist "frontend\dist\index.html" (
  where npm >nul 2>nul
  if not errorlevel 1 (
    echo  Preparo l'interfaccia...
    pushd frontend
    call npm ci || call npm install
    call npm run build
    popd
  ) else (
    echo  ATTENZIONE: interfaccia non compilata e Node.js non installato. Vedere README.md
  )
)

if not exist ".env" copy ".env.example" ".env" >nul

REM Optional Tesseract OCR: its Windows installer does not put it on the PATH.
if not defined PALADEX_TESSERACT_CMD if exist "%ProgramFiles%\Tesseract-OCR\tesseract.exe" set "PALADEX_TESSERACT_CMD=%ProgramFiles%\Tesseract-OCR\tesseract.exe"

REM Update (git pull), libraries if they changed, then start. Run as one block: an update may
REM rewrite this file while it runs, and cmd must not read any line of it afterwards.
(backend\.venv\Scripts\python.exe scripts\launch.py & exit /b)

:nopython
echo.
echo  Python 3.11 o superiore non trovato. Installarlo da https://www.python.org/downloads/
echo  (durante l'installazione spuntare "Add Python to PATH"), poi riaprire questo file.
echo  Python 3.11 or newer not found: install it from https://www.python.org/downloads/
echo  (tick "Add Python to PATH" during the installation), then open this file again.
echo.
pause
exit /b 1

:error
echo.
echo  Installazione non riuscita. Controllare la connessione internet e riaprire questo file.
echo  Installation failed. Check the internet connection and open this file again.
echo.
pause
exit /b 1
