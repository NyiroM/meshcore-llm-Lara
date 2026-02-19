# LARA Auto-Reply Bot - Indítási Útmutató

## Gyors Indítás

### 1. Batch fájl (.bat) - AJÁNLOTT
Dupla kattintás: **`start_lara.bat`**

- ✅ Automatikusan aktiválja a virtual environment-et
- ✅ UTF-8 kódolás támogatás
- ✅ Hibaellenőrzés (config, Python script)
- ✅ Szép formázott kimenet
- ✅ Automatikus pause hiba esetén

### 2. PowerShell script (.ps1)
Jobb klikk → "Futtatás PowerShell-lel": **`start_lara.ps1`**

- ✅ Minden amit a .bat tud, plusz:
- ✅ Python verzió ellenőrzés
- ✅ Részletesebb hibakezelés
- ✅ Színes kimenet

**Megjegyzés**: Első futtatásnál lehet, hogy engedélyezned kell:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### 3. Kézi indítás (terminálból)

#### Virtual environment-tel:
```cmd
.venv\Scripts\activate
python auto_reply_priv.py
```

#### Virtual environment nélkül:
```cmd
python auto_reply_priv.py
```

---

## Valódi .EXE létrehozása (opcionális)

Ha tényleg .exe fájlt szeretnél (egy kattintásos, dependency nélküli):

### 1. PyInstaller telepítése
```cmd
pip install pyinstaller
```

### 2. .exe buildelés
```cmd
pyinstaller --onefile --name "LARA_AutoReply" --console auto_reply_priv.py
```

### 3. Eredmény
- Kész .exe: `dist\LARA_AutoReply.exe`
- **FIGYELEM**: A `lara_config.yaml` fájlt **mellé kell másolni** a dist mappába!

**Hátránya**:
- ~30-50 MB méretű lesz (becsomagolja a Python-t és az összes library-t)
- Lassabb indulás (kicsomagolja a temp mappába)
- Antivirusok false positive-ot jelezhetnek

---

## Teendők első indítás előtt

1. ✅ `lara_config.yaml` kitöltve és helyes
2. ✅ Virtual environment létrehozva és aktiválva
3. ✅ Függőségek telepítve: `pip install -r requirements.txt`
4. ✅ COM portok helyesen beállítva
5. ✅ OpenWebUI API kulcs konfigurálva

---

## Troubleshooting

### "Python nem található"
- Telepítsd a Python-t: https://www.python.org/downloads/
- Vagy add hozzá a PATH-hoz

### "ModuleNotFoundError: meshcore"
```cmd
pip install meshcore requests pyyaml
```

### "COM port busy"
- Zárd be a MeshCore web app-ot
- Ellenőrizd, hogy nincs másik LARA példány futva

### Virtual environment nem aktiválódik
```cmd
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

---

## Háttérben futtatás (Windows szolgáltatásként)

Ha szeretnéd, hogy automatikusan induljon rendszerindításkor:

1. **NSSM** (Non-Sucking Service Manager) telepítése
2. Szolgáltatás létrehozása:
   ```cmd
   nssm install LARA "C:\path\to\python.exe" "C:\path\to\auto_reply_priv.py"
   nssm set LARA AppDirectory "C:\path\to\lara-cli-interface"
   nssm start LARA
   ```

---

**Készítette**: GitHub Copilot (Claude Sonnet 4.5)  
**Dátum**: 2026-02-18
