"""Тесты CLI: парсер, настройки, роутинг (без реальных моделей/микрофона)."""

from __future__ import annotations

import json

import pytest

from dictophone import cli


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Изолированный файл настроек, чтобы не трогать настройки пользователя."""
    path = tmp_path / "config.json"
    monkeypatch.setenv("DICTOPHONE_CONFIG", str(path))
    return path


@pytest.fixture
def stub_transcribe(monkeypatch):
    """Перехватываем вызов transcribe.transcribe — модель грузить не нужно."""
    calls = []

    def fake(source=None, **kw):
        calls.append({"source": source, **kw})
        return "текст"

    monkeypatch.setattr(cli.transcribe, "transcribe", fake)
    return calls


class TestParser:
    def test_help_lists_all_commands(self, capsys):
        with pytest.raises(SystemExit):
            cli.main(["--help"])
        out = capsys.readouterr().out
        for cmd in ("list", "devices", "config", "download", "file", "mic"):
            assert cmd in out

    def test_version_flag_prints_version(self, capsys):
        """Версия нужна пользователю для отчёта об ошибке."""
        from dictophone import __version__

        with pytest.raises(SystemExit) as exit_info:
            cli.main(["--version"])
        assert exit_info.value.code == 0
        assert __version__ in capsys.readouterr().out

    def test_no_args_prints_help(self, capsys):
        cli.main([])
        assert "usage" in capsys.readouterr().out.lower()

    def test_mic_has_device_and_size(self):
        args = cli.build_parser().parse_args(["mic", "--size", "large", "--device", "1"])
        assert args.size == "large" and args.device == "1"

    def test_file_words_flag(self):
        args = cli.build_parser().parse_args(["file", "a.wav", "--words"])
        assert args.words is True

    def test_defaults_are_none_so_config_wins(self):
        args = cli.build_parser().parse_args(["file", "a.wav"])
        assert args.lang is None and args.size is None
        assert args.output is None and args.output_dir is None


class TestConfigCommand:
    def test_shows_defaults(self, isolated_config, capsys):
        cli.main(["config"])
        out = capsys.readouterr().out
        assert "lang" in out and "ru" in out
        assert str(isolated_config) in out

    def test_sets_values(self, isolated_config, capsys):
        cli.main(["config", "lang=uk", "size=small"])
        capsys.readouterr()
        data = json.loads(isolated_config.read_text(encoding="utf-8"))
        assert data["lang"] == "uk" and data["size"] == "small"

    def test_rejects_unknown_lang(self, isolated_config):
        with pytest.raises(SystemExit, match="Неизвестный язык"):
            cli.main(["config", "lang=xx"])

    def test_rejects_bad_format(self, isolated_config):
        with pytest.raises(SystemExit, match="КЛЮЧ=ЗНАЧЕНИЕ"):
            cli.main(["config", "langru"])

    def test_reset(self, isolated_config):
        cli.main(["config", "lang=de"])
        cli.main(["config", "--reset"])
        data = json.loads(isolated_config.read_text(encoding="utf-8"))
        assert data.get("lang", "ru") == "ru"

    def test_reset_keeps_language_state(self, isolated_config):
        """--reset не должен приводить к повторному вопросу про язык."""
        # сначала «пользователь прошёл первый запуск» и выбрал русский
        cli.main(["config", "first_run=false", "ui_lang=ru", "lang=uk"])
        cli.main(["config", "--reset"])
        data = json.loads(isolated_config.read_text(encoding="utf-8"))
        assert data["first_run"] is False  # диалог больше не появится
        assert data["ui_lang"] == "ru"  # язык интерфейса сохранён
        assert data["lang"] == "ru"  # а вот язык распознавания сброшен

    def test_ask_language_sets_first_run(self, isolated_config):
        """--ask-language намеренно включает вопрос при следующем запуске."""
        cli.main(["config", "ui_lang=ru"])
        cli.main(["config", "--ask-language"])
        data = json.loads(isolated_config.read_text(encoding="utf-8"))
        assert data["first_run"] is True
        assert data["ui_lang"] == "ru"  # сам язык не меняем, только флаг

    def test_size_can_be_set_and_persists(self, isolated_config):
        """Пользователь может зафиксировать размер модели (не 'auto')."""
        cli.main(["config", "size=small"])
        data = json.loads(isolated_config.read_text(encoding="utf-8"))
        assert data["size"] == "small"
        cli.main(["config", "size=large"])
        data = json.loads(isolated_config.read_text(encoding="utf-8"))
        assert data["size"] == "large"

    def test_show_reports_size(self, isolated_config, capsys):
        cli.main(["config", "size=small"])
        capsys.readouterr()
        cli.main(["config"])
        out = capsys.readouterr().out
        assert "size" in out and "small" in out

    def test_broken_config_file_is_reported(self, tmp_path, capsys):
        broken = tmp_path / "broken.json"
        broken.write_text("{oops", encoding="utf-8")
        with pytest.raises(SystemExit, match="разобрать"):
            cli.main(["config", "--path", str(broken)])


class TestSettingsPrecedence:
    def test_config_supplies_defaults(self, isolated_config, stub_transcribe):
        cli.main(["config", "lang=de", "size=small"])
        cli.main(["file", "a.wav"])
        call = stub_transcribe[0]
        assert call["lang"] == "de" and call["size"] == "small"

    def test_cli_overrides_config(self, isolated_config, stub_transcribe):
        cli.main(["config", "lang=de", "size=small"])
        cli.main(["file", "a.wav", "--lang", "fr", "--size", "large"])
        call = stub_transcribe[0]
        assert call["lang"] == "fr" and call["size"] == "large"

    def test_output_dir_from_config(self, isolated_config, stub_transcribe, tmp_path):
        target = tmp_path / "custom_out"
        cli.main(["config", f"output_dir={target}"])
        cli.main(["file", "a.wav"])
        assert stub_transcribe[0]["output"] == target / "a.txt"

    def test_explicit_output_wins(self, isolated_config, stub_transcribe, tmp_path):
        cli.main(["config", f"output_dir={tmp_path / 'cfg'}"])
        out = tmp_path / "explicit.txt"
        cli.main(["file", "a.wav", "-o", str(out)])
        assert stub_transcribe[0]["output"] == out


class TestRouting:
    def test_file_rejects_unknown_lang(self, isolated_config, stub_transcribe):
        with pytest.raises(SystemExit, match="Неизвестный язык"):
            cli.main(["file", "a.wav", "--lang", "xx"])

    def test_mic_resolves_device(self, isolated_config, stub_transcribe, monkeypatch):
        seen = {}

        def fake_resolve(spec):
            seen["spec"] = spec
            return 7

        monkeypatch.setattr(cli.devices_mod, "resolve_device", fake_resolve)
        cli.main(["config", "device=yeti"])
        cli.main(["mic"])
        assert seen["spec"] == "yeti"
        assert stub_transcribe[0]["device"] == 7

    def test_mic_device_error_is_user_friendly(
        self, isolated_config, stub_transcribe, monkeypatch
    ):
        def boom(spec):
            raise cli.devices_mod.DeviceError("Устройство 'xx' не найдено")

        monkeypatch.setattr(cli.devices_mod, "resolve_device", boom)
        with pytest.raises(SystemExit, match="не найдено"):
            cli.main(["mic", "--device", "xx"])

    def test_list_runs(self, capsys):
        cli.main(["list"])
        assert "vosk-model" in capsys.readouterr().out
