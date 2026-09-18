@echo off
rem Cria o ambiente virtual na primeira execucao e abre o programa.
rem Ex.: run_windows.bat --modo caixa
setlocal
cd /d "%~dp0"
if not exist .venv (
    echo Criando ambiente virtual...
    py -3.13 -m venv .venv || py -3 -m venv .venv || goto :erro
    .venv\Scripts\python -m pip install --upgrade pip
    .venv\Scripts\pip install -r requirements.txt || goto :erro
)
.venv\Scripts\python main.py %*
goto :eof
:erro
echo Nao foi possivel preparar o ambiente. Confira se o Python 3.13 (64 bits) esta instalado.
pause
