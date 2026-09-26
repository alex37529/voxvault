"""Диктофон — распознавание речи в текст (VOSK, офлайн, много языков).

Точка входа. Вся логика — в пакете dictophone (папка src/):
  - cli.py        — ArgumentParser, настройки, роутинг команд
  - models.py     — реестр VOSK, скачивание, загрузка моделей
  - transcribe.py — аудио и распознавание (файл / микрофон)
  - config.py     — настройки пользователя (%APPDATA%\\dictophone\\config.json)
  - devices.py    — входные аудиоустройства (микрофоны)
  - console.py    — UTF-8 в консоли

Команды:
  list      список доступных языков и моделей
  devices   список микрофонов
  config    показать/изменить настройки
  download  скачать модель             (--lang, --size)
  file      распознать аудиофайл       (--lang, --size, -o, --words)
  mic       realtime с микрофона       (--lang, --size, --device, -o)

После `pip install .` доступна команда `dictophone` без этого файла.
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def main() -> None:
    from dictophone.cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
