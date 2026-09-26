"""Перевод интерфейса: загрузка словарей, подстановки, выбор языка.

Словари — по файлу на язык в каталоге `locales/`. Ключи стабильные
(идентификаторы с точками), НЕ исходные строки: иначе любая правка русского
текста ломает переводы.

Плейсхолдеры вида {name} подставляются через str.format.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable, Optional

LOCALES_DIR = Path(__file__).resolve().parent / "locales"
FALLBACK = "en"


def _detect_locales_dir() -> Path:
    """Каталог словарей: в собранном exe он лежит не рядом с `i18n.py`.

    PyInstaller кладёт данные в `sys._MEIPASS`, а модуль — в замороженный
    архив, поэтому `Path(__file__).parent` может указывать не туда. Без
    этого приложение в exe стартует без переводов.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        frozen = Path(meipass) / "dictophone" / "locales"
        if frozen.is_dir():
            return frozen
    return LOCALES_DIR


LOCALES_DIR = _detect_locales_dir()

#: LANGID Windows -> код языка интерфейса (для автоопределения).
_WIN_LANGID = {
    0x0419: "ru",  # русский
    0x0423: "be",
    0x0422: "uk",  # украинский
    0x0409: "en",  # английский (США)
    0x0809: "en",  # английский (Великобритания)
    0x0407: "de",  # немецкий
    0x040C: "fr",  # французский
    0x0410: "it",  # итальянский
    0x0C0A: "es",  # испанский
    0x0804: "zh",
}


def available() -> list[str]:
    """Языки, для которых есть словарь (по файлам в locales/)."""
    if not LOCALES_DIR.is_dir():
        return []
    return sorted(p.stem for p in LOCALES_DIR.glob("*.json"))


def windows_lang() -> Optional[str]:
    """Код языка интерфейса Windows или None (не-Windows / не удалось)."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return _WIN_LANGID.get(int(langid))
    except Exception:
        return None


def detect_system_lang() -> str:
    """Язык по умолчанию: язык Windows -> из словарей -> english.

    ВНИМАНИЕ: на машине с английской Windows вернётся 'en', даже если
    пользователь русскоязычный. Поэтому автоопределение — это предложение,
    а в настройках язык выбирается явно.
    """
    win = windows_lang()
    langs = available()
    if win and win in langs:
        return win
    return FALLBACK if FALLBACK in langs else (langs[0] if langs else FALLBACK)


def _load_file(lang: str) -> dict[str, str]:
    path = LOCALES_DIR / f"{lang}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"Не удалось прочитать перевод {lang}: {e}") from None
    if not isinstance(data, dict):
        raise ValueError(f"Ожидался JSON-объект в {path}")
    return data


def lang_name(tr: Callable[..., str], code: str) -> str:
    """Название языка распознавания по переводу; нет перевода — сам код.

    Языки распознавания (ru, en-us, el-gr...) и языки интерфейса — разные
    наборы, поэтому перевода может не быть: тогда показываем код, как
    делает выбор модели.
    """
    key = f"lang.{code}"
    text = tr(key)
    return code if text == key else text


class I18n:
    """Текущий язык интерфейса и доступ к переводам."""

    def __init__(self, lang: Optional[str] = None) -> None:
        self._cache: dict[str, dict[str, str]] = {}
        self._fallback: dict[str, str] = {}
        self._lang = FALLBACK
        if FALLBACK in available():
            self._fallback = self._load(FALLBACK)
        self.set_lang(lang or detect_system_lang())

    # -- загрузка ----------------------------------------------------------
    def _load(self, lang: str) -> dict[str, str]:
        if lang not in self._cache:
            self._cache[lang] = _load_file(lang)
        return self._cache[lang]

    def set_lang(self, lang: str) -> None:
        """Сменить язык. Неизвестный код — с тихим откатом на english."""
        if lang in available():
            self._lang = lang
        else:
            self._lang = FALLBACK if FALLBACK in available() else (available() or [FALLBACK])[0]

    def preload(self) -> None:
        """Заранее прочитать все словари — переключение языка станет мгновенным."""
        for lang in available():
            try:
                self._load(lang)
            except ValueError:
                continue  # битый словарь не должен ломать запуск

    @property
    def lang(self) -> str:
        return self._lang

    @property
    def is_rtl(self) -> bool:
        """Нужно ли отражать интерфейс справа налево."""
        return self._lang in ("ar", "he", "fa")

    # -- перевод -----------------------------------------------------------
    def t(self, key: str, /, **kwargs: Any) -> str:
        """Перевод по ключу; при отсутствии — english, затем сам ключ.

        Никогда не бросает: незаполненный перевод не должен ронять интерфейс.
        """
        text = self._table().get(key)
        if text is None:
            text = self._fallback.get(key)
        if text is None:
            text = key
        if kwargs:
            try:
                return text.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                return text
        return text

    def _table(self) -> dict[str, str]:
        try:
            return self._load(self._lang)
        except ValueError:
            return self._fallback

    # -- проверки целостности (для тестов) ---------------------------------
    def keys_of(self, lang: str) -> set[str]:
        return set(_load_file(lang))

    def placeholders(self, lang: str) -> dict[str, set[str]]:
        """Ключ -> множество имён плейсхолдеров {…}."""
        import re

        pattern = re.compile(r"\{(\w+)\}")
        return {
            key: set(pattern.findall(text))
            for key, text in _load_file(lang).items()
        }
