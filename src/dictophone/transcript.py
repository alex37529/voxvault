"""Сборка живой расшифровки: закрытые сегменты + текущий незакрытый.

Модуль без GUI-тулкита: используется и tkinter-версией (gui.py), и Qt
(gui_qt.py), чтобы при удалении одной из них логика не потерялась.

Зачем: VOSK отдаёт поток partial-финалов, а показать надо «одну текущую
строку + накопленные закрытые». Если partial дописывать в текст, он
навсегда остаётся мусором в расшифровке.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

PARTIAL = "partial"
FINAL = "final"


@dataclass(frozen=True)
class SpeechEvent:
    """Событие распознавания: «на лету» (partial) или закрытый сегмент."""

    kind: str
    text: str


@dataclass
class TranscriptBuffer:
    """Состав видимой расшифровки.

    `partial` всегда один и каждый раз ЗАМЕНЯЕТСЯ, а не добавляется.
    `authoritative` — итоговый текст, который реально сохранён в файл; при его
    появлении весь показанный текст заменяется им, чтобы экран и файл не
    разошлись.
    """

    finals: list[str] = field(default_factory=list)
    partial: Optional[str] = None
    authoritative: Optional[str] = None

    def reset(self) -> None:
        self.finals.clear()
        self.partial = None
        self.authoritative = None

    def add_partial(self, text: str) -> None:
        """Новый незакрытый сегмент (заменяет предыдущий)."""
        self.partial = (text or "").strip() or None

    def add_final(self, text: str) -> None:
        """Сегмент закрыт — он становится постоянной строкой."""
        self.partial = None
        cleaned = (text or "").strip()
        if cleaned:
            self.finals.append(cleaned)

    def set_authoritative(self, text: str) -> None:
        """Итоговый текст (как в сохранённом файле).

        Незакрытый сегмент сбрасывается: после итога незавершённых partial'ов
        быть не может, и `has_partial` не должен противоречить `render()`.
        """
        self.authoritative = (text or "").strip()
        self.partial = None

    @property
    def has_partial(self) -> bool:
        return self.partial is not None

    @property
    def body(self) -> str:
        """Финальные строки — то, что должно остаться в расшифровке."""
        if self.authoritative is not None:
            return self.authoritative
        return "\n".join(self.finals)

    def render(self) -> tuple[str, bool]:
        """(текст для показа, является ли последняя строка незакрытой)."""
        if self.authoritative is not None:
            return self.authoritative, False
        body = self.body
        if self.partial:
            return (f"{body}\n{self.partial}" if body else self.partial), True
        return body, False

    def finalized(self) -> str:
        """Текст для сохранения: только закрытые сегменты."""
        if self.authoritative is not None:
            return self.authoritative
        return " ".join(self.finals).strip()
