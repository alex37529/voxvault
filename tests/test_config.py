"""Тесты настроек (config.py)."""
from __future__ import annotations

import json

import pytest

from dictophone import config as config_mod


class TestLoad:
    def test_defaults_when_no_file(self, tmp_path):
        cfg = config_mod.load_config(tmp_path / "absent.json")
        assert cfg.lang == "ru"
        # small по умолчанию: 'auto' тянул бы большую модель (70 с на прогрев).
        assert cfg.size == "small"
        assert cfg.size_or_none() == "small"
        assert cfg.device is None
        assert cfg.ui_lang == "auto"
        assert cfg.ui_lang_or_none() is None
        assert cfg.first_run is True      # выбор языка ещё не показывали

    def test_existing_config_disables_first_run(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"ui_lang": "ru", "first_run": True}), encoding="utf-8")
        assert config_mod.load_config(path).first_run is False

    def test_reads_values(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(
            json.dumps({"lang": "uk", "size": "small", "device": "yeti"},
                       ensure_ascii=False),
            encoding="utf-8",
        )
        cfg = config_mod.load_config(path)
        assert (cfg.lang, cfg.size, cfg.device) == ("uk", "small", "yeti")

    def test_bad_json_raises(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(config_mod.ConfigError):
            config_mod.load_config(path)

    def test_unknown_key_raises(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"lang": "ru", "nope": 1}), encoding="utf-8")
        with pytest.raises(config_mod.ConfigError, match="Неизвестный параметр"):
            config_mod.load_config(path)

    def test_bad_size_raises(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"size": "huge"}), encoding="utf-8")
        with pytest.raises(config_mod.ConfigError, match="size"):
            config_mod.load_config(path)

    def test_empty_string_becomes_none(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"device": "  "}), encoding="utf-8")
        assert config_mod.load_config(path).device is None

    def test_not_a_dict_raises(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text("[1,2,3]", encoding="utf-8")
        with pytest.raises(config_mod.ConfigError):
            config_mod.load_config(path)

    def test_boolean_keys_parsed(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"history": False, "first_run": False}),
                       encoding="utf-8")
        cfg = config_mod.load_config(path)
        assert cfg.history is False and cfg.first_run is False

    def test_bad_boolean_raises(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"first_run": "maybe"}), encoding="utf-8")
        with pytest.raises(config_mod.ConfigError, match="first_run"):
            config_mod.load_config(path)


class TestSave:
    def test_roundtrip(self, tmp_path):
        path = tmp_path / "sub" / "config.json"
        cfg = config_mod.Config(lang="de", size="large", device="1")
        saved = config_mod.save_config(cfg, path)
        assert saved == path
        back = config_mod.load_config(path)
        assert back.lang == "de" and back.size == "large" and back.device == "1"

    def test_none_values_not_written(self, tmp_path):
        path = tmp_path / "config.json"
        config_mod.save_config(config_mod.Config(), path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert "device" not in raw
        assert raw["lang"] == "ru"

    def test_size_and_ui_lang_always_written(self, tmp_path):
        """Раньше size/ui_lang пропадали из файла при значении None/auto —
        и настройки молча терялись. Теперь они записываются всегда."""
        path = tmp_path / "config.json"
        config_mod.save_config(config_mod.Config(size="auto", ui_lang="auto"), path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["size"] == "auto"
        assert raw["ui_lang"] == "auto"
        back = config_mod.load_config(path)
        assert back.size == "auto" and back.ui_lang == "auto"

    def test_auto_size_roundtrip(self, tmp_path):
        path = tmp_path / "c.json"
        config_mod.save_config(config_mod.Config(size="auto"), path)
        assert config_mod.load_config(path).size_or_none() is None

    def test_bad_ui_lang_rejected(self, tmp_path):
        path = tmp_path / "c.json"
        path.write_text(json.dumps({"ui_lang": "kl"}), encoding="utf-8")
        with pytest.raises(config_mod.ConfigError, match="ui_lang"):
            config_mod.load_config(path)

    def test_unicode_preserved(self, tmp_path):
        path = tmp_path / "config.json"
        config_mod.save_config(config_mod.Config(output_dir="Д:\\Записи"), path)
        text = path.read_text(encoding="utf-8")
        assert "Записи" in text


class TestSetValues:
    def test_sets_and_persists(self, tmp_path):
        path = tmp_path / "config.json"
        cfg, saved = config_mod.set_values(
            config_mod.Config(), {"lang": "fr", "size": "small"}, path
        )
        assert cfg.lang == "fr" and cfg.size == "small"
        assert config_mod.load_config(path).lang == "fr"

    def test_empty_value_resets_to_default(self, tmp_path):
        path = tmp_path / "config.json"
        config_mod.save_config(config_mod.Config(device="5"), path)
        cfg, _ = config_mod.set_values(config_mod.load_config(path), {"device": ""}, path)
        assert cfg.device is None

    def test_unknown_key_raises(self, tmp_path):
        with pytest.raises(config_mod.ConfigError, match="Неизвестный"):
            config_mod.set_values(
                config_mod.Config(), {"bad": "1"}, tmp_path / "c.json"
            )
