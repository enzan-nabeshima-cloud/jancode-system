@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist venv (
  echo [初回] 仮想環境を作成します...
  python -m venv venv
)
call venv\Scripts\activate
pip install -q -r requirements.txt
if not exist .env copy .env.example .env >nul
echo.
echo ブラウザで http://localhost:5057 を開いてください
echo 終了するには このウィンドウで Ctrl+C
echo.
python app.py
pause
