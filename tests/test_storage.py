"""Тесты истории распознаваний (storage.py)."""
from __future__ import annotations

import pytest

from dictophone import storage


@pytest.fixture
def db(tmp_path):
    with storage.Storage(tmp_path / "history.db") as s:
        yield s


def _entry(**kw) -> storage.Entry:
    base = dict(kind="mic", text="привет мир", lang="ru", audio_s=1.5)
    base.update(kw)
    return storage.Entry(**base)


class TestAddGet:
    def test_add_returns_id(self, db):
        assert db.add(_entry()) == 1
        assert db.add(_entry(text="второе")) == 2

    def test_get_roundtrip(self, db):
        entry_id = db.add(_entry(source="C:/a.wav", output_path="C:/out.txt",
                                 device="1", model_size="small"))
        row = db.get(entry_id)
        assert row["text"] == "привет мир"
        assert row["source"] == "C:/a.wav"
        assert row["device"] == "1"
        assert row["chars"] == len("привет мир")

    def test_get_missing(self, db):
        assert db.get(999) is None

    def test_created_at_filled(self, db):
        row = db.get(db.add(_entry()))
        assert row["created_at"]  # ISO-строка проставлена автоматически

    def test_empty_text_allowed(self, db):
        assert db.add(_entry(text="")) == 1

    def test_rounds_audio_seconds(self, db):
        row = db.get(db.add(_entry(audio_s=1.23456)))
        assert row["audio_s"] == 1.23


class TestListSearch:
    def test_newest_first(self, db):
        db.add(_entry(text="первая"))
        db.add(_entry(text="вторая"))
        rows = db.list(limit=10)
        assert rows[0]["text"] == "вторая"

    def test_limit(self, db):
        for i in range(5):
            db.add(_entry(text=f"запись {i}"))
        assert len(db.list(limit=2)) == 2

    def test_filter_by_lang_and_kind(self, db):
        db.add(_entry(lang="ru", kind="mic"))
        db.add(_entry(lang="en-us", kind="file", source="a.wav"))
        assert len(db.list(lang="ru")) == 1
        assert len(db.list(kind="file")) == 1
        assert len(db.list(lang="ru", kind="file")) == 0

    def test_search_finds_text(self, db):
        db.add(_entry(text="сегодня хорошая погода"))
        db.add(_entry(text="совсем другой текст"))
        rows = db.search("погода")
        assert len(rows) == 1 and "погода" in rows[0]["text"]

    def test_search_is_case_insensitive(self, db):
        db.add(_entry(text="Hello World"))
        assert len(db.search("hello")) == 1

    def test_search_by_source(self, db):
        db.add(_entry(kind="file", source="C:/docs/meeting.wav", text="x"))
        assert len(db.search("meeting")) == 1

    def test_search_no_match(self, db):
        db.add(_entry(text="привет"))
        assert db.search("zzz") == []


class TestDeleteClear:
    def test_delete(self, db):
        entry_id = db.add(_entry())
        assert db.delete(entry_id) is True
        assert db.get(entry_id) is None

    def test_delete_missing(self, db):
        assert db.delete(42) is False

    def test_clear(self, db):
        for _ in range(3):
            db.add(_entry())
        assert db.clear() == 3
        assert db.count() == 0


class TestPersistence:
    def test_data_survives_reopen(self, tmp_path):
        path = tmp_path / "history.db"
        with storage.Storage(path) as s:
            s.add(_entry(text="сохранится"))
        with storage.Storage(path) as s:
            assert s.count() == 1
            assert s.list()[0]["text"] == "сохранится"

    def test_schema_created_automatically(self, tmp_path):
        path = tmp_path / "sub" / "new.db"
        with storage.Storage(path) as s:
            assert path.exists() and s.count() == 0


class TestThreadSafety:
    """Соединение открывается на операцию: Storage можно использовать из GUI-потока
    и из рабочего потока одновременно (иначе SQLite ругается на check_same_thread)."""

    def test_write_from_other_thread(self, db):
        import threading

        errors: list[Exception] = []

        def worker():
            try:
                db.add(_entry(text="из потока"))
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        th = threading.Thread(target=worker)
        th.start()
        th.join()
        assert not errors, errors
        assert db.count() == 1

    def test_read_while_writing(self, tmp_path):
        import threading

        store = storage.Storage(tmp_path / "concurrent.db")
        done = threading.Event()
        errors: list[Exception] = []

        def writer():
            try:
                for i in range(30):
                    store.add(_entry(text=f"запись {i}"))
            except Exception as e:  # noqa: BLE001
                errors.append(e)
            finally:
                done.set()

        th = threading.Thread(target=writer)
        th.start()
        while not done.is_set():      # читаем параллельно с записью
            store.list(limit=5)
        th.join()
        assert not errors, errors
        assert store.count() == 30

    def test_parallel_writers_do_not_lock(self, tmp_path):
        import threading

        store = storage.Storage(tmp_path / "parallel.db")
        errors: list[Exception] = []

        def worker(n: int):
            try:
                for i in range(10):
                    store.add(_entry(text=f"поток {n} запись {i}"))
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, errors
        assert store.count() == 40


class TestFormat:
    def test_contains_key_fields(self, db):
        row = db.get(db.add(_entry(source="C:/x/meeting.wav")))
        line = storage.format_entry(row)
        assert "микрофон" in line or "файл" in line
        assert "ru" in line
        assert "meeting.wav" in line

    def test_truncates_long_text(self, db):
        row = db.get(db.add(_entry(text="а" * 500)))
        assert "…" in storage.format_entry(row, preview=20)
