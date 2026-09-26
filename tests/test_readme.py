"""README на трёх языках: взаимные ссылки и синхронная структура.

Русская, английская и китайская версии описывают один и тот же продукт.
Если они разойдутся (потеряется раздел, команда, язык в таблице), это будет
незаметно для разработчика, но заметно для пользователя — поэтому проверяем.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
#: код языка интерфейса → файл README
#: Английский — основной README.md в корне, переводы лежат в docs/.
README_FILES = {
    "en": ROOT / "README.md",
    "ru": ROOT / "docs" / "README.ru.md",
    "zh": ROOT / "docs" / "README.zh.md",
}

#: Скриншот приложения в hero-секции.
SCREENSHOT = ROOT / "docs" / "screen.png"
LICENSE = ROOT / "LICENSE"

#: Файлы, о которых должны знать все версии.
KEY_FILES = (
    "VoxVault.spec",
    "build.py",
    "launcher.py",
    "single_instance.py",
    "app_icon.py",
    "qt_history.py",
    "qt_model_dialog.py",
    "release.yml",
    "LICENSE",
)

#: Кириллица допустима только в переключателе языка и в примере не-ASCII пути.
ALLOWED_CYRILLIC = {"Русский", "диктофон"}


@pytest.fixture(scope="module")
def texts():
    return {code: path.read_text(encoding="utf-8") for code, path in README_FILES.items()}


class TestLanguageSwitch:
    def test_all_readmes_exist(self):
        for code, path in README_FILES.items():
            assert path.exists(), f"нет README для {code}: {path}"

    def test_every_version_links_to_all_others(self, texts):
        """Ссылки переключателя должны вести в СУЩЕСТВУЮЩИЕ файлы.

        Проверяем именно href относительно папки README, а не подстроку:
        после переноса переводов в docs/ относительные пути разные, и
        ошибка «docs/docs/README.ru.md» подстрокой не ловится.
        """
        for code, text in texts.items():
            here = README_FILES[code].parent
            links = re.findall(r"\[([^\]]+)\]\(([^)]+\.md)\)", text)
            targets = {
                os.path.normpath(str((here / target).resolve())) for _, target in links
            }
            for other, path in README_FILES.items():
                if other == code:
                    continue
                assert os.path.normpath(str(path.resolve())) in targets, (
                    f"README {code}: нет рабочей ссылки на {other} "
                    f"({path.relative_to(ROOT).as_posix()})"
                )

    def test_no_broken_relative_links(self, texts):
        """Любая относительная ссылка на файл должна существовать."""
        for code, text in texts.items():
            here = README_FILES[code].parent
            for target in re.findall(r"(?:href|src)=\"([^\"]+)\"", text):
                if target.startswith(("http://", "https://")):
                    continue
                resolved = (here / target).resolve()
                assert resolved.exists(), f"README {code}: битая ссылка {target}"

    def test_screenshot_next_to_translated_readmes(self, texts):
        """Переводы лежат в docs/, поэтому скриншот у них рядом — `screen.png`."""
        for code in ("ru", "zh"):
            assert SCREENSHOT.parent == README_FILES[code].parent
            assert 'src="screen.png"' in texts[code], code

    def test_current_version_marked_active(self, texts):
        """В переключателе текущий язык не должен быть ссылкой."""
        active = {"ru": "**Русский**", "en": "**English**", "zh": "**简体中文**"}
        for code, text in texts.items():
            head = text.splitlines()[2]
            assert active[code] in head, f"в README {code} нет активной метки"


class TestStructure:
    def test_same_number_of_sections(self, texts):
        counts = {
            code: len(re.findall(r"^## (.+)$", text, re.MULTILINE))
            for code, text in texts.items()
        }
        assert len(set(counts.values())) == 1, f"разное число разделов: {counts}"

    def test_same_number_of_subsections(self, texts):
        counts = {
            code: len(re.findall(r"^### ", text, re.MULTILINE))
            for code, text in texts.items()
        }
        assert len(set(counts.values())) == 1, f"разное число подразделов: {counts}"

    def test_same_commands(self, texts):
        sets = {
            code: set(re.findall(r"\bdictophone [a-z-]+", text))
            for code, text in texts.items()
        }
        base = sets["ru"]
        for code, found in sets.items():
            assert found == base, (
                f"{code}: команды отличаются\n"
                f"  только в ru: {sorted(base - found)}\n"
                f"  только в {code}: {sorted(found - base)}"
            )

    def test_key_files_mentioned_everywhere(self, texts):
        for code, text in texts.items():
            for name in KEY_FILES:
                assert name in text, f"{name} не упомянут в README {code}"

    def test_build_instructions_present(self, texts):
        for code, text in texts.items():
            assert "packaging\\build.py" in text, code
            assert "--selftest" in text, code
            assert "--onefile" in text, code

    def test_all_readmes_listed_in_structure(self, texts):
        """В блоке структуры переводы перечислены внутри каталога docs/."""
        for code, text in texts.items():
            for path in README_FILES.values():
                assert path.name in text, f"{path.name} нет в структуре README {code}"
            assert "docs/" in text, code
            assert "screen.png" in text, code


class TestHeroSection:
    """Шапка README: бейджи и скриншот приложения."""

    #: Бейджи, которые обязаны быть в каждой версии.
    REQUIRED_BADGES = (
        "license-Apache--2.0",
        "version-",
        "Windows%20x64",
        "python-3.9",
        "PySide6",
        "VOSK",
        "offline",
    )

    def test_screenshot_file_exists(self):
        assert SCREENSHOT.exists(), "нет docs/screen.png"
        assert SCREENSHOT.stat().st_size > 5_000, "скриншот подозрительно маленький"

    def test_screenshot_embedded_everywhere(self, texts):
        """Путь к скриншоту разрешается относительно папки самого README."""
        for code, text in texts.items():
            here = README_FILES[code].parent
            src = re.search(r'<img src="([^"]*screen\.png)"', text)
            assert src, f"README {code}: нет тега со скриншотом"
            assert (here / src.group(1)).resolve() == SCREENSHOT.resolve(), (
                f"README {code}: скриншот указывает на {src.group(1)}"
            )

    def test_badges_present_everywhere(self, texts):
        for code, text in texts.items():
            for badge in self.REQUIRED_BADGES:
                assert badge in text, f"README {code}: нет бейджа {badge}"

    def test_badges_use_centered_html(self, texts):
        """Центрирование делается через <p align="center"> — GitHub это умеет."""
        for code, text in texts.items():
            assert '<p align="center">' in text, code
            assert "img.shields.io" in text, code

    def test_version_badge_matches_package(self, texts):
        """Бейдж версии обязан совпадать с __version__, иначе врёт."""
        from dictophone import __version__

        for code, text in texts.items():
            assert f"version-v{__version__}" in text, (
                f"README {code}: бейдж версии не совпадает с {__version__}"
            )

    def test_language_badges_match_code(self, texts):
        """Счётчики языков на бейджах — из кода, а не из головы."""
        from dictophone import models
        from dictophone.i18n import available

        ui = f"UI-{len(available())}%20languages"
        asr = f"ASR-{len(models.known_langs())}%20languages"
        for code, text in texts.items():
            assert ui in text, f"README {code}: бейдж языков интерфейса неверен"
            assert asr in text, f"README {code}: бейдж языков распознавания неверен"

    def test_license_badge_links_to_license_file(self, texts):
        """Бейдж лицензии ведёт на сам LICENSE с учётом вложенности папки."""
        for code, text in texts.items():
            here = README_FILES[code].parent
            href = re.search(
                r'<a href="([^"]+)"><img[^>]+src="https://img\.shields\.io'
                r"/badge/license-",
                text,
            )
            assert href, f"README {code}: нет бейджа лицензии"
            assert (here / href.group(1)).resolve() == LICENSE.resolve(), (
                f"README {code}: бейдж лицензии ведёт не на LICENSE"
            )


class TestRecognitionLanguages:
    """Таблица языков в README — это копия реестра models.MODELS.

    Реестр меняют чаще, чем README, а расхождение заметно только пользователю:
    он вводит `--lang`, которого «вроде бы» нет в списке.
    """

    @staticmethod
    def _rows(text: str) -> dict[str, tuple[str, str]]:
        """Строки таблицы языков: {code: (small, large)}.

        Разбирается ТОЛЬКО таблица под заголовком «Код/Code | small | large»:
        в README есть и другие таблицы с таким же числом колонок, и без
        ограничения они попадали бы сюда.
        """
        lines = text.splitlines()
        header = re.compile(r"^\|\s*(Код|Code|代码)\s*\|\s*small\s*\|\s*large\s*\|$")
        start = next((i for i, line in enumerate(lines) if header.match(line)), None)
        if start is None:
            return {}
        pattern = re.compile(r"^\|\s*`([a-z-]+)`\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|$")
        found: dict[str, tuple[str, str]] = {}
        for line in lines[start + 2 :]:  # +2 — пропуск строки разделителя
            if not line.startswith("|"):
                break
            match = pattern.match(line)
            if match:
                lang, small, large = match.groups()
                found[lang] = (small, large)
        return found

    @staticmethod
    def _expected() -> dict[str, tuple[str, str]]:
        from dictophone import models

        expected = {}
        for lang in models.known_langs():
            entry = models.MODELS[lang]
            expected[lang] = (
                f"`{entry.get('small')}`" if entry.get("small") else "—",
                f"`{entry.get('large')}`" if entry.get("large") else "—",
            )
        return expected

    def test_readme_rows_match_registry(self, texts):
        expected = self._expected()
        for code, text in texts.items():
            rows = self._rows(text)
            assert rows == expected, (
                f"README {code}: таблица языков разошлась с models.MODELS.\n"
                f"  лишние: {sorted(set(rows) - set(expected))}\n"
                f"  не хватает: {sorted(set(expected) - set(rows))}\n"
                f"  несовпадения: "
                f"{ {k: (v, expected.get(k)) for k, v in rows.items() if expected.get(k) != v} }"
            )

    def test_language_count_stated_correctly(self, texts):
        from dictophone import models

        count = str(len(models.known_langs()))
        for code, text in texts.items():
            # Китайский использует полноширинные скобки （33）, русский/английский — обычные (33)
            stated = f"({count})" in text or f"（{count}" in text
            assert stated, f"README {code}: не указано число языков ({count})"

    def test_interface_languages_listed(self, texts):
        """Языки интерфейса и языки распознавания — разные списки."""
        from dictophone.i18n import available

        for code, text in texts.items():
            missing = [lang for lang in available() if f"`{lang}`" not in text]
            assert not missing, f"README {code}: не указаны языки интерфейса {missing}"


class TestTranslations:
    """Каждая версия написана на своём языке и упоминает бренд."""

    #: Строка переключателя языков намеренно содержит названия на всех
    #: трёх языках — её надо исключать из проверок «своей» письменности.
    SWITCHER_LINE = 2

    @staticmethod
    def _body(text: str) -> str:
        lines = text.splitlines()
        return "\n".join(
            lines[: TestTranslations.SWITCHER_LINE]
            + lines[TestTranslations.SWITCHER_LINE + 1 :]
        )

    def test_brand_mentioned(self, texts):
        for code, text in texts.items():
            assert "VoxVault" in text, code

    def test_no_stray_cyrillic_in_foreign_versions(self, texts):
        """В английской и китаййской версиях кириллица — только в
        переключателе языка и в примере не-ASCII пути.

        Проверка ловит русские единицы измерения (МБ, ГБ, кГц), проскочившие
        в перевод, и омоглифы вида «МB» (кириллическая М + латинская B).
        """
        for code in ("en", "zh"):
            cyrillic = set(re.findall(r"[А-Яа-яЁё]+", self._body(texts[code])))
            assert cyrillic <= ALLOWED_CYRILLIC, (
                f"README {code}: неожиданная кириллица {cyrillic - ALLOWED_CYRILLIC}"
            )

    def test_no_mixed_script_words(self, texts):
        """Слова вида «МB»: кириллица и латиница в одном слове."""
        mixed = re.compile(r"[А-Яа-яЁё][A-Za-z]|[A-Za-z][А-Яа-яЁё]")
        for code, text in texts.items():
            found = mixed.findall(text)
            assert not found, f"README {code}: смешанная письменность {found}"

    def test_english_has_no_han_characters(self, texts):
        han = set(re.findall(r"[一-鿿]", self._body(texts["en"])))
        assert not han, f"в английском README есть китайские иероглифы: {han}"

    def test_russian_has_no_han_characters(self, texts):
        han = set(re.findall(r"[一-鿿]", self._body(texts["ru"])))
        assert not han, f"в русском README есть китайские иероглифы: {han}"

    def test_chinese_version_is_in_chinese(self, texts):
        han = re.findall(r"[一-鿿]", self._body(texts["zh"]))
        assert len(han) > 200, "китайская версия выглядит не переведённой"
