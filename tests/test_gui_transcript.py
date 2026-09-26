"""Тесты живой расшифровки в GUI (TranscriptBuffer).

Регрессия: раньше partial-результат ДОПИСЫВАЛСЯ в поле текста и никогда не
заменялся, поэтому итоговая расшифровка засорялась серыми «(… )» хвостами.
Здесь проверяется, что незакрытый сегмент всегда один и всегда перезаписывается.
"""

from __future__ import annotations

import pytest

from dictophone.gui import TranscriptBuffer


class TestPartialDoesNotAccumulate:
    def test_partial_replaces_previous(self):
        buf = TranscriptBuffer()
        buf.add_partial("при")
        buf.add_partial("привет")
        buf.add_partial("привет мир")
        text, is_partial = buf.render()
        assert text == "привет мир"
        assert is_partial is True

    def test_no_parenthesis_scaffolding(self):
        """Старый баг печатал «(текст)» — такие хвосты в выводе не остаются."""
        buf = TranscriptBuffer()
        for chunk in ("раз", "два", "три"):
            buf.add_partial(chunk)
        text, _ = buf.render()
        assert "(" not in text and ")" not in text

    def test_many_partials_stay_single_line(self):
        buf = TranscriptBuffer()
        for i in range(200):
            buf.add_partial(f"слово {i}")
        text, is_partial = buf.render()
        assert text == "слово 199"
        assert text.count("\n") == 0
        assert is_partial is True


class TestFinalSegments:
    def test_final_is_persisted(self):
        buf = TranscriptBuffer()
        buf.add_partial("первый")
        buf.add_final("первый")
        text, is_partial = buf.render()
        assert text == "первый"
        assert is_partial is False

    def test_finals_stack_on_separate_lines(self):
        buf = TranscriptBuffer()
        buf.add_final("раз")
        buf.add_final("два")
        text, _ = buf.render()
        assert text == "раз\nдва"

    def test_partial_shows_below_finals(self):
        buf = TranscriptBuffer()
        buf.add_final("первый")
        buf.add_partial("второй пока")
        text, is_partial = buf.render()
        assert text == "первый\nвторой пока"
        assert is_partial is True

    def test_final_clears_pending_partial(self):
        """Закрытие сегмента убирает его «черновую» версию."""
        buf = TranscriptBuffer()
        buf.add_partial("черновик")
        buf.add_final("чистовик")
        text, is_partial = buf.render()
        assert text == "чистовик"
        assert "черновик" not in text
        assert is_partial is False

    def test_empty_finals_ignored(self):
        buf = TranscriptBuffer()
        buf.add_final("   ")
        buf.add_final("")
        assert buf.render()[0] == ""
        assert buf.finalized() == ""

    def test_finalized_excludes_partial(self):
        buf = TranscriptBuffer()
        buf.add_final("сохранённое")
        buf.add_partial("незакрытое")
        assert buf.finalized() == "сохранённое"


class TestAuthoritativeResult:
    def test_result_replaces_display(self):
        buf = TranscriptBuffer()
        buf.add_partial("черновик")
        buf.add_final("черновик")
        buf.set_authoritative("Итог. С двумя точками.")
        text, is_partial = buf.render()
        assert text == "Итог. С двумя точками."
        assert is_partial is False

    def test_result_is_what_gets_saved(self):
        """Экран и файл не должны расходиться."""
        buf = TranscriptBuffer()
        buf.add_final("раз")
        buf.add_final("два")
        buf.set_authoritative("Раз. Два.")
        assert buf.finalized() == buf.render()[0] == "Раз. Два."

    def test_result_clears_pending_partial(self):
        buf = TranscriptBuffer()
        buf.add_final("да")
        buf.add_partial("нет")
        buf.set_authoritative("Да.")
        assert buf.has_partial is False
        assert "нет" not in buf.render()[0]


class TestReset:
    def test_reset_clears_everything(self):
        buf = TranscriptBuffer()
        buf.add_final("раз")
        buf.add_partial("два")
        buf.set_authoritative("Раз.")
        buf.reset()
        assert buf.finals == []
        assert buf.partial is None
        assert buf.authoritative is None
        assert buf.render() == ("", False)
        assert buf.finalized() == ""

    def test_reuse_after_reset(self):
        buf = TranscriptBuffer()
        buf.add_final("старые")
        buf.reset()
        buf.add_final("новые")
        assert buf.render()[0] == "новые"


class TestSimulatedSession:
    """Сценарий живой сессии: partial-ы, finals, итог — без накопления мусора."""

    def test_full_session(self):
        buf = TranscriptBuffer()
        # сегмент 1: три черновика -> финал
        for chunk in ("при", "привет", "привет мир"):
            buf.add_partial(chunk)
        buf.add_final("привет мир")
        # сегмент 2: черновики, затем финал
        for chunk in ("сег", "сегодня", "сегодня хоро"):
            buf.add_partial(chunk)
        buf.add_final("сегодня хороший день")
        # незакрытый «хвост», потом итоговый результат
        buf.add_partial("и последнее")
        buf.set_authoritative("Привет мир. Сегодня хороший день. И последнее.")

        text, is_partial = buf.render()
        assert is_partial is False
        assert "Привет мир" in text
        assert "Сегодня хороший день" in text
        assert "И последнее" in text
        # ни один черновик не утёк в итог
        for draft in ("привет мо", "сег��дн", "и последн"):
            assert draft not in text
        assert text.count("\n") == 0  # итог — абзацем, как в файле
        assert buf.finalized() == text
