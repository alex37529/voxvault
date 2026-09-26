"""Тесты постобработки текста (postprocess.py)."""

from __future__ import annotations

import pytest

from dictophone import postprocess as pp


class TestHeuristic:
    def test_capitalizes_first_letter(self):
        assert pp.heuristic("привет мир") == "Привет мир."

    def test_adds_final_dot(self):
        assert pp.heuristic("тест").endswith(".")

    def test_keeps_existing_punctuation(self):
        out = pp.heuristic("Привет.")
        assert out == "Привет."
        assert not out.endswith("..")

    def test_respects_segments_as_sentences(self):
        out = pp.heuristic("раз два три", segments=["раз два", "три"])
        assert out.count(".") == 2
        assert out.startswith("Раз")
        assert "Три" in out

    def test_does_not_double_sentences(self):
        # уже есть точка — не добавляем вторую
        assert pp.heuristic("Привет. Как дела") == "Привет. Как дела."

    def test_empty_untouched(self):
        assert pp.heuristic("") == ""
        assert pp.heuristic("   ") == "   "

    def test_digits_prefix_keeps_capitalization(self):
        assert pp.heuristic("123 привет").startswith("123 Привет")

    def test_no_spurious_commas(self):
        """Запятые намеренно не ставим: без разбора они дают мусор."""
        out = pp.heuristic("я думаю что да")
        assert "," not in out
        assert "думаю" in out

    def test_keeps_existing_comma(self):
        assert pp.heuristic("привет, мир") == "Привет, мир."

    def test_non_latin_untouched(self):
        assert pp.heuristic("日本語") == "日本語."


class TestModes:
    def test_off_is_identity(self):
        proc = pp.get_mode("off")
        assert proc.apply("привет мир") == "привет мир"

    def test_heuristic_mode(self):
        assert pp.get_mode("heuristic").apply("тест") == "Тест."

    def test_unknown_mode_raises(self):
        from dictophone.config import ConfigError

        with pytest.raises(ConfigError, match="Неизвестный режим"):
            pp.get_mode("nope")

    def test_apply_respects_enabled_flag(self):
        assert pp.apply("тест", enabled=False) == "тест"
        assert pp.apply("тест", enabled=True) == "Тест."


class TestBackendSwap:
    def test_set_backend(self):
        class Shout:
            def apply(self, text, segments=()):
                return text.upper() + "!"

        original = pp.get_backend()
        try:
            pp.set_backend(Shout())
            assert pp.apply("тихо") == "ТИХО!"
        finally:
            pp.set_backend(original)
        assert pp.apply("тихо") == "Тихо."

    def test_function_adapter(self):
        proc = pp.FunctionPostProcessor(lambda t, s=(): t[::-1])
        assert proc.apply("abc") == "cba"
        assert "FunctionPostProcessor" in repr(proc)
