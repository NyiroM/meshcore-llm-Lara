@echo off
chcp 65001 >nul
title LARA - EXE Builder

echo.
echo ╔════════════════════════════════════════════╗
echo ║   LARA Auto-Reply Bot - EXE Építő         ║
echo ╚════════════════════════════════════════════╝
echo.

cd /d "%~dp0"

REM Ellenőrizzük a PyInstaller-t
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo [!] PyInstaller nincs telepítve
    echo [→] Telepítés...
    echo.
    pip install pyinstaller
    if errorlevel 1 (
        echo [✗] Telepítés sikertelen!
        pause
        exit /b 1
    )
    echo.
    echo [✓] PyInstaller telepítve
    echo.
)

echo [i] PyInstaller verzió:
pyinstaller --version
echo.

echo [→] .EXE építése...
echo     Ez 1-3 percet vehet igénybe...
echo.

REM Tisztítsuk meg a korábbi build-et
if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist

REM Build spec fájlból (fejlettebb konfiguráció)
if exist "lara_autoexe.spec" (
    echo [i] Spec fájl használata: lara_autoexe.spec
    pyinstaller lara_autoexe.spec
) else (
    REM Egyszerű build, ha nincs spec
    echo [i] Egyszerű build (nincs spec fájl)
    pyinstaller --onefile --name "LARA_AutoReply" --console auto_reply_priv.py
)

if errorlevel 1 (
    echo.
    echo [✗] Build sikertelen!
    pause
    exit /b 1
)

echo.
echo ────────────────────────────────────────────
echo.
echo [✓] Build sikeres!
echo.
echo [i] Eredmény: dist\LARA_AutoReply.exe
echo.

REM Ellenőrizzük, hogy létrejött-e
if exist "dist\LARA_AutoReply.exe" (
    for %%A in (dist\LARA_AutoReply.exe) do (
        echo [i] Fájl méret: %%~zA bytes (~%%~zAk KB)
    )
    echo.
    
    REM Másoljuk át a config fájlt
    if exist "lara_config.yaml" (
        copy /y "lara_config.yaml" "dist\lara_config.yaml" >nul
        echo [✓] Config fájl átmásolva: dist\lara_config.yaml
    ) else (
        echo [!] Figyelem: lara_config.yaml hiányzik!
        echo     Másold át kézzel a dist\ mappába!
    )
    
    echo.
    echo ────────────────────────────────────────────
    echo.
    echo [→] Használat:
    echo     1. Nyisd meg: dist\
    echo     2. Dupla kattintás: LARA_AutoReply.exe
    echo.
    echo [!] FONTOS: A lara_config.yaml fájlnak AZ EXE MELLETT kell lennie!
    echo.
) else (
    echo [✗] HIBA: Az exe fájl nem jött létre!
)

pause
