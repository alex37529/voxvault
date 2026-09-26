"""История распознаваний в SQLite.

Каждое распознавание (файл или микрофон) сохраняется отдельной записью:
когда, что, каким языком/моделью/устройством, сколько audio и сам текст.
Отсюда — поиск по прошлым расшифровкам и просмотр их из GUI.

База по умолчанию: `%APPDATA%\\dictophone\\history.db`
(переопределяется `DICTOPHONE_DB` или настройкой `db_path`).
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, List, Optional

APP_NAME = "dictophone"
DB_ENV = "DICTOPHONE_DB"

SCHEMA = """
CREATE TABLE IF NOT EXISTS transcriptions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL,
    kind        TEXT    NOT NULL,          -- 'mic' | 'file'
    source      TEXT,                      -- путь к файлу (NULL для микрофона)
    lang        TEXT,
    model_size  TEXT,
    model_name  TEXT,
    device      TEXT,
    audio_s     REAL    DEFAULT 0,
    chars       INTEGER DEFAULT 0,
    text        TEXT    NOT NULL,
    output_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_created_at ON transcriptions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_lang       ON transcriptions(lang);
"""


def default_db_path() -> Path:
    """Путь к базе истории (существует она или нет)."""
    override = os.environ.get(DB_ENV)
    if override:
        return Path(override).expanduser()
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    return root / APP_NAME / "history.db"


@dataclass
class Entry:
    """Запись истории."""

    kind: str  # 'mic' | 'file'
    text: str
    created_at: Optional[str] = None  # ISO; None -> сейчас
    source: Optional[str] = None
    lang: Optional[str] = None
    model_size: Optional[str] = None
    model_name: Optional[str] = None
    device: Optional[str] = None
    audio_s: float = 0.0
    output_path: Optional[str] = None
    id: Optional[int] = None
    extra: dict[str, Any] = field(default_factory=dict)


class Storage:
    """Хранилище истории.

    Соединение НЕ хранится постоянно: SQLite-соединение привязано к потоку,
    который его открыл, а GUI пишет историю из рабочего потока. Поэтому
    соединение открывается на каждую операцию и сразу закрывается.
    Режим WAL позволяет читать из одного потока, пока другой пишет.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.path = Path(db_path) if db_path is not None else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()
        with closing(self._connect()) as conn:
            conn.executescript(SCHEMA)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.path), timeout=15.0)

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        with closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            yield conn

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        # записи сериализуем: избегаем «database is locked» при параллельной записи
        with self._write_lock, closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            yield conn
            conn.commit()

    # -- запись ------------------------------------------------------------
    def add(self, entry: Entry) -> int:
        """Сохранить запись, вернуть её id."""
        created = entry.created_at or datetime.now().isoformat(timespec="seconds")
        with self._write() as conn:
            cur = conn.execute(
                """
                INSERT INTO transcriptions
                    (created_at, kind, source, lang, model_size, model_name,
                     device, audio_s, chars, text, output_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created,
                    entry.kind,
                    entry.source,
                    entry.lang,
                    entry.model_size,
                    entry.model_name,
                    entry.device,
                    round(float(entry.audio_s), 2),
                    len(entry.text or ""),
                    entry.text or "",
                    entry.output_path,
                ),
            )
            return int(cur.lastrowid or 0)

    # -- чтение ------------------------------------------------------------
    def get(self, entry_id: int) -> Optional[dict]:
        with self._read() as conn:
            row = conn.execute(
                "SELECT * FROM transcriptions WHERE id = ?", (entry_id,)
            ).fetchone()
            return dict(row) if row else None

    def list(
        self,
        limit: int = 20,
        lang: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> List[dict]:
        """Последние записи (новые сверху).

        List[...], а не list[...]: метод называется list и перекрывает
        встроенный тип в области класса, из-за чего list[dict] в аннотации
        перестал бы быть типом.
        """
        sql = "SELECT * FROM transcriptions"
        clauses: list[str] = []
        params: list = []
        if lang:
            clauses.append("lang = ?")
            params.append(lang)
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit))
        with self._read() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def search(self, query: str, limit: int = 20) -> List[dict]:  # см. list()
        """Поиск подстроки в тексте/исходнике (LIKE)."""
        pattern = f"%{query.strip()}%"
        with self._read() as conn:
            rows = conn.execute(
                """
                SELECT * FROM transcriptions
                 WHERE text LIKE ? COLLATE NOCASE
                    OR IFNULL(source, '') LIKE ? COLLATE NOCASE
                 ORDER BY id DESC LIMIT ?
                """,
                (pattern, pattern, int(limit)),
            ).fetchall()
            return [dict(r) for r in rows]

    def count(self) -> int:
        with self._read() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM transcriptions").fetchone()[0])

    # -- удаление ----------------------------------------------------------
    def delete(self, entry_id: int) -> bool:
        with self._write() as conn:
            cur = conn.execute("DELETE FROM transcriptions WHERE id = ?", (entry_id,))
            return cur.rowcount > 0

    def clear(self) -> int:
        with self._write() as conn:
            cur = conn.execute("DELETE FROM transcriptions")
            return cur.rowcount

    def close(self) -> None:
        """Совместимость: постоянного соединения больше нет — ничего не делаем."""
        return

    def __enter__(self) -> Storage:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Вывод в терминал
# ---------------------------------------------------------------------------


def format_entry(row: dict, *, preview: int = 60) -> str:
    """Строка списка истории: дата, вид, язык, длина, начало текста."""
    when = (row.get("created_at") or "")[:16].replace("T", " ")
    kind = "микрофон" if row.get("kind") == "mic" else "файл"
    lang = row.get("lang") or "?"
    size = row.get("model_size") or "-"
    src = row.get("source") or row.get("device") or "-"
    src = Path(src).name if src != "-" else "-"
    text = (row.get("text") or "").replace("\n", " ").strip()
    if len(text) > preview:
        text = text[:preview] + "…"
    dur = row.get("audio_s") or 0
    return (
        f"[{row['id']:>4}] {when}  {kind:<8} {lang:<6} {size:<5} "
        f"{dur:>6.1f}s  {src:<22} {text}"
    )
