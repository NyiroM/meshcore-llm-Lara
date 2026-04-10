# LARA Auto-Reply Bot - Startup Guide

## Quick Start

### 1. Batch file (.bat) - RECOMMENDED
Double-click: **`start_lara.bat`**

- ✅ Automatically activates the virtual environment
- ✅ Supports UTF-8 encoding
- ✅ Performs configuration and Python script validation
- ✅ Nicely formatted output
- ✅ Pauses automatically on errors

### 2. PowerShell script (.ps1)
Right-click → "Run with PowerShell": **`start_lara.ps1`**

- ✅ Includes everything the .bat offers, plus:
- ✅ Python version validation
- ✅ More detailed error handling
- ✅ Colorized output

**Note**: On the first run you may need to enable script execution:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### 3. Manual startup (terminal)

#### With virtual environment:
```cmd
.venv\Scripts\activate
python auto_reply_priv.py
```

#### Without virtual environment:
```cmd
python auto_reply_priv.py
```

---

## Building a standalone .exe (optional)

If you want a one-click executable without requiring installed dependencies:

### 1. Install PyInstaller
```cmd
pip install pyinstaller
```

### 2. Build the executable
```cmd
pyinstaller --onefile --name "LARA_AutoReply" --console auto_reply_priv.py
```

### 3. Output
- Built executable: `dist\LARA_AutoReply.exe`
- **NOTE**: Copy `lara_config.yaml` alongside the exe in the dist folder.

**Caveats**:
- The executable may be ~30-50 MB because it bundles Python and libraries
- Startup can be slower while it extracts to a temp folder
- Antivirus software may occasionally report false positives

---

## Pre-launch checklist

1. ✅ `lara_config.yaml` is filled out correctly
2. ✅ Virtual environment is created and activated
3. ✅ Dependencies installed: `pip install -r requirements.txt`
4. ✅ COM ports are set correctly
5. ✅ OpenWebUI API key is configured

---

## Troubleshooting

### "Python not found"
- Install Python: https://www.python.org/downloads/
- Or add Python to your PATH

### "ModuleNotFoundError: meshcore"
```cmd
pip install meshcore requests pyyaml
```

### "COM port busy"
- Close the MeshCore web app
- Ensure no other LARA instance is running

### Virtual environment will not activate
```cmd
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

---

## Running as a Windows background service

To start automatically on system boot:

1. Install **NSSM** (Non-Sucking Service Manager)
2. Create the service:
   ```cmd
   nssm install LARA "C:\path\to\python.exe" "C:\path\to\auto_reply_priv.py"
   nssm set LARA AppDirectory "C:\path\to\lara-cli-interface"
   nssm start LARA
   ```

---

**Created with AI-assisted tooling**
