"""Постобработка текста: регистр и пунктуация.

VOSK выдаёт «голый» текст — без заглавных букв и знаков препинания. Здесь
добавляется лёгкая эвристика (без тяжёлых зависимостей) и точка расширения:
если появится нейросетевая модель пунктуации (например `vosk-recasepunc`),
её можно подключить, реализовав интерфейс `PostProcessor` — остальной код
менять не придётся.

Честно о границах: без нейросети восстановление знаков препинания по
тексту без знаков — эвристика. Расставляем точки по длинным паузам
(границы сегментов), ставим заглавную в начале и после точки, добавляем
точку в конце. Точность — заметно ниже recasepunc, зато мгновенно и без
1.6 ГБ модели.
"""

from __future__ import annotations

from typing import Protocol, Sequence


class PostProcessor(Protocol):
    """Интерфейс постобработки. Реализуйте — и подключите через set_backend."""

    def apply(self, text: str, segments: Sequence[str] = ()) -> str: ...


def _capitalize(sentence: str) -> str:
    for i, ch in enumerate(sentence):
        if ch.isalpha():
            return sentence[:i] + ch.upper() + sentence[i + 1 :]
        if ch.isdigit():
            continue
    return sentence


def heuristic(text: str, segments: Sequence[str] = ()) -> str:
    """Эвристика: регистр + точки на границах сегментов + точка в конце.

    Запятые намеренно НЕ расставляются: без синтаксического разбора любое
    правило даёт мусор вроде «Как, дела». Для нормальных запятых нужна
    нейросетевая модель (vosk-recasepunc) — подключается через set_backend.
    """
    if not text or not text.strip():
        return text

    # Конец сегмента — вероятная граница предложения.
    if segments:
        parts = [s.strip() for s in segments if s and s.strip()]
    else:
        parts = [p for p in text.split("  ") if p.strip()] or [text.strip()]

    sentences = [_capitalize(part.rstrip(" ,;:-")) for part in parts if part.strip()]
    text = ". ".join(s for s in sentences if s)
    if text and not text.endswith((".", "!", "?", "…")):
        text += "."
    return text


class IdentityPostProcessor:
    """Ничего не делает — режим «как распознал VOSK»."""

    def apply(self, text: str, segments: Sequence[str] = ()) -> str:  # noqa: ARG002 - сигнатура общая для всех постпроцессоров
        return text


class FunctionPostProcessor:
    """Адаптер: оборачивает функцию в интерфейс PostProcessor."""

    def __init__(self, fn):
        self._fn = fn

    def apply(self, text: str, segments: Sequence[str] = ()) -> str:
        return self._fn(text, segments)

    def __repr__(self) -> str:
        return f"FunctionPostProcessor({getattr(self._fn, '__name__', self._fn)})"


_backend: PostProcessor = FunctionPostProcessor(heuristic)


def set_backend(processor: PostProcessor) -> None:
    """Подменить реализацию (например, на нейросетевую модель пунктуации)."""
    global _backend
    _backend = processor


def get_backend() -> PostProcessor:
    return _backend


def apply(text: str, segments: Sequence[str] = (), enabled: bool = True) -> str:
    """Применить текущий бэкенд (или ничего, если enabled=False)."""
    if not enabled:
        return text
    return _backend.apply(text, segments)


#: Имена режимов для настройки/CLI.
MODES: dict[str, PostProcessor] = {
    "off": IdentityPostProcessor(),
    "heuristic": FunctionPostProcessor(heuristic),
}


def get_mode(name: str) -> PostProcessor:
    """Получить постобработчик по имени режима (для настроек/CLI)."""
    key = (name or "heuristic").lower()
    if key not in MODES:
        from .config import ConfigError

        raise ConfigError(
            f"Неизвестный режим постобработки: {name!r}. "
            f"Допустимо: {', '.join(sorted(MODES))}"
        )
    return MODES[key]
