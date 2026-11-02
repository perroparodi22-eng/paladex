@echo off
REM ============================================================
REM  Parodi Group - Honey Intelligence
REM  Doppio clic su questo file per avviare l'applicazione.
REM  Double-click this file to start the application.
REM ============================================================
setlocal
cd /d "%~dp0"
title Parodi Group - Honey Intelligence

where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")
%PY% --version >nul 2>nul
if not %errorlevel%==0 (
  echo.
  echo  Python non trovato. Installare Python 3.11 o superiore da https://www.python.org/downloads/
  echo  ^(durante l'installazione spuntare "Add Python to PATH"^), poi riaprire questo file.
  echo.
  pause
  exit /b 1
)

if not exist "backend\.venv\Scripts\python.exe" (
  echo  Prima installazione: preparo l'ambiente ^(qualche minuto^)...
  %PY% -m venv backend\.venv || goto :error
  backend\.venv\Scripts\python.exe -m pip install --upgrade pip >nul
  backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt || goto :error
)

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

cd backend
.venv\Scripts\python.exe -m paladex serve
goto :eof

:error
echo.
echo  Installazione non riuscita. Controllare la connessione internet e riprovare.
pause
exit /b 1
