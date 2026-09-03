@echo off
chcp 65001 >nul
echo 正在打包 QianXunViewer（onefile 单文件，首次启动略慢属正常）...
call "%~dp0.venv\Scripts\activate.bat"
set QX_ONEFILE=1
pyinstaller --noconfirm --distpath "%~dp0dist" --workpath "%~dp0build" "%~dp0QianXunViewer.spec"
echo 完成，产物：dist\QianXunViewer.exe
pause
