# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller: сборка VoxVault в один каталог (onedir).

Почему `onedir`, а не `onefile`:
  - `onefile` каждый запуск распаковывает ~90 МБ во временный каталог —
    старт занимает секунды вместо мгновенного;
  - антивирусы регулярно ругаются на распаковку во временный каталог;
  - `onedir` — обычная папка с exe и DLL, её видно и легко отладить.

Почему НЕ `onefile`+`upx`: см. выше, UPX дополнительно ловит срабатывания.

Модели в сборку НЕ попадают намеренно: это 50 МБ–1,8 ГБ на язык, они
качаются приложением при первом запуске и лежат в каталоге моделей
пользователя. Проверка этого — в packaging/build.py.
"""
from pathlib import Path

import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Spec выполняется в процессе PyInstaller. Там по умолчанию кодировка
# консоли как в системе (на CI это cp1252), и наш диагностический print
# с русским текстом роняет сборку UnicodeEncodeError.
try:
    from dictophone.console import setup_console

    setup_console()
except Exception:
    pass

#: Раскладка сборки задаётся переменной окружения (её ставит build.py):
#:   VOXVAULT_ONEFILE=1 -> один файл VoxVault.exe (self-extracting)
#:   по умолчанию       -> папка: VoxVault.exe + VoxVault/_internal/
#: Пользователю release отдаётся onedir (быстрый старт, нет ложных
#: срабатываний антивирусов); onefile включается флагом `--onefile`.
ONEFILE = os.environ.get("VOXVAULT_ONEFILE") == "1"

LOCALES = ROOT / "src" / "dictophone" / "locales"
ICON = ROOT / "packaging" / "assets" / "VoxVault.ico"
VERSION = ROOT / "packaging" / "build" / "version_info.txt"
LAUNCHER = ROOT / "packaging" / "launcher.py"

# vosk и sounddevice грузят свои DLL через cffi/dlopen — обычного анализа
# импортов мало, поэтому забираем целиком.
vosk_binaries, vosk_datas, vosk_hidden = collect_all("vosk")
sd_binaries, sd_datas, sd_hidden = collect_all("sounddevice")

# Без cacert.pem скачивание моделей падает с SSL-ошибкой.
certifi_datas = collect_data_files("certifi")

block_cipher = None

a = Analysis(
    [str(LAUNCHER)],
    pathex=[str(ROOT / "src")],
    binaries=vosk_binaries + sd_binaries,
    datas=[
        (str(LOCALES), "dictophone/locales"),
        *vosk_datas,
        *sd_datas,
        *certifi_datas,
    ],
    hiddenimports=[
        *vosk_hidden,
        *sd_hidden,
        # импорты внутри функций: PyInstaller их тоже видит, но фиксируем явно
        "dictophone.gui_qt",
        "dictophone.qt_settings",
        "dictophone.qt_history",
        "dictophone.qt_language",
        "dictophone.qt_model_dialog",
        "dictophone.qt_workers",
        "dictophone.single_instance",
        "dictophone.storage",
        "dictophone.transcript",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # numpy проекту не нужен (WAV читается модулем wave) — минус ~15 МБ.
    excludes=[
        "numpy",
        "pytest",
        "tkinter.test",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtQuick",
        "PySide6.QtQuick3D",
        "PySide6.Qt3DCore",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtPdf",
        "PySide6.QtDesigner",
        "PySide6.QtBluetooth",
        "PySide6.QtPositioning",
        "PySide6.QtSerialPort",
        "PySide6.QtSql",
        "PySide6.QtTest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Qt-переводы (*.qm, ~6 МБ) в этот список кладёт хук PySide6 напрямую, минуя
# collect_all, поэтому резать их надо здесь — после Analysis и до COLLECT.
# Мы их не используем: свой i18n на JSON-словарях, QTranslator не вызывается.
_before = len(a.datas)
a.datas = [item for item in a.datas if not str(item[0]).endswith(".qm")]
_dropped = _before - len(a.datas)
if _dropped:
    print(f"[spec] убрано Qt-переводов (.qm): {_dropped}")

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

_EXE_COMMON = dict(
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                      # UPX → ложные срабатывания антивирусов
    console=False,                  # GUI-приложение: окна консоли быть не должно
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON) if ICON.exists() else None,
    version=str(VERSION) if VERSION.exists() else None,
)

if ONEFILE:
    # Один файл: при каждом запуске распаковывает содержимое во временный
    # каталог. Быстрый запуск и чистая папка — в одной сборке несовместимы.
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="VoxVault", **_EXE_COMMON)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
              name="VoxVault", **_EXE_COMMON)
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="VoxVault",
    )
