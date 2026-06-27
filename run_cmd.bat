@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist venv ( echo start.batを先に1回実行してください & pause & exit )
call venv\Scripts\activate
echo.
echo == 一括取込み用コマンド窓 ==
echo 例: python bulk_import.py --base 490108516 --limit 50
echo.
cmd /k
