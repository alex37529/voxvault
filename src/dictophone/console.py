"""Настройка консоли: UTF-8, чтобы русский текст не превращался в кракозябры.

Windows-консоль по умолчанию живёт в cp866/cp1251. Нужен и смена кодовой
страницы консоли (иначе байты UTF-8 она отрисует как мусор), и перевод
стандартных потоков на UTF-8.
"""
from __future__ import annotations

import sys


def setup_console() -> None:
    """Перевести консоль и stdout/stderr в UTF-8. Безопасно при отсутствии консоли."""
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleOutputCP(65001)
            kernel32.SetConsoleCP(65001)
        except Exception:
            pass  # нет консоли (GUI-запуск, перенаправление) — не критично
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass  # поток не поддерживает reconfigure — тоже не критично
