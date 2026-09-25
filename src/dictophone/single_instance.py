"""Одна копия приложения: запуск второй копии блокируется.

Зачем: две копии делят один и тот же `config.json`, одну `history.db`
(SQLite отдаст `database is locked`) и один каталог моделей. Вдобавок
пользователь получает два окна и две фоновые загрузки одной модели.

Реализация — `QLockFile` из QtCore: он держит файловую блокировку и PID,
поэтому после краша приложения «мёртвый» замок не блокирует запуск навсегда
(`setStaleLockTime(0)` — считать устаревшим только если процесса нет).

Если PySide6 недоступен (CLI без Qt, сборка, тесты ядра) — блокировка
не работает и разрешается всегда: лучше запустить, чем упасть.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

APP_ID = "VoxVault"

#: Аварийный выключатель блокировки (тесты, отладка, CI).
NO_LOCK_ENV = "VOXVAULT_NO_SINGLE_INSTANCE"


def lock_dir() -> Path:
    """Каталог для файла блокировки: пользовательский, не рядом с exe.

    Рядом с exe писать нельзя — в `Program Files` нет прав на запись.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    else:
        base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return Path(base) / APP_ID


class SingleInstance:
    """Замок на запуск. Использование как контекстный менеджер."""

    def __init__(self, app_id: str = APP_ID, path: Optional[Path] = None):
        self.app_id = app_id
        self._path = Path(path) if path is not None else lock_dir() / "run.lock"
        self._lock = None
        self.acquired = False

    @property
    def path(self) -> Path:
        return self._path

    def acquire(self) -> bool:
        """Занять замок. `False` — приложение уже запущено."""
        if os.environ.get(NO_LOCK_ENV):
            self.acquired = True
            return True
        lock = self._make_lock()
        if lock is None:               # Qt нет — не блокируем запуск
            self.acquired = True
            return True
        self._lock = lock
        if lock.tryLock(0):
            self.acquired = True
            return True
        self._lock = None
        return False

    def _make_lock(self):
        try:
            from PySide6 import QtCore
        except ImportError:
            return None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None                 # каталог недоступен — не блокируем
        lock = QtCore.QLockFile(str(self._path))
        lock.setStaleLockTime(0)
        return lock

    def release(self) -> None:
        if self._lock is not None:
            self._lock.unlock()
        self._lock = None
        self.acquired = False

    def __enter__(self) -> "SingleInstance":
        if not self.acquire():
            raise RuntimeError("Приложение уже запущено")
        return self

    def __exit__(self, *exc) -> None:
        self.release()
