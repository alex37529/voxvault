"""Тесты i18n: целостность словарей и подстановки.

Ключевая защита от типичной ошибки локализации: наборы ключей и плейсхолдеров
во всех языках должны совпадать. Иначе перевод «отваливается» в рантайме.
"""

from __future__ import annotations

import json

import pytest

from dictophone import i18n
from dictophone.i18n import (
    I18n,
    available,
    detect_system_lang,
    lang_name,
    windows_lang,
)

LANGS = available()


@pytest.fixture(scope="module")
def tables():
    return {
        lang: json.loads((i18n.LOCALES_DIR / f"{lang}.json").read_text("utf-8"))
        for lang in LANGS
    }


class TestCatalog:
    def test_at_least_two_languages(self):
        assert len(LANGS) >= 2, "нужен минимум базовый + запасной язык"

    def test_fallback_present(self):
        assert i18n.FALLBACK in LANGS

    def test_all_values_are_strings(self, tables):
        for lang, table in tables.items():
            for key, value in table.items():
                assert isinstance(value, str), f"{lang}:{key} не строка"
                assert value.strip(), f"{lang}:{key} пустой"

    def test_keys_are_dotted_identifiers(self, tables):
        for lang, table in tables.items():
            for key in table:
                assert key == key.strip()
                assert " " not in key
                assert key.count(".") >= 1, f"{lang}:{key} — без префикса"

    def test_key_sets_identical(self, tables):
        """Главная проверка: наборы ключей не расходятся между языками."""
        base = set(tables[i18n.FALLBACK])
        for lang, table in tables.items():
            missing = base - set(table)
            extra = set(table) - base
            assert not missing, f"в {lang} нет ключей: {sorted(missing)}"
            assert not extra, f"в {lang} лишние ключи: {sorted(extra)}"

    def test_placeholders_identical(self, tables):
        """Иначе {name} останется неподставленным в одном из языков."""
        import re

        pattern = re.compile(r"\{(\w+)\}")
        per_lang = {
            lang: {k: set(pattern.findall(v)) for k, v in table.items()}
            for lang, table in tables.items()
        }
        base = per_lang[i18n.FALLBACK]
        for lang, table in per_lang.items():
            for key, names in table.items():
                assert names == base[key], (
                    f"{lang}:{key} плейсхолдеры {sorted(names)} != {sorted(base[key])}"
                )

    def test_no_source_strings_as_keys(self, tables):
        """Ключ не должен совпадать со значением (признак ленивого перевода)."""
        for lang, table in tables.items():
            for key, value in table.items():
                assert key != value, f"{lang}: ключ {key} совпал с текстом"


class TestTranslate:
    def test_returns_translation(self):
        ru = I18n("ru")
        en = I18n("en")
        assert ru.t("btn.record") != en.t("btn.record")
        assert "Record" in en.t("btn.record")

    def test_formats_placeholders(self):
        en = I18n("en")
        out = en.t("status.loading_wait", name="ru/large", sec=42)
        assert "ru/large" in out and "42" in out

    def test_about_mentions_brand_and_benefits(self):
        for lang in available():
            text = I18n(lang).t("about.text")
            assert "VoxVault" in text, lang
            assert "Makeenak Alyaksandr" in text, lang
            assert "6836808@gmail.com" in text, lang

    def test_app_title_uses_new_brand(self):
        for lang in available():
            assert I18n(lang).t("app.title").startswith("VoxVault")

    def test_missing_key_returns_key_itself(self):
        en = I18n("en")
        assert en.t("no.such.key") == "no.such.key"

    def test_broken_placeholder_does_not_raise(self):
        en = I18n("en")
        # ключ есть, но передан лишний/неизвестный аргумент
        out = en.t("status.loading_wait", wrong_name="x")
        assert isinstance(out, str) and out

    def test_fallback_to_english_for_unknown_key(self, tmp_path, monkeypatch):
        """Ключ есть только в en — должен подставиться, а не упасть."""
        en_table = json.loads((i18n.LOCALES_DIR / "en.json").read_text("utf-8"))
        ru_table = json.loads((i18n.LOCALES_DIR / "ru.json").read_text("utf-8"))
        ru_table.pop("btn.copy")
        only_en = "btn.copy"
        (i18n.LOCALES_DIR / "zz.json").write_text(
            json.dumps(ru_table, ensure_ascii=False), encoding="utf-8"
        )
        monkeypatch.setattr(i18n, "LOCALES_DIR", i18n.LOCALES_DIR)
        try:
            zz = I18n("zz")
            assert zz.t(only_en) == en_table[only_en]
        finally:
            (i18n.LOCALES_DIR / "zz.json").unlink(missing_ok=True)

    def test_unknown_lang_falls_back(self):
        obj = I18n("ru")
        obj.set_lang("klingon")
        assert obj.lang == i18n.FALLBACK

    def test_lang_property(self):
        assert I18n("en").lang == "en"

    def test_is_rtl(self):
        assert I18n("en").is_rtl is False

    def test_preload_fills_cache(self):
        obj = I18n("ru")
        obj._cache.clear()
        obj.preload()
        # все языки прочитаны заранее -> переключение без чтения файла
        for lang in available():
            assert lang in obj._cache

    def test_preload_survives_broken_file(self, monkeypatch):
        """Битый словарь не должен ломать запуск — просто не грузится."""
        broken = i18n.LOCALES_DIR / "zz.json"
        broken.write_text("{не json", encoding="utf-8")
        try:
            obj = I18n("ru")
            obj.preload()  # не должно бросить
            assert obj.t("btn.record")
        finally:
            broken.unlink(missing_ok=True)

    def test_switch_is_instant_after_preload(self):
        obj = I18n("en")
        obj.preload()
        first = obj.t("btn.record")
        obj.set_lang("ru")
        assert obj.t("btn.record") != first


class TestLangName:
    """Название языка распознавания для сообщений и списков."""

    def test_known_lang_uses_translation(self):
        ru = I18n("ru").t
        assert lang_name(ru, "ru") == "Русский"
        assert lang_name(ru, "uk") == "Українська"

    def test_unknown_lang_falls_back_to_code(self):
        """Язык распознавания не всегда есть в словаре — показываем код."""
        ru = I18n("ru").t
        assert lang_name(ru, "el-gr") == "el-gr"

    def test_key_never_leaks_to_user(self):
        for lang in available():
            tr = I18n(lang).t
            for code in ("ru", "en-us", "zh", "el-gr"):
                text = lang_name(tr, code)
                assert not text.startswith("lang."), (lang, code)
                assert text

    def test_windows_lang_valid_or_none(self):
        code = windows_lang()
        assert code is None or isinstance(code, str)

    def test_detect_returns_available(self):
        code = detect_system_lang()
        assert code in available()

    def test_detect_falls_back_when_unknown(self, monkeypatch):
        monkeypatch.setattr(i18n, "windows_lang", lambda: "xx")
        assert detect_system_lang() in available()
