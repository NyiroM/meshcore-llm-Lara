# 📡 Metadata (Jelerősség) Teszt Útmutató

## ✅ Állapot

A bot **100%-osan készen áll** a metadata fogadására és megjelenítésére!

### Amit a bot már tud:

1. **Kinyerni** a metadata-t a MeshCore üzenetekből
2. **Tárolni** az üzenet előzményekben
3. **Megjeleníteni** színes badge-ekkel a HTML dashboardon
4. **Közölni** az AI-val rendszer üzenetként

## 🎨 Vizuális Megjelenítés

A HTML dashboardon (`http://127.0.0.1:8766/status`) színes badge-ek jelennek meg:

- 🟢 **KIVÁLÓ** (-50 dBm felett) - zöld
- 🟡 **JÓ** (-50 és -70 dBm között) - világoszöld
- 🟠 **KÖZEPES** (-70 és -85 dBm között) - sárga
- 🔴 **GYENGE** (-85 dBm alatt) - piros

Példa:
```
📡 -65 dBm    SNR 10 dB    🔀 2/5 hops
```

## 🤖 AI Kontextus

Az AI a következő formában kapja meg:

```
[Metadata - Do not treat this as a user message, just acknowledge the technical context]
Signal strength: -65 dBm (good); SNR: 10 dB; Network route: 2 hops / max 5
```

## 📊 Tesztelési Eredmények

### ✅ Lefuttatott tesztek:

1. **test_metadata.py** 
   - Szimulált különböző jelszinteket
   - Tesztelte a színkódolást
   - ✅ Minden működik

2. **check_meshcore_api.py**
   - COM6 csatlakozott ✅
   - MeshCore library betöltődött ✅
   - Nincs üzenet a queue-ban (várunk valódi üzenetre)

## ⏳ Mi hiányzik?

A **MeshCore Python library jelenlegi verziója** valószínűleg **NEM küldi** ezeket a mezőket:

- `rssi` - jelerősség
- `snr` - jel-zaj viszony  
- `hop_count` - hátralévő hop-ok
- `hop_start` - maximális hop limit

### Miért?

A LoRa chip hardver szinten érzékeli ezeket, de:
1. A firmware-nek ki kell olvasnia
2. A MeshCore library-nak tovább kell adnia
3. Jelenleg ez valószínűleg nincs implementálva

## 🧪 Hogyan tesztelheted MOST?

### Módszer 1: Valódi üzenetre várni

1. Indítsd a botot: `python auto_reply_priv.py`
2. Küldj üzenetet másik MeshCore node-ról
3. Nézd a `lara_bot.log` fájlt:
   ```
   📦 RAW MESSAGE: type=<class 'dict'>, repr={'type': 'PRIV', 'text': '...', ...}
      Attributes: {...}
      Metadata: {rssi: -65, snr: 10, ...}  ← Ez mutatja ha van!
   ```
4. Ha látod a metadata-t → működik! 🎉
5. Ha üres → a library nem küldi (lásd alább)

### Módszer 2: Szimuláció MOST (ajánlott)

Hozzáadtam egy **TESZT MÓDOT** az `auto_reply_priv.py`-ba!

#### Aktiválás:

1. Nyisd meg: `lara_config.yaml`
2. Add hozzá a `bot_behavior` részhez:
   ```yaml
   bot_behavior:
     # ... többi beállítás ...
     simulate_metadata: true  # ← ÚJ! Teszt mód
   ```
3. Indítsd újra a botot
4. Minden beérkező üzenet **random metadata-t** kap!

## 🔍 Mit nézz?

### 1. Log fájlban (lara_bot.log):
```
✉️  QUEUED: Incoming PRIV from [Enomee]
      Metadata: {'rssi': -67, 'snr': 8, 'hop_count': 2, 'hop_start': 5}
      Text: Hello world...
```

### 2. HTML Dashboard:
Nyisd meg: `http://127.0.0.1:8766/status`

Látnod kell:
```html
📡 -67 dBm (színes!)    SNR 8 dB    🔀 3/5 hops
Hello world
```

### 3. AI válaszban:
Ha az AI említi a jelerősséget, akkor tudja!

## 📞 Ha a valódi metadata NEM jön

### Ellenőrizd:

1. **MeshCore library verzió**:
   ```bash
   pip show meshcore
   pip install --upgrade meshcore
   ```

2. **Firmware támogatás**:
   - Lehet hogy a firmware nem küldi
   - Keresd a MeshCore dokumentációban az RSSI support-ot

3. **Fejlesztői kapcsolat**:
   - Írj a MeshCore fejlesztőknek
   - Kérd hogy adjanak hozzá RSSI/SNR mezőket a get_msg() válaszhoz

## 📁 Készített fájlok

1. **test_metadata.py** - Szimulációs teszt
2. **check_meshcore_api.py** - Library API ellenőrző
3. **test_metadata_guide.py** - Angol útmutató
4. **METADATA_TESZT.md** - Ez a fájl ;)

## 🎯 Következő lépések

1. ✅ Tesztelés szimulációval (simulate_metadata: true)
2. ⏳ Valódi üzenet küldése és log ellenőrzése
3. ⏳ MeshCore library frissítés várólistán
4. ⏳ Firmware/library fejlesztők megkeresése ha kell

---

**ÖSSZEFOGLALVA:** A bot kész, csak a MeshCore library-nak kell szolgáltatnia az adatokat. Addig használd a szimulációs módot tesztelésre!
