"""Тесты реестра и выбора моделей (models.py)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import ClassVar

import pytest

from dictophone import models


class TestDataRoot:
    """Где приложение ищет модели/тексты — в исходниках и в собранном exe."""

    def test_source_mode_uses_project_root(self, monkeypatch):
        monkeypatch.delattr(sys, "frozen", raising=False)
        assert models._data_root() == models.PROJECT_ROOT

    def test_frozen_uses_dir_next_to_exe(self, tmp_path, monkeypatch):
        """Portable-релиз: модели лежат рядом с exe, а не внутри _internal."""
        fake_exe = tmp_path / "VoxVault" / "VoxVault.exe"
        fake_exe.parent.mkdir(parents=True)
        fake_exe.write_bytes(b"x")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(fake_exe))
        assert models._data_root() == fake_exe.parent

    def test_frozen_falls_back_to_localappdata(self, tmp_path, monkeypatch):
        """В Program Files записать нельзя — уходим в %LOCALAPPDATA%."""
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        # Каталога рядом с exe нет и создать его нельзя (как в Program Files).
        monkeypatch.setattr(
            sys,
            "executable",
            str(tmp_path / "read only root" / "VoxVault.exe"),
        )
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
        assert models._data_root() == tmp_path / "local" / "VoxVault"

    def test_probe_file_is_cleaned_up(self, tmp_path, monkeypatch):
        fake_exe = tmp_path / "VoxVault" / "VoxVault.exe"
        fake_exe.parent.mkdir(parents=True)
        fake_exe.write_bytes(b"x")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(fake_exe))
        models._data_root()
        leftovers = list(fake_exe.parent.glob(".voxvault-write-probe"))
        assert leftovers == [], "пробный файл записи должен удаляться"

    def test_defaults_are_inside_data_root(self):
        assert models.DEFAULT_MODEL_DIR.parent == models.DATA_ROOT
        assert models.DEFAULT_OUTPUT_DIR.parent == models.DATA_ROOT


class TestRegistry:
    def test_known_langs_sorted_and_nonempty(self):
        langs = models.known_langs()
        assert langs == sorted(langs)
        assert "ru" in langs and "en-us" in langs

    def test_every_lang_has_at_least_one_size(self):
        for lang, sizes in models.MODELS.items():
            assert any(sizes.values()), f"язык {lang} без размеров"

    def test_archive_names_are_unique(self):
        names = [n for sizes in models.MODELS.values() for n in sizes.values() if n]
        assert len(names) == len(set(names)), "дублирующиеся имена архивов"

    def test_model_name_returns_archive(self):
        assert models.model_name("ru", "small") == "vosk-model-small-ru-0.22"
        assert models.model_name("RU", "large") == "vosk-model-ru-0.42"

    def test_model_name_unknown_lang(self):
        with pytest.raises(models.ModelNotAvailableError, match="Неизвестный язык"):
            models.model_name("xx", "small")

    def test_model_name_missing_size_suggests_alternative(self):
        # У 'pl' есть только small
        with pytest.raises(models.ModelNotAvailableError, match="small"):
            models.model_name("pl", "large")

    def test_model_url_shape(self):
        url = models.model_url("en-us", "small")
        assert url.endswith("/vosk-model-small-en-us-0.15.zip")
        assert url.startswith("http")

    def test_table_lists_all_langs(self):
        table = models.format_models_table()
        for lang in models.known_langs():
            assert lang in table


class TestRegistrySizes:
    """Размеры, которых нет в реестре, — это «нет», а не «-»."""

    def test_available_sizes_for_both_kinds(self):
        assert models.available_sizes("ru") == ["small", "large"]
        assert models.available_sizes("ar") == ["large"]  # только большая
        assert models.available_sizes("ca") == ["small"]  # только маленькая

    def test_missing_sizes(self):
        assert models.missing_sizes("ar") == ["small"]
        assert models.missing_sizes("ca") == ["large"]
        assert models.missing_sizes("ru") == []

    def test_size_exists(self):
        assert models.size_exists("ar", "large") is True
        assert models.size_exists("ar", "small") is False
        assert models.size_exists("ca", "small") is True
        assert models.size_exists("ca", "large") is False

    def test_case_insensitive_and_unknown_lang(self):
        assert models.available_sizes("AR") == ["large"]
        assert models.available_sizes("xx") == []
        assert models.size_exists("xx", "small") is False

    def test_every_lang_has_at_least_one_size_in_order(self):
        for lang in models.known_langs():
            sizes = models.available_sizes(lang)
            assert sizes, f"{lang}: ни одного размера"
            assert sizes == sorted(sizes, key=models.SIZES.index)

    def test_table_says_no_instead_of_dash(self):
        """Регресс: отсутствующий размер печатался как `small=-`.

        По дефису не отличить «нет такой модели» от «сбой вывода», и
        интерфейс предлагал скачать то, чего не существует.
        """
        table = models.format_models_table()
        line = next(row for row in table.splitlines() if row.strip().startswith("ar"))
        assert "small = нет в реестре" in line
        assert "large = vosk-model-ar-mgb2-0.4" in line
        assert "=-" not in table
        assert "= -" not in table

    def test_table_shows_archive_names(self):
        table = models.format_models_table()
        for sizes in models.MODELS.values():
            for name in sizes.values():
                if name:
                    assert name in table, f"{name} не показан в таблице"


class TestFindModel:
    def test_by_lang_prefers_large(self, fake_model_dir):
        found = models.find_model(fake_model_dir, "ru")
        assert found is not None and found.name == "vosk-model-ru-0.42"

    def test_explicit_small(self, fake_model_dir):
        found = models.find_model(fake_model_dir, "ru", "small")
        assert found is not None and found.name == "vosk-model-small-ru-0.22"

    def test_explicit_large(self, fake_model_dir):
        found = models.find_model(fake_model_dir, "ru", "large")
        assert found is not None and found.name == "vosk-model-ru-0.42"

    def test_missing_lang_returns_none(self, fake_model_dir):
        assert models.find_model(fake_model_dir, "ja") is None

    def test_missing_size_returns_none(self, fake_model_dir):
        # Для 'ar' в фикстуре есть только large
        assert models.find_model(fake_model_dir, "ar", "small") is None

    def test_registry_match_wins_over_substring(self, fake_model_dir):
        """'ar' не должен цеплять vosk-model-small-ar-tn-... (тунисский арабский)."""
        found = models.find_model(fake_model_dir, "ar", "small")
        assert found is None, "ar не должен матчить -ar-tn-"
        found = models.find_model(fake_model_dir, "ar")
        assert found is not None and found.name == "vosk-model-ar-mgb2-0.4"

    def test_en_us_does_not_match_en_in_style(self, fake_model_dir):
        found = models.find_model(fake_model_dir, "en-us", "small")
        assert found is not None and found.name == "vosk-model-small-en-us-0.15"

    def test_ignores_recasepunc_and_junk(self, fake_model_dir):
        for _ in range(3):
            found = models.find_model(fake_model_dir)
            assert found is not None
            assert "recasepunc" not in found.name
            assert found.name.startswith("vosk-model-")

    def test_missing_dir_returns_none(self, tmp_path):
        assert models.find_model(tmp_path / "nope", "ru") is None

    def test_incomplete_model_dir_ignored(self, tmp_path):
        # каталог без am/final.mdl не считается моделью
        (tmp_path / "vosk-model-small-ru-0.22" / "am").mkdir(parents=True)
        assert models.find_model(tmp_path, "ru") is None

    def test_model_dir_pointing_directly_at_model(self, fake_model_dir):
        """--model-dir может указывать сразу на папку модели (для ручных моделей)."""
        direct = fake_model_dir / "vosk-model-small-ru-0.22"
        found = models.find_model(direct, "ru", "small")
        assert found == direct

    def test_unknown_custom_model_via_direct_path(self, tmp_path):
        """Модель вне реестра подключается прямым указанием папки."""
        custom = tmp_path / "my-custom-model" / "am"
        custom.mkdir(parents=True)
        (custom / "final.mdl").write_bytes(b"fake")
        (tmp_path / "my-custom-model" / "conf").mkdir()
        found = models.find_model(tmp_path / "my-custom-model")
        assert found is not None and found.name == "my-custom-model"


class TestDownloadGuards:
    def test_existing_model_skips_download(self, fake_model_dir, capsys):
        path = models.download_model("ru", "small", fake_model_dir)
        assert path.name == "vosk-model-small-ru-0.22"
        assert "уже установлена" in capsys.readouterr().out

    def test_existing_small_does_not_block_large(self, tmp_path, monkeypatch):
        """Ранний выход срабатывает только на запрошенный размер."""
        # установлена ТОЛЬКО small-модель
        model = tmp_path / "vosk-model-small-ru-0.22" / "am"
        model.mkdir(parents=True)
        (model / "final.mdl").write_bytes(b"fake")

        def boom(*a, **kw):
            raise RuntimeError("сеть недоступна")

        import requests

        monkeypatch.setattr(requests, "get", boom)

        # download_model переводит сетевые сбои в SystemExit с понятным текстом
        with pytest.raises(SystemExit, match="Не удалось скачать"):
            models.download_model("ru", "large", tmp_path)

    def test_partial_file_is_not_treated_as_installed(self, tmp_path):
        """Оборванная загрузка не должна выглядеть как установленная модель."""
        part = tmp_path / "vosk-model-ru-0.42.zip.part"
        part.write_bytes(b"PK\x03\x04 partial")
        assert models.find_model(tmp_path, "ru", "large") is None

    def test_download_large_ru_keeps_new_layout_model(self, tmp_path, monkeypatch):
        """Сценарий из репорта: ru/large скачивается и остаётся на диске.

        Сеть подменена, архив — настоящий zip с раскладкой новой модели
        (единственный `graph/HCLG.fst`). Раньше такая модель проходила
        скачивание, но удалялась проверкой как неполная.
        """
        import zipfile

        source = tmp_path / "source.zip"
        name = models.MODELS["ru"]["large"]
        with zipfile.ZipFile(source, "w") as zf:
            for relative in models.REQUIRED_MODEL_FILES:
                zf.writestr(f"{name}/{relative}", "x")
            zf.writestr(f"{name}/graph/HCLG.fst", "x")

        payload = source.read_bytes()
        monkeypatch.setattr(
            models,
            "_fetch_archive",
            lambda url, dest, **kw: Path(dest).write_bytes(payload),
        )

        model_dir = tmp_path / "models"
        path = models.download_model("ru", "large", model_dir)
        assert path == model_dir / name
        assert (path / "graph" / "HCLG.fst").exists()
        assert models.find_model(model_dir, "ru", "large") == path
        # временный .part не остаётся рядом с моделью
        assert not list(model_dir.glob("*.part"))


class TestIntegrity:
    def _make_model(self, root: Path, name: str, graph: str) -> Path:
        """Разметить каталог под распакованную модель VOSK."""
        model = root / name
        for relative in models.REQUIRED_MODEL_FILES:
            path = model / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")
        (model / "graph").mkdir(parents=True, exist_ok=True)
        (model / "graph" / graph).write_bytes(b"x")
        return model

    def test_validate_model_dir_lists_missing(self, tmp_path):
        model = tmp_path / "vosk-model-ru-0.42" / "am"
        model.mkdir(parents=True)
        (model / "final.mdl").write_bytes(b"x")
        missing = models.validate_model_dir(tmp_path / "vosk-model-ru-0.42")
        assert "conf/mfcc.conf" in missing
        assert "am/final.mdl" not in missing

    @pytest.mark.parametrize("graph", ["Gr.fst", "HCLr.fst", "HCLG.fst"])
    def test_validate_accepts_any_graph_layout(self, tmp_path, graph):
        """Имя файла графа у моделей разное — проверка не должна его знать.

        Регресс: требовались `Gr.fst` и `HCLr.fst`, и нормальная большая
        модель ru-0.42 (в ней один `HCLG.fst`) объявлялась неполной —
        скачанные 1,8 ГБ удалялись, модель оставалась недоступной.
        """
        model = self._make_model(tmp_path, "vosk-model-x", graph)
        assert models.validate_model_dir(model) == []

    def test_validate_reports_missing_graph(self, tmp_path):
        """Без графа декодирования модель действительно нерабочая."""
        model = self._make_model(tmp_path, "vosk-model-x", "HCLG.fst")
        (model / "graph" / "HCLG.fst").unlink()
        missing = models.validate_model_dir(model)
        assert missing == ["graph/*.fst"]

    def test_validate_accepts_vosk_archive_layout(self, tmp_path):
        model = self._make_model(tmp_path, "vosk-model-small-ru-0.22", "HCLr.fst")
        assert models.validate_model_dir(model) == []

    def test_extract_keeps_model_with_hclg_graph(self, tmp_path):
        """Модель из новой раскладки должна пережить распаковку."""
        import zipfile

        arch = tmp_path / "vosk-model-ru-0.42.zip"
        with zipfile.ZipFile(arch, "w") as zf:
            for relative in models.REQUIRED_MODEL_FILES:
                zf.writestr(f"vosk-model-ru-0.42/{relative}", "x")
            zf.writestr("vosk-model-ru-0.42/graph/HCLG.fst", "x")
        models._extract_verified(
            zip_path=arch, model_dir=tmp_path, archive_name="vosk-model-ru-0.42"
        )
        assert (tmp_path / "vosk-model-ru-0.42" / "graph" / "HCLG.fst").exists()

    def test_extract_rejects_broken_zip(self, tmp_path):
        broken = tmp_path / "vosk-model-ru-0.42.zip"
        broken.write_bytes(b"not a zip at all")
        with pytest.raises(SystemExit, match="повреждён"):
            models._extract_verified(
                zip_path=broken, model_dir=tmp_path, archive_name="vosk-model-ru-0.42"
            )

    def test_extract_rejects_incomplete_model(self, tmp_path):
        import zipfile

        arch = tmp_path / "m.zip"
        with zipfile.ZipFile(arch, "w") as zf:
            zf.writestr("vosk-model-ru-0.42/am/final.mdl", "x")  # без conf/graph
        with pytest.raises(SystemExit, match="недостают"):
            models._extract_verified(
                zip_path=arch, model_dir=tmp_path, archive_name="vosk-model-ru-0.42"
            )
        # недокачанная модель убрана
        assert not (tmp_path / "vosk-model-ru-0.42").exists()

    def test_installed_langs(self, fake_model_dir):
        langs = models.installed_langs(fake_model_dir)
        assert "ru" in langs and "en-us" in langs and "ar" in langs
        assert "ja" not in langs  # модели нет


class TestInstalledAndDelete:
    def test_list_installed_reports_sizes(self, fake_model_dir):
        rows = models.list_installed(fake_model_dir)
        by_lang = {r["lang"]: r for r in rows}
        ru = by_lang["ru"]
        assert ru["small"] == "vosk-model-small-ru-0.22"
        assert ru["large"] == "vosk-model-ru-0.42"
        assert ru["path"] is not None
        assert by_lang["ja"]["path"] is None  # не установлена
        assert by_lang["ja"]["small"] is None

    def test_list_installed_covers_all_langs(self, fake_model_dir):
        rows = models.list_installed(fake_model_dir)
        assert len(rows) == len(models.MODELS)
        assert {"lang", "small", "large", "path", "size_mb"} <= set(rows[0])

    def test_dir_size_mb(self, fake_model_dir):
        model = fake_model_dir / "vosk-model-small-ru-0.22"
        (model / "big.bin").write_bytes(b"x" * (3 * 1024 * 1024))
        assert models.dir_size_mb(model) >= 3

    def test_free_space_positive(self, fake_model_dir):
        assert models.free_space_mb(fake_model_dir) > 0

    def test_delete_model_frees(self, fake_model_dir):
        model = fake_model_dir / "vosk-model-small-ru-0.22"
        assert model.is_dir()
        freed = models.delete_model(model)
        assert freed >= 0
        assert not model.exists()
        assert models.find_model(fake_model_dir, "ru", "small") is None

    def test_delete_refuses_non_model_dir(self, fake_model_dir):
        with pytest.raises(ValueError, match="не каталог модели"):
            models.delete_model(fake_model_dir / "not-a-model")

    def test_delete_refuses_root_models_dir(self):
        with pytest.raises(ValueError, match="корневой каталог"):
            models.delete_model(models.DEFAULT_MODEL_DIR)


class TestDownloadProgress:
    def _fake_response(self, chunks, total):
        class R:
            headers: ClassVar[dict] = {"content-length": str(total)}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size=1):
                return iter(chunks)

        return lambda *a, **k: R()

    def test_progress_cb_receives_bytes(self, tmp_path, monkeypatch):
        import requests

        chunks = [b"a" * 512, b"b" * 512]
        total = 1024
        monkeypatch.setattr(requests, "get", self._fake_response(chunks, total))
        seen = []
        dest = tmp_path / "a.zip"
        models._fetch_archive(
            "http://x/a.zip", dest, progress_cb=lambda d, t: seen.append((d, t))
        )
        assert seen, "прогресс не передавался"
        assert seen[-1] == (total, total)
        assert [d for d, _ in seen] == sorted(d for d, _ in seen)  # неубывает

    def test_progress_cb_suppresses_stdout(self, tmp_path, monkeypatch, capsys):
        import requests

        monkeypatch.setattr(requests, "get", self._fake_response([b"x" * 100], 100))
        models._fetch_archive(
            "http://x/a.zip", tmp_path / "b.zip", progress_cb=lambda d, t: None
        )
        assert "%" not in capsys.readouterr().out

    def test_stop_event_cancels(self, tmp_path, monkeypatch):
        import threading

        import requests

        monkeypatch.setattr(requests, "get", self._fake_response([b"x" * 16] * 5, 80))
        stop = threading.Event()
        stop.set()  # отмена до начала
        with pytest.raises(models.DownloadCancelled):
            models._fetch_archive("http://x/c.zip", tmp_path / "c.zip", stop_event=stop)

    def test_cancelled_download_leaves_no_part(self, tmp_path, monkeypatch):
        """После отмены .part не должен остаться в каталоге моделей."""
        import threading

        import requests

        monkeypatch.setattr(requests, "get", self._fake_response([b"x" * 16] * 4, 64))
        stop = threading.Event()
        stop.set()
        with pytest.raises(models.DownloadCancelled):
            models.download_model("ru", "large", tmp_path, stop_event=stop)
        leftovers = list(tmp_path.glob("*.part"))
        assert not leftovers, f"остался мусор: {leftovers}"

    def test_cancellation_is_not_retried(self, tmp_path, monkeypatch):
        import threading

        import requests

        calls = []

        def counting(*a, **k):
            calls.append(1)
            return self._fake_response([b"x" * 16], 16)()

        monkeypatch.setattr(requests, "get", counting)
        stop = threading.Event()
        stop.set()
        with pytest.raises(models.DownloadCancelled):
            models._fetch_archive(
                "http://x/d.zip", tmp_path / "d.zip", attempts=3, stop_event=stop
            )
        assert len(calls) <= 1, "отмена не должна перезапускать попытки"
