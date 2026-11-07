@echo off
title Aion 2 Weed Metter
cd /d "%~dp0"

echo ===================================================
echo              AION 2 WEED METTER v1.0
echo ===================================================
echo.

:: Verifica se o executavel standalone existe
if exist "Aion2_Weed_Metter.exe" (
    echo Iniciando Aion 2 Weed Metter (Standalone)...
    start "" "Aion2_Weed_Metter.exe"
    exit /b
)

:: Caso contrario, inicia via interpretador Python
echo Iniciando via Python...
python aion2_overlay.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Ocorreu um erro ao iniciar o Aion 2 Weed Metter.
    echo Certifique-se de que o Python e as dependencias estao instalados:
    echo pip install -r requirements.txt
    pause
)
