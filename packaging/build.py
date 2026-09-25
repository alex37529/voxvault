"""Сборка VoxVault: ресурсы → PyInstaller → проверки → zip для GitHub.

    python packaging/build.py            # собрать dist/VoxVault/
    python packaging/build.py --zip      # ещё и dist/VoxVault-<version>-win64.zip
    python packaging/build.py --clean    # вычистить build/ и dist/ перед сборкой

Проверки после сборки намеренные: они ловят именно те ошибки, из-за которых
релиз уезжает к пользователю сломанным.

  1. exe существует;
  2. в сборке НЕТ каталога моделей (1,8 ГБ не должны попасть в релиз);
  3. словари переводов на месте (иначе приложение молча стартует по-английски);
  4. есть DLL Vosk и PortAudio (иначе не заработает микрофон/распознавание).
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

PACKAGING = ROOT / "packaging"
BUILD = PACKAGING / "build"
DIST = ROOT / "dist"
ICON = PACKAGING / "assets" / "VoxVault.ico"
VERSION_FILE = BUILD / "version_info.txt"
SPEC = PACKAGING / "VoxVault.spec"

MIN_PYTHON = (3, 9)
#: PyInstaller отстаёт от свежих релизов Python; на неподдержанной версии
#: сборка падает странными ошибками в bootloader, поэтому проверяем заранее.
KNOWN_GOOD_PYTHON = ((3, 9), (3, 10), (3, 11), (3, 12), (3, 13))


def app_version() -> str:
    text = (ROOT / "src" / "dictophone" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not match:
        raise SystemExit("Не найден __version__ в src/dictophone/__init__.py")
    return match.group(1)


def render_version_info(version: str) -> str:
    """Windows-ресурс версии для exe (Properties → Details)."""
    parts = [int(p) for p in version.split(".")]
    while len(parts) < 4:
        parts.append(0)
    quad = ", ".join(str(p) for p in parts[:4])
    return f"""# Сгенерировано packaging/build.py — правь версию в src/dictophone/__init__.py
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({quad},),
    prodvers=({quad},),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', 'VoxVault'),
         StringStruct('FileDescription', 'VoxVault - offline speech recognition'),
         StringStruct('FileVersion', '{version}'),
         StringStruct('InternalName', 'VoxVault'),
         StringStruct('LegalCopyright', 'Apache-2.0'),
         StringStruct('OriginalFilename', 'VoxVault.exe'),
         StringStruct('ProductName', 'VoxVault'),
         StringStruct('ProductVersion', '{version}')])
    ]),
    VarFileInfo([VarStruct('Translation', [1049, 1200])])
  ]
)
"""


def check_environment() -> None:
    if sys.version_info[:2] < MIN_PYTHON:
        raise SystemExit(f"Нужен Python >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]}")
    if sys.version_info[:2] not in KNOWN_GOOD_PYTHON:
        print(
            "ВНИМАНИЕ: сборка на незнакомой версии Python "
            f"{sys.version_info.major}.{sys.version_info.minor}. "
            "PyInstaller может не собрать bootloader.",
            file=sys.stderr,
        )
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        raise SystemExit(
            "Не установлен PyInstaller.\n"
            '  py -m pip install -e ".[dev]"   # или: py -m pip install pyinstaller'
        )
    try:
        import PySide6  # noqa: F401
    except ImportError:
        raise SystemExit(
            "Не установлен PySide6-Essentials.\n"
            '  py -m pip install -e ".[gui]"'
        )


def _child_env() -> dict[str, str]:
    """Окружение для дочерних процессов (PyInstaller, make_icon).

    Раньше они наследовали кодировку пользователя, и на CI (cp1252) или
    при `PYTHONIOENCODING=cp1252` падали на любом русском тексте — в том числе
    внутри spec-файла, который исполняется в процессе PyInstaller.
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def prepare(version: str) -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    VERSION_FILE.write_text(render_version_info(version), encoding="utf-8")
    if not ICON.exists():
        print("Иконка не найдена, генерирую...")
        subprocess.run(
            [sys.executable, str(PACKAGING / "make_icon.py")],
            check=True, env=_child_env(),
        )
    # Кириллица в пути ломает вывод и часть сборщиков — предупреждаем.
    if not str(ROOT).isascii():
        print(
            "ВНИМАНИЕ: путь проекта содержит не-ASCII символы. "
            "PyInstaller и VOSK к такому пути чувствительны — "
            "лучше собирать из папки с латинским именем.",
            file=sys.stderr,
        )


def run_pyinstaller(onefile: bool = False) -> None:
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath", str(DIST),
        "--workpath", str(BUILD / "work"),
        str(SPEC),
    ]
    env = _child_env()
    if onefile:
        env["VOXVAULT_ONEFILE"] = "1"
    else:
        env.pop("VOXVAULT_ONEFILE", None)
    print("$", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=str(ROOT), env=env)


def _dir_size_mb(path: Path) -> float:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1024 / 1024


def verify(version: str) -> Path:
    dist_dir = DIST / "VoxVault"
    exe = dist_dir / "VoxVault.exe"
    problems: list[str] = []

    if not exe.exists():
        problems.append(f"не собран exe: {exe}")

    # 1. Модели не должны попасть в релиз.
    for marker in ("models", "vosk-model-small-ru-0.22", "vosk-model-ru-0.42"):
        if (dist_dir / marker).exists():
            problems.append(f"в сборку попал каталог/файл модели: {marker}")

    # 2. Словари: без них интерфейс молча падает на английский.
    locales = list(dist_dir.rglob("locales/*.json"))
    if not locales:
        problems.append("не найдены словари переводов (locales/*.json)")

    # 2a. Qt-переводы (*.qm) не используются — их быть не должно.
    qm = list(dist_dir.rglob("*.qm"))
    if qm:
        problems.append(
            f"в сборке {len(qm)} Qt-переводов (*.qm), они не используются: "
            f"{qm[0].name}"
        )

    # 3. Нативные библиотеки VOSK и PortAudio.
    if not list(dist_dir.rglob("vosk*.pyd")) and not list(dist_dir.rglob("libvosk*")):
        problems.append("не найдена библиотека VOSK")
    if not list(dist_dir.rglob("portaudio*.dll")) and not list(dist_dir.rglob("*.dll")):
        problems.append("похоже, нет ни одной DLL (PortAudio/Qt)")

    size = _dir_size_mb(dist_dir) if dist_dir.exists() else 0.0
    print()
    print(f"Сборка: {dist_dir}")
    print(f"Размер: {size:.1f} МБ")
    print(f"Переводов: {len(locales)}")
    print(f"Версия: {version}")

    if problems:
        print("\nПРОБЛЕМЫ СБОРКИ:", file=sys.stderr)
        for item in problems:
            print(f"  - {item}", file=sys.stderr)
        raise SystemExit(1)
    return dist_dir


def verify_onefile(version: str) -> Path:
    """Проверка сборки в один файл: `_internal` быть не должно, модели — нет."""
    exe = DIST / "VoxVault.exe"
    problems: list[str] = []
    if not exe.exists():
        problems.append(f"не собран exe: {exe}")
    if (DIST / "_internal").exists():
        problems.append("в onefile-сборке не должно быть каталога _internal")
    if (DIST / "models").exists() and any((DIST / "models").iterdir()):
        problems.append("в onefile-сборке попали модели")
    size = exe.stat().st_size / 1024 / 1024 if exe.exists() else 0.0
    print()
    print(f"Сборка (onefile): {exe}")
    print(f"Размер: {size:.1f} МБ")
    print(f"Версия: {version}")
    print("ВНИМАНИЕ: при каждом запуске содержимое распаковывается во временный")
    print("каталог — старт медленнее, чем у папки, и чаще срабатывает антивирус.")
    if problems:
        print("\nПРОБЛЕМЫ СБОРКИ:", file=sys.stderr)
        for item in problems:
            print(f"  - {item}", file=sys.stderr)
        raise SystemExit(1)
    return exe


def make_zip(dist_dir: Path, version: str) -> Path:
    """Zip для GitHub Releases: один файл, качать проще, чем папку."""
    zip_path = DIST / f"VoxVault-{version}-win64.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(dist_dir.rglob("*")):
            if path.is_file():
                zf.write(path, Path("VoxVault") / path.relative_to(dist_dir))
    print(f"\nАрхив для релиза: {zip_path} "
          f"({zip_path.stat().st_size / 1024 / 1024:.1f} МБ)")
    return zip_path


def clean() -> None:
    for path in (DIST, BUILD / "work"):
        if path.exists():
            print(f"Удаляю {path}")
            shutil.rmtree(path, ignore_errors=True)


def main() -> int:
    # UTF-8 ДО первого вывода: на раннерах GitHub Actions кодировка консоли
    # cp1252, и любой русский текст (в т.ч. description argparse при --help)
    # роняет сборку UnicodeEncodeError. Тот же приём, что в cli.main().
    from dictophone.console import setup_console

    setup_console()

    parser = argparse.ArgumentParser(description="Сборка VoxVault")
    parser.add_argument("--zip", action="store_true",
                        help="сделать zip для GitHub Releases")
    parser.add_argument("--onefile", action="store_true",
                        help="один exe вместо папки (медленный старт, "
                             "ложные срабатывания антивирусов)")
    parser.add_argument("--clean", action="store_true",
                        help="вычистить build/ и dist/ перед сборкой")
    args = parser.parse_args()

    check_environment()
    version = app_version()
    if args.clean:
        clean()
    prepare(version)
    run_pyinstaller(onefile=args.onefile)
    if args.onefile:
        verify_onefile(version)
    else:
        dist_dir = verify(version)
        if args.zip:
            make_zip(dist_dir, version)
    print("\nГотово.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
