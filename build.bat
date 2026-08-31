@echo off
chcp 65001 >nul
echo 正在打包 QianXunViewer（onefile 单文件，首次启动略慢属正常）...
call "%~dp0.venv\Scripts\activate.bat"
pyinstaller -F -w -n QianXunViewer --icon="%~dp0assets\icon.ico" --add-data "%~dp0assets\logo.png;assets" --add-data "%~dp0src\ui\styles.qss;src\ui" --distpath "%~dp0dist" --workpath "%~dp0build" --specpath "%~dp0build" "%~dp0main.py"
echo 完成，产物：dist\QianXunViewer.exe
pause
