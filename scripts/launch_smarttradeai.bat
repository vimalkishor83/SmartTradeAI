@echo off
setlocal
set APPDIR=D:\Claude\SmartTradeAI
set URL=http://127.0.0.1:5000/login

cd /d "%APPDIR%"

rem If the server is already up, just open the browser and exit.
curl -s -o NUL -w "%%{http_code}" --max-time 2 %URL% 2>NUL | findstr "200" >NUL
if %ERRORLEVEL%==0 (
    start "" %URL%
    exit /b 0
)

rem Start the server in the background (no visible console window).
start "SmartTradeAI Server" /min cmd /c "python run.py > server_run.log 2>&1"

rem Wait for it to come up, then open the default browser.
:waitloop
timeout /t 1 /nobreak >NUL
curl -s -o NUL -w "%%{http_code}" --max-time 2 %URL% 2>NUL | findstr "200" >NUL
if not %ERRORLEVEL%==0 goto waitloop

start "" %URL%
endlocal
