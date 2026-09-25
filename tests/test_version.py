"""Версия проекта: единый источник правды, чтобы не расходилась.

Версия нужна в трёх местах: `pyproject.toml` (метаданные пакета),
`dictophone.__version__` (about/диагностика) и `version_info.txt`
(ресурс exe, который читает PyInstaller). Расхождение ломает и релиз,
и «О программе», поэтому фиксируем тестом.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from dictophone import __version__

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
VERSION_INFO = ROOT / "packaging" / "build" / "version_info.txt"


def _pyproject_version() -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert match, "в pyproject.toml нет version = \"...\""
    return match.group(1)


class TestVersion:
    def test_pyproject_matches_package(self):
        assert _pyproject_version() == __version__

    def test_version_is_release(self):
        assert re.fullmatch(r"\d+\.\d+\.\d+", __version__), __version__

    def test_pep440_compatible(self):
        """Имя пакета/версия идут в имя файла релиза и в тег Git."""
        assert __version__.replace(".", "") .isalnum()

    @pytest.mark.skipif(not VERSION_INFO.exists(), reason="нет version_info.txt")
    def test_version_info_resource_matches(self):
        text = VERSION_INFO.read_text(encoding="utf-8")
        tuples = re.findall(r"filevers=\(([^)]*)\)", text)
        assert tuples, "в version_info.txt нет filevers=(...)"
        for raw in tuples:
            parts = [p.strip() for p in raw.split(",") if p.strip()]
            assert ".".join(parts[:3]) == __version__, f"{raw} != {__version__}"
