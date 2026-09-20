@echo off
REM Roda o Sistema Comercial (versao Android/Kivy) para teste no Windows.
REM Basta dar duplo-clique neste arquivo sempre que quiser testar.

cd /d "%~dp0"

if not exist venv\Scripts\python.exe (
    echo ERRO: nao encontrei o ambiente virtual "venv" nesta pasta.
    echo Rode primeiro: py -3.12 -m venv venv
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

echo Iniciando o Sistema Comercial...
echo.
python app.py

echo.
echo ==============================================
echo O programa foi fechado (ou deu erro acima).
echo ==============================================
pause
