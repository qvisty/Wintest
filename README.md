# Windows File Search App

To parallelle implementeringer af en Windows file search-applikation – én i **PySide6 (Qt)** og én i **Flet (Flutter)** – til sammenligning.

## Funktionalitet

Begge apps har identisk funktionalitet:

- **Mappevælger** med "Gennemse..."-knap
- **Søgefelt** med Enter-understøttelse
- **Resultatliste** – klik/dobbeltklik åbner filens placering i Stifinder
- **Baggrundssøgning** – UI'et fryser ikke under søgning
- **Statuslinje** der viser antal fundne filer

## Projektstruktur

```
Wintest/
├── pyside6_app/              # Qt-baseret (industristandard)
│   ├── main.py               # Entry point
│   ├── ui.py                 # Vindue med widgets
│   ├── searcher.py           # Baggrundssøgning via QThread
│   ├── requirements.txt      # pip install PySide6
│   └── build.bat             # Byg til exe
│
└── flet_app/                 # Flutter-baseret (moderne, simpelt API)
    ├── main.py               # Entry point
    ├── ui.py                 # UI opbygget med Flet-komponenter
    ├── searcher.py           # Baggrundssøgning via threading
    ├── requirements.txt      # pip install flet
    ├── build.bat             # Byg til exe med flet build
    └── build_pyinstaller.bat # Alternativ: byg til exe med PyInstaller
```

## Forudsætninger

- Python 3.10+ installeret på Windows
- pip (følger med Python)

## Kør fra kildekode

### PySide6-versionen

```bash
cd pyside6_app
pip install -r requirements.txt
python main.py
```

### Flet-versionen

```bash
cd flet_app
pip install -r requirements.txt
python main.py
```

## Byg som .exe

Begge apps kan pakkes som selvstændige `.exe`-filer, så de kan køre uden Python installeret.

### PySide6

Dobbeltklik `pyside6_app\build.bat` eller kør manuelt:

```bash
cd pyside6_app
pip install pyinstaller
pyinstaller --onefile --windowed --name "FileSearch-Qt" main.py
```

Exe-filen havner i `dist\FileSearch-Qt.exe`.

### Flet

**Mulighed 1 – Flets eget build-system:**

```bash
cd flet_app
flet build windows
```

Output i `build\windows\`.

**Mulighed 2 – PyInstaller:**

Dobbeltklik `flet_app\build_pyinstaller.bat` eller kør manuelt:

```bash
cd flet_app
pip install pyinstaller
pyinstaller --onefile --windowed --name "FileSearch-Flet" main.py
```

Exe-filen havner i `dist\FileSearch-Flet.exe`.

### Build-indstillinger

| Flag | Effekt |
|---|---|
| `--onefile` | Pakker alt i én enkelt `.exe`-fil |
| `--windowed` | Skjuler konsol-vinduet (kun GUI vises) |
| `--icon=ikon.ico` | Tilføj et brugerdefineret ikon til exe-filen |

Exe-filerne bliver ca. 30–80 MB, da hele Python-runtimen er inkluderet.

## Sammenligning af frameworks

| | PySide6 (Qt) | Flet (Flutter) |
|---|---|---|
| **Udseende** | Native Windows-look | Moderne Material Design |
| **Modenhed** | Industristandard, stor community | Nyere, voksende hurtigt |
| **Installationsstørrelse** | ~100 MB | ~50 MB |
| **Widget-udvalg** | Meget stort | Moderat, voksende |
| **Skalerbarhed** | Velegnet til store, komplekse apps | Bedst til små-mellemstore apps |
| **Ekstra** | Qt Designer (visuel UI-editor) | Kan også bygge til web og mobil |
