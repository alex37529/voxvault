"""Настройка консоли: UTF-8, чтобы русский текст не превращался в кракозябры.

Windows-консоль по умолчанию живёт в cp866/cp1251. Нужен и смена кодовой
страницы консоли (иначе байты UTF-8 она отрисует как мусор), и перевод
стандартных потоков на UTF-8.
"""

from __future__ import annotations

import contextlib
import sys


def setup_console() -> None:
    """Перевести консоль и stdout/stderr в UTF-8. Безопасно при отсутствии консоли."""
    if sys.platform == "win32":
        # нет консоли (GUI-запуск, перенаправление) — не критично
        with contextlib.suppress(Exception):
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleOutputCP(65001)
            kernel32.SetConsoleCP(65001)
    for stream in (sys.stdout, sys.stderr):
        # поток не поддерживает reconfigure — тоже не критично
        with contextlib.suppress(Exception):
            reconfigure = getattr(stream, "reconfigure", None)
            if callable(reconfigure):
                reconfigure(encoding="utf-8", errors="replace")
