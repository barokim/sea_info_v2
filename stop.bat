@echo off
chcp 65001 >nul
cd /d "%~dp0"
taskkill /FI "WINDOWTITLE eq Sea-Info API*" /T /F >nul 2>nul && echo API 서버를 껐어요.
docker compose stop redis >nul 2>nul && echo Redis(Docker)를 멈췄어요.
echo 모두 껐어요. (데이터는 그대로 남아요)
pause
