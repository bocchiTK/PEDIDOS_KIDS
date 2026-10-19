@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m pip install -r requirements.txt
if errorlevel 1 goto error
start "" /b python -c "import time, webbrowser; time.sleep(2); webbrowser.open('http://127.0.0.1:5001')"
python app.py
pause
exit /b
:error
echo No se pudo iniciar el entorno. Comprueba Python y la conexion.
pause