@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PATH=%~dp0.venv\Scripts;%PATH%"
set "DATABASE_URL=sqlite:///./data/preview_local/sea_info_preview.db"
set "API_PORT=8810"
set "WEB_PORT=8510"
echo 담당 뉴스 미리보기 DB로 실행합니다: data\preview_local\sea_info_preview.db
echo 화면 주소: http://127.0.0.1:8510/news
call "%~dp0start.bat"
