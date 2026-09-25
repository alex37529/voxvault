"""Dictophone — офлайн-распознавание речи в текст (VOSK).

Модули пакета:
  models     — реестр VOSK, скачивание и загрузка моделей
  transcribe — аудио и распознавание: файл (transcribe_file) и микрофон
               (iter_mic — поток событий, transcribe — фасад)
  cli        — ArgumentParser, настройки, роутинг команд
  config     — настройки пользователя (%APPDATA%\\dictophone\\config.json)
  devices    — входные аудиоустройства (микрофоны)

Пример использования как библиотеки:
    from pathlib import Path
    from dictophone.transcribe import transcribe
    text = transcribe(Path("audio.wav"), lang="ru", size="small")
"""
from __future__ import annotations

__version__ = "0.3.0"
__all__ = ["__version__"]
