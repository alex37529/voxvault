"""Точка входа собранного приложения VoxVault.

Зачем отдельный файл, а не `main.py`: `main.py` — это CLI для разработки
(кладёт `src/` в `sys.path` и зовёт `cli.main`). В замороженном приложении
пакет лежит внутри exe, а пользователь по умолчанию хочет окно, а не
консоль со справкой.

Поведение:
  VoxVault.exe              → графическое приложение (без окна консоли)
  VoxVault.exe file a.wav   → CLI, вывод возвращается в консоль терминала

Модели НЕ вшиваются: приложение само скачивает их при первом запуске.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_importable() -> None:
    """В исходниках пакет лежит в `src/`; в сборке импортируется как есть."""
    src = Path(__file__).resolve().parent.parent / "src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))


def _console_usable() -> bool:
    """Есть ли уже пригодный поток вывода.

    Если вывод перенаправлен в файл или конвейер (пайп, CI, тесты) — трогать
    ничего не надо: писать надо туда же, куда ожидает вызывающий.
    """
    stream = sys.stdout
    if stream is None:
        return False
    try:
        return bool(stream.fileno())
    except Exception:  # noqa: BLE001 - поток без fileno (подмена в тестах)
        return False


def _attach_parent_console() -> None:
    """Обеспечить консоль для вывода CLI.

    `console=False` в PyInstaller не создаёт окно консоли, поэтому при запуске
    с аргументами выводить некуда. Порядок важен:

    1. уже есть пригодный stdout (файл/пайп) — оставляем как есть;
    2. `AttachConsole(-1)` — цепляемся к консоли терминала, из которого
       запустили (обычный случай);
    3. `AllocConsole()` — если запустили двойным щелчком, открываем своё окно,
       иначе пользователь не увидит результат вообще.
    """
    if sys.platform != "win32" or _console_usable():
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        attached = bool(kernel32.AttachConsole(-1))
        if not attached:
            kernel32.AllocConsole()
        for name in ("stdout", "stderr"):
            stream = open("CONOUT$", "w", encoding="utf-8", buffering=1)
            setattr(sys, name, stream)
    except Exception:  # noqa: BLE001 - без консоли живём: вывод, может, и некуда
        pass


def _selftest() -> int:
    """Диагностика сборки: что внутри exe и что с ним происходит.

    Нужна для проверки релиза на чистой Windows без Python: пользователь
    присылает вывод этой команды, и по нему видно, чего не хватает.

    Запуск: VoxVault.exe --selftest
    """
    import traceback

    from dictophone import __version__, i18n, models
    from dictophone.single_instance import SingleInstance

    checks: list[tuple[str, bool, str]] = []

    def check(name: str, func) -> None:
        try:
            detail = func()
            checks.append((name, True, str(detail)))
        except Exception as e:  # noqa: BLE001 - здесь любая ошибка informative
            checks.append((name, False, f"{type(e).__name__}: {e}"))

    print(f"VoxVault {__version__}")
    print(f"frozen      = {getattr(sys, 'frozen', False)}")
    print(f"executable  = {sys.executable}")
    print(f"_MEIPASS    = {getattr(sys, '_MEIPASS', None)}")
    print(f"python      = {sys.version.split()[0]}")

    check("import vosk", lambda: __import__("vosk").__file__)
    check("import sounddevice", lambda: __import__("sounddevice").__file__)
    check("языки интерфейса", lambda: ", ".join(i18n.available()))
    check("каталог моделей", lambda: models.DEFAULT_MODEL_DIR)
    check("каталог текстов", lambda: models.DEFAULT_OUTPUT_DIR)
    check("модели в каталоге", lambda: ", ".join(models.installed_langs()) or "нет")

    def qt_check() -> str:
        import os

        # offscreen, чтобы selftest работал и без интерактивного рабочего стола
        # (CI, сервер сборки) — проверяем, что Qt вообще инициализируется.
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6 import QtWidgets

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        return f"{app.platformName()}, Qt {QtCore_version()}"

    def QtCore_version() -> str:
        from PySide6 import QtCore

        return QtCore.__version__

    check("Qt инициализируется", qt_check)

    def taskbar_identity() -> str:
        from dictophone.app_icon import (
            APP_USER_MODEL_ID,
            set_app_user_model_id,
        )

        applied = set_app_user_model_id()
        return f"{APP_USER_MODEL_ID} (применён: {applied})"

    check("идентификатор панели задач", taskbar_identity)

    guard = SingleInstance()
    if guard.acquire():
        guard.release()
        lock_state = "свободен"
    else:
        lock_state = "занят другим процессом"
    check("замок единственного экземпляра", lambda: lock_state)

    print()
    failed = 0
    for name, ok, detail in checks:
        mark = "OK  " if ok else "FAIL"
        print(f"[{mark}] {name}: {detail}")
        if not ok:
            failed += 1
    print()
    print("Итог:", "всё в порядке" if not failed else f"проблем: {failed}")
    if failed:
        traceback.print_exc()
    return 1 if failed else 0


def main() -> int:
    _ensure_importable()
    args = sys.argv[1:]
    if args == ["--selftest"]:
        _attach_parent_console()
        from dictophone.console import setup_console

        setup_console()
        return _selftest()
    if args:
        # Аргументы есть — режим CLI, как у обычного `dictophone`.
        _attach_parent_console()
        from dictophone.console import setup_console

        setup_console()
        from dictophone.cli import main as cli_main

        cli_main(args)
        return 0
    from dictophone import gui_qt

    return gui_qt.main([])


if __name__ == "__main__":
    raise SystemExit(main())
