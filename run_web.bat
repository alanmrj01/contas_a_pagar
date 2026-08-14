@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Contas a Pagar Web 2.0.2

echo ================================================================
echo CONTAS A PAGAR WEB 2.0.2.0
echo ================================================================
echo.

set "PYTHON_EXE="
where py >nul 2>nul && set "PYTHON_EXE=py -3"
if not defined PYTHON_EXE (
  where python >nul 2>nul && set "PYTHON_EXE=python"
)
if not defined PYTHON_EXE (
  echo ERRO: Python 3 nao encontrado.
  echo Instale Python 3.13 ou superior e execute este arquivo novamente.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Criando ambiente virtual...
  %PYTHON_EXE% -m venv ".venv"
  if errorlevel 1 goto :error
)

echo [2/3] Instalando/verificando dependencias...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :error

echo [3/3] Iniciando servidor web...
echo.
echo Acesse: http://127.0.0.1:8000
echo Para encerrar, pressione CTRL+C nesta janela.
echo.
".venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000
exit /b %errorlevel%

:error
echo.
echo ================================================================
echo NAO FOI POSSIVEL INICIAR O CONTAS A PAGAR WEB.
echo ================================================================
pause
exit /b 1
