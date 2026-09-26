"""Сгенерировать `assets/VoxVault.ico` — иконку, вшитую в собранный exe.

Сама картинка рисуется в `dictophone.app_icon`: тот же код отдаёт иконку
окну приложения, поэтому в exe и в заголовке окна она не расходится.

Запуск:  python packaging/make_icon.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

OUT = ROOT / "packaging" / "assets" / "VoxVault.ico"


def main() -> int:
    # UTF-8 до первого вывода: скрипт запускается в том числе из CI, где
    # кодировка консоли cp1252 и русский текст роняет процесс.
    from dictophone.console import setup_console

    setup_console()

    try:
        from dictophone.app_icon import ICON_SIZES, write_ico
    except ImportError:
        print("Нужен PySide6: py -m pip install PySide6-Essentials", file=sys.stderr)
        return 1
    write_ico(OUT)
    print(
        f"Иконка записана: {OUT} ({OUT.stat().st_size} байт, {len(ICON_SIZES)} размеров)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
