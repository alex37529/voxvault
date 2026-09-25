"""Упаковка: инварианты spec-файла и генератора версии.

Полная сборка exe занимает минуты и требует PyInstaller, поэтому здесь
проверяются быстрые вещи, которые чаще всего ломают релиз:

  - spec кладёт словари внутрь (без них exe стартует по-английски);
  - spec не тянет `models/` (1,8 ГБ в релизе — недопустимо);
  - spec не включает numpy (проект его не использует);
  - версия для ресурсов exe совпадает с версией пакета.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "packaging" / "VoxVault.spec"
BUILD_PY = ROOT / "packaging" / "build.py"
LAUNCHER = ROOT / "packaging" / "launcher.py"


def _load_build_module():
    spec = importlib.util.spec_from_file_location("vx_build", BUILD_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestSpec:
    def test_spec_exists(self):
        assert SPEC.exists(), "нет packaging/VoxVault.spec"

    def test_onedir_is_default(self):
        """По умолчанию — папка: быстрый старт, меньше срабатываний антивирусов."""
        text = SPEC.read_text(encoding="utf-8")
        assert "COLLECT(" in text, "ожидается onedir-сборка (COLLECT)"
        assert 'os.environ.get("VOXVAULT_ONEFILE") == "1"' in text
        assert not re.search(r"onefile\s*=\s*True", text)

    def test_onefile_is_opt_in(self):
        """Один файл собирается только по флагу `--onefile`."""
        text = SPEC.read_text(encoding="utf-8")
        assert "if ONEFILE:" in text
        assert "exclude_binaries=True" in text, "onedir должен исключать бинарники из exe"

    def test_console_disabled(self):
        text = SPEC.read_text(encoding="utf-8")
        assert "console=False" in text, "GUI-приложение собираем без консоли"

    def test_upx_disabled(self):
        """UPX → ложные срабатывания антивирусов на Qt DLL."""
        text = SPEC.read_text(encoding="utf-8")
        assert "upx=False" in text

    def test_locales_bundled(self):
        text = SPEC.read_text(encoding="utf-8")
        assert "dictophone/locales" in text, "словари переводов должны попасть в сборку"

    def test_models_not_bundled(self):
        """Каталог моделей не должен попадать в datas/binaries."""
        text = SPEC.read_text(encoding="utf-8")
        data_block = text.split("datas=[", 1)[1].split("]", 1)[0]
        binaries_block = text.split("binaries=", 1)[1].split("\n", 1)[0]
        assert "models" not in data_block
        assert "models" not in binaries_block

    def test_numpy_excluded(self):
        text = SPEC.read_text(encoding="utf-8")
        excludes = text.split("excludes=[", 1)[1].split("]", 1)[0]
        assert "numpy" in excludes

    def test_vosk_and_sounddevice_collected(self):
        text = SPEC.read_text(encoding="utf-8")
        assert "collect_all(\"vosk\")" in text
        assert "collect_all(\"sounddevice\")" in text

    def test_certifi_bundled(self):
        """Без cacert.pem скачивание моделей падает с SSL-ошибкой."""
        text = SPEC.read_text(encoding="utf-8")
        assert "certifi" in text


class TestVersionResource:
    def test_version_matches_package(self):
        from dictophone import __version__

        build = _load_build_module()
        assert build.app_version() == __version__

    def test_rendered_resource_contains_version(self):
        from dictophone import __version__

        build = _load_build_module()
        text = build.render_version_info(__version__)
        assert f"filevers=({__version__.replace('.', ', ')}," in text
        assert "VoxVault" in text

    def test_version_file_pads_to_four_parts(self):
        """Windows требует filevers из четырёх чисел: X.Y.Z.W."""
        build = _load_build_module()
        text = build.render_version_info("1.2.3")
        assert "filevers=(1, 2, 3, 0,)" in text

    def test_bad_version_raises(self, tmp_path, monkeypatch):
        build = _load_build_module()
        fake = tmp_path / "src" / "dictophone" / "__init__.py"
        fake.parent.mkdir(parents=True)
        fake.write_text("# без версии\n", encoding="utf-8")
        monkeypatch.setattr(build, "ROOT", tmp_path)
        with pytest.raises(SystemExit):
            build.app_version()


class TestConsoleEncoding:
    """Скрипты сборки печатают по-русски — и должны не падать на CI.

    Регрессия: на раннерах GitHub Actions кодировка консоли cp1252, и
    `print("Иконка не найдена...")` ронял сборку UnicodeEncodeError. Сборка
    доходила до этого места всегда: `assets/*.ico` в git не попадает, и
    иконку всегда генерирует CI.
    """

    SCRIPTS = ("build.py", "make_icon.py")

    @staticmethod
    def _run(script: str, *args: str):
        import os
        import subprocess
        import sys

        env = dict(os.environ, PYTHONIOENCODING="cp1252", PYTHONUTF8="0")
        return subprocess.run(
            [sys.executable, f"packaging/{script}", *args],
            cwd=str(ROOT), env=env, capture_output=True,
        )

    @pytest.mark.parametrize("script", SCRIPTS)
    def test_scripts_call_setup_console(self, script):
        text = (ROOT / "packaging" / script).read_text(encoding="utf-8")
        assert "setup_console()" in text, f"{script} не переключает вывод в UTF-8"

    def test_spec_calls_setup_console(self):
        """Spec исполняется в процессе PyInstaller — там тоже cp1252."""
        text = SPEC.read_text(encoding="utf-8")
        assert "setup_console()" in text, "spec не переключает вывод в UTF-8"

    def test_child_env_forces_utf8(self):
        """Дочерние процессы не должны наследовать кодировку пользователя."""
        build = _load_build_module()
        env = build._child_env()
        assert env["PYTHONIOENCODING"] == "utf-8"
        assert env["PYTHONUTF8"] == "1"

    def test_build_help_survives_non_utf8_console(self):
        """`--help` печатает кириллическое описание argparse — тоже должно."""
        result = self._run("build.py", "--help")
        assert result.returncode == 0, result.stderr.decode("cp1252", "replace")

    def test_make_icon_survives_non_utf8_console(self, tmp_path):
        result = self._run("make_icon.py")
        assert result.returncode == 0, result.stderr.decode("cp1252", "replace")

    def test_console_setup_fixes_cyrillic_output(self):
        """Сам механизм: после setup_console() кириллица печатается в cp1252-консоль."""
        import os
        import subprocess
        import sys

        code = (
            "import sys; sys.path.insert(0, 'src')\n"
            "from dictophone.console import setup_console\n"
            "setup_console()\n"
            "print('Иконка не найдена, генерирую...')\n"
        )
        env = dict(os.environ, PYTHONIOENCODING="cp1252", PYTHONUTF8="0")
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=str(ROOT), env=env,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr.decode("cp1252", "replace")
        assert "Иконка" in result.stdout.decode("utf-8", "replace")


class TestLauncher:
    def test_launcher_exists(self):
        assert LAUNCHER.exists()

    def test_launcher_gui_by_default(self):
        text = LAUNCHER.read_text(encoding="utf-8")
        assert "gui_qt" in text
        assert re.search(r"if args:", text), "без аргументов должен открываться GUI"

    def test_launcher_does_not_bundle_models(self):
        text = LAUNCHER.read_text(encoding="utf-8")
        assert "models" not in text.lower() or "НЕ" in text
