@echo off
chcp 65001 >nul
echo 正在打包 QianXunViewer（onedir 目录版，启动更快）...
call "%~dp0.venv\Scripts\activate.bat"
set QX_ONEFILE=0
pyinstaller --noconfirm --distpath "%~dp0dist" --workpath "%~dp0build" "%~dp0QianXunViewer.spec"
echo 完成，产物：dist\QianXunViewer\QianXunViewer.exe
pause
