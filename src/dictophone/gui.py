"""Графическое приложение (tkinter) поверх iter_mic — запасной вариант.

Основной интерфейс проекта — Qt (`gui_qt.py`, команда `gui-qt`). Эта версия
оставлена как рабочий откат и как пример «Tk без Qt». События из рабочего
потока идут через `queue` + `after()` (в Qt вместо этого сигналы).

Запуск: `py main.py gui`
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Optional

from dictophone import config as config_mod
from dictophone import devices as devices_mod
from dictophone import models, storage, transcribe
from dictophone.console import setup_console
from dictophone.transcript import PARTIAL, TranscriptBuffer

POLL_MS = 100  # как часто UI забирает события из очереди

#: Сообщения из рабочего потока в UI.
MSG_STATUS = "status"
MSG_PARTIAL = "partial"
MSG_FINAL = "final"
MSG_RESULT = "result"  # итоговый текст (авторитетный, как в файле)
MSG_DONE = "done"
MSG_ERROR = "error"


class DictophoneApp:
    """Главное окно tkinter-версии: настройки, запуск/стоп, текст, история."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Диктофон — распознавание речи")
        self.root.geometry("760x620")
        self.root.minsize(640, 520)

        self.cfg = config_mod.load_config()
        self.stop_event: Optional[threading.Event] = None
        self.worker: Optional[threading.Thread] = None
        self.queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.transcript = TranscriptBuffer()
        self.db = storage.Storage()

        self._build_widgets()
        self._refresh_devices()
        self._refresh_langs()
        self.root.after(POLL_MS, self._drain_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._set_status("Готово. Выберите параметры и нажмите «Старт».")

    # -- интерфейс ---------------------------------------------------------
    def _build_widgets(self) -> None:
        opts = ttk.Frame(self.root, padding=10)
        opts.pack(fill="x")

        ttk.Label(opts, text="Микрофон:").grid(row=0, column=0, sticky="w")
        self.device_box = ttk.Combobox(opts, state="readonly", width=42)
        self.device_box.grid(row=0, column=1, sticky="ew", padx=(6, 6))
        ttk.Button(opts, text="Обновить", command=self._refresh_devices).grid(
            row=0, column=2
        )

        ttk.Label(opts, text="Язык:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.lang_box = ttk.Combobox(opts, state="readonly", width=42)
        self.lang_box.grid(row=1, column=1, sticky="ew", padx=(6, 6), pady=(6, 0))
        self.lang_box.set(self.cfg.lang)

        ttk.Label(opts, text="Модель:").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.size_box = ttk.Combobox(
            opts, state="readonly", width=42, values=("auto", "small", "large")
        )
        self.size_box.grid(row=2, column=1, sticky="ew", padx=(6, 6), pady=(6, 0))
        self.size_box.set(self.cfg.size)

        ttk.Label(opts, text="Папка для текстов:").grid(
            row=3, column=0, sticky="w", pady=(6, 0)
        )
        self.out_var = tk.StringVar(
            value=self.cfg.output_dir or str(models.DEFAULT_OUTPUT_DIR)
        )
        ttk.Entry(opts, textvariable=self.out_var).grid(
            row=3, column=1, sticky="ew", padx=(6, 6), pady=(6, 0)
        )
        ttk.Button(opts, text="Обзор…", command=self._pick_output_dir).grid(
            row=3, column=2
        )

        ttk.Label(opts, text="Аудиофайл:").grid(row=4, column=0, sticky="w", pady=(6, 0))
        self.file_var = tk.StringVar()
        ttk.Entry(opts, textvariable=self.file_var).grid(
            row=4, column=1, sticky="ew", padx=(6, 6), pady=(6, 0)
        )
        ttk.Button(opts, text="Обзор…", command=self._pick_audio).grid(row=4, column=2)
        opts.columnconfigure(1, weight=1)

        bar = ttk.Frame(self.root, padding=(10, 0))
        bar.pack(fill="x")
        self.btn_mic = ttk.Button(
            bar, text="🎙 Запись с микрофона", command=self._start_mic
        )
        self.btn_mic.pack(side="left")
        self.btn_file = ttk.Button(bar, text="Распознать файл", command=self._start_file)
        self.btn_file.pack(side="left", padx=6)
        self.btn_stop = ttk.Button(bar, text="Стоп", command=self._stop, state="disabled")
        self.btn_stop.pack(side="left")
        ttk.Button(bar, text="Сохранить настройки", command=self._save_settings).pack(
            side="right"
        )
        ttk.Button(bar, text="История", command=self._open_history).pack(side="right")

        text_frame = ttk.Frame(self.root, padding=10)
        text_frame.pack(fill="both", expand=True)
        self.text = tk.Text(text_frame, wrap="word", font=("Segoe UI", 11))
        scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.text.tag_configure("partial", foreground="#777777")
        self._partial_mark = "partial_tail"
        self.text.mark_set(self._partial_mark, "end-1c")
        self.text.configure(state="disabled")

        self.status = ttk.Label(self.root, text="", anchor="w", padding=(10, 4))
        self.status.pack(fill="x")

    def _set_status(self, text: str) -> None:
        self.status.config(text=text)

    def _show_transcript(self) -> None:
        """Перерисовать поле по состоянию буфера (partial заменяется, не копится)."""
        body, tail_is_partial = self.transcript.render()
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        if body:
            if tail_is_partial:
                head = body.rsplit("\n", 1)[0] if "\n" in body else ""
                tail = body.split("\n")[-1]
                if head:
                    self.text.insert("end", head + "\n")
                self.text.insert("end", tail, "partial")
            else:
                self.text.insert("end", body)
        self.text.mark_set(self._partial_mark, "end-1c")
        self.text.see("end")
        self.text.configure(state="disabled")

    def _clear_transcript(self) -> None:
        self.transcript.reset()
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.mark_set(self._partial_mark, "end-1c")
        self.text.configure(state="disabled")

    # -- выпадающие списки -------------------------------------------------
    def _refresh_devices(self) -> None:
        values = ["По умолчанию"]
        self._device_specs: list[Optional[str]] = [None]
        try:
            for d in devices_mod.list_input_devices():
                mark = " *" if d["is_default"] else ""
                values.append(f"{d['index']}: {d['name']} ({d['channels']} кан.){mark}")
                self._device_specs.append(str(d["index"]))
        except devices_mod.DeviceError as e:
            self._set_status(str(e))
        self.device_box["values"] = values
        if self.cfg.device:
            wanted = str(self.cfg.device)
            for i, spec in enumerate(self._device_specs):
                if spec == wanted or wanted.lower() in values[i].lower():
                    self.device_box.current(i)
                    break
        else:
            self.device_box.current(0)

    def _refresh_langs(self) -> None:
        installed = models.installed_langs()
        self._lang_values = installed or models.known_langs()
        self.lang_box["values"] = self._lang_values
        if self.cfg.lang in self._lang_values:
            self.lang_box.set(self.cfg.lang)
        elif self._lang_values:
            self.lang_box.set(self._lang_values[0])

    # -- параметры ---------------------------------------------------------
    def _selected_device(self) -> Optional[int]:
        idx = self.device_box.current()
        if idx is None or idx <= 0:
            return None
        spec = self._device_specs[idx]
        try:
            return devices_mod.resolve_device(spec)
        except devices_mod.DeviceError:
            return None

    def _selected_size(self) -> Optional[str]:
        return None if self.size_box.get() == "auto" else self.size_box.get()

    def _selected_lang(self) -> str:
        return self.lang_box.get() or self.cfg.lang

    def _model_dir(self) -> Path:
        return (
            Path(self.cfg.model_dir) if self.cfg.model_dir else models.DEFAULT_MODEL_DIR
        )

    def _pick_output_dir(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.out_var.get() or ".")
        if chosen:
            self.out_var.set(chosen)

    def _pick_audio(self) -> None:
        chosen = filedialog.askopenfilename(
            filetypes=[("Аудио", "*.wav *.mp3 *.m4a *.ogg *.flac"), ("Все файлы", "*.*")]
        )
        if chosen:
            self.file_var.set(chosen)

    def _save_settings(self) -> None:
        try:
            self.cfg.lang = self._selected_lang()
            self.cfg.size = self._selected_size() or "auto"
            self.cfg.output_dir = self.out_var.get() or None
            spec = (
                self._device_specs[self.device_box.current()]
                if self.device_box.current() > 0
                else None
            )
            self.cfg.device = spec
            path = config_mod.save_config(self.cfg)
            self._set_status(f"Настройки сохранены: {path}")
        except (config_mod.ConfigError, OSError) as e:
            messagebox.showerror("Настройки", str(e))

    # -- запуск ------------------------------------------------------------
    def _set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        for btn in (self.btn_mic, self.btn_file):
            btn.configure(state=state)
        self.btn_stop.configure(state="normal" if running else "disabled")

    def _start_mic(self) -> None:
        self._clear_transcript()
        self.stop_event = threading.Event()
        self._set_running(True)
        threading.Thread(target=self._mic_worker, daemon=True).start()

    def _start_file(self) -> None:
        path = self.file_var.get().strip()
        if not path:
            messagebox.showwarning("Файл", "Выберите аудиофайл.")
            return
        if not Path(path).exists():
            messagebox.showerror("Файл", f"Файл не найден:\n{path}")
            return
        self._clear_transcript()
        self.stop_event = threading.Event()
        self._set_running(True)
        threading.Thread(
            target=self._file_worker, args=(Path(path),), daemon=True
        ).start()

    def _stop(self) -> None:
        if self.stop_event is not None:
            self.stop_event.set()
            self._set_status("Останавливаю…")

    # -- рабочие потоки ----------------------------------------------------
    def _emit(self, kind: str, payload: Any = None) -> None:
        self.queue.put((kind, payload))

    def _mic_worker(self) -> None:
        lang = self._selected_lang()
        size = self._selected_size()
        model_dir = self._model_dir()
        device = self._selected_device()
        capture = transcribe.Capture()
        try:
            self._emit(MSG_STATUS, f"Загружаю модель {lang}…")
            model = models.load_model(model_dir, lang, size)
            self._emit(MSG_STATUS, "Слушаю. Говорите.")
            for event in transcribe.iter_mic(
                model, device=device, stop_event=self.stop_event, capture=capture
            ):
                self._emit(
                    MSG_PARTIAL if event.kind == PARTIAL else MSG_FINAL, event.text
                )
            self._emit(MSG_STATUS, "Обрабатываю…")
            from dictophone import postprocess as pp

            text = pp.apply(" ".join(capture.segments), capture.segments)
            out = self._save_result(
                text,
                kind="mic",
                lang=lang,
                size=size,
                device=device,
                audio_s=capture.audio_s,
            )
            self.db.add(
                storage.Entry(
                    kind="mic",
                    text=text,
                    lang=lang,
                    model_size=size or "auto",
                    device=str(device) if device is not None else None,
                    audio_s=capture.audio_s,
                    output_path=str(out) if out else None,
                )
            )
            self._emit(MSG_RESULT, text)
            self._emit(MSG_DONE, f"Готово: {len(text)} симв.")
        except SystemExit as e:
            self._emit(MSG_ERROR, str(e))
        except Exception as e:  # noqa: BLE001
            self._emit(MSG_ERROR, f"{type(e).__name__}: {e}")

    def _file_worker(self, path: Path) -> None:
        lang = self._selected_lang()
        size = self._selected_size()
        model_dir = self._model_dir()
        try:
            self._emit(MSG_STATUS, f"Загружаю модель {lang}…")
            result = transcribe.transcribe(
                path, lang=lang, size=size, model_dir=model_dir, output=None
            )
            out = self._save_result(
                result.text,
                kind="file",
                lang=result.lang or lang,
                size=size,
                device=None,
                audio_s=result.audio_s,
                source=path,
            )
            self.db.add(
                storage.Entry(
                    kind="file",
                    text=result.text,
                    lang=result.lang or lang,
                    source=str(path),
                    model_size=size or "auto",
                    audio_s=result.audio_s,
                    output_path=str(out) if out else None,
                )
            )
            self._emit(MSG_RESULT, result.text)
            self._emit(MSG_DONE, f"Готово: {result.chars} симв., {result.audio_s:.1f} с")
        except SystemExit as e:
            self._emit(MSG_ERROR, str(e))
        except Exception as e:  # noqa: BLE001
            self._emit(MSG_ERROR, f"{type(e).__name__}: {e}")

    def _save_result(
        self,
        text: str,
        *,
        kind: str,
        lang: str,
        size: Optional[str],
        device: Optional[int],
        audio_s: float,
        source: Optional[Path] = None,
    ) -> Optional[Path]:
        from datetime import datetime

        out_dir = Path(self.out_var.get() or models.DEFAULT_OUTPUT_DIR)
        stem = source.stem if source else f"mic_{datetime.now():%Y%m%d_%H%M%S}"
        out = out_dir / f"{stem}.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
        self._emit(MSG_STATUS, f"Сохранено: {out}")
        return out

    # -- очередь событий -> UI --------------------------------------------
    def _drain_queue(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == MSG_STATUS:
                    self._set_status(str(payload))
                elif kind == MSG_PARTIAL:
                    self.transcript.add_partial(payload)
                    self._show_transcript()
                elif kind == MSG_FINAL:
                    self.transcript.add_final(payload)
                    self._show_transcript()
                elif kind == MSG_RESULT:
                    self.transcript.set_authoritative(payload)
                    self._show_transcript()
                elif kind == MSG_DONE:
                    self._set_running(False)
                    self._set_status(str(payload))
                elif kind == MSG_ERROR:
                    self._set_running(False)
                    self._set_status("Ошибка")
                    messagebox.showerror("Диктофон", str(payload))
        except queue.Empty:
            pass
        self.root.after(POLL_MS, self._drain_queue)

    def _open_history(self) -> None:
        HistoryWindow(self.root, self.db)

    def _on_close(self) -> None:
        if self.stop_event is not None:
            self.stop_event.set()
        self.db.close()
        self.root.destroy()


class HistoryWindow(tk.Toplevel):
    """Окно истории распознаваний."""

    def __init__(self, parent: tk.Misc, db: storage.Storage):
        super().__init__(parent)
        self.title("История распознаваний")
        self.geometry("900x480")
        self.db = db

        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        self.query = tk.StringVar()
        ttk.Label(top, text="Поиск:").pack(side="left")
        entry = ttk.Entry(top, textvariable=self.query, width=40)
        entry.pack(side="left", padx=6)
        entry.bind("<Return>", lambda _e: self._refresh())
        ttk.Button(top, text="Найти", command=self._refresh).pack(side="left")
        ttk.Button(top, text="Показать все", command=self._show_all).pack(
            side="left", padx=6
        )

        body = ttk.Frame(self, padding=8)
        body.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            body,
            columns=("id", "when", "kind", "lang", "dur", "preview"),
            show="headings",
            selectmode="browse",
        )
        for col, title, width in (
            ("id", "ID", 50),
            ("when", "Когда", 140),
            ("kind", "Вид", 90),
            ("lang", "Язык", 60),
            ("dur", "Длина", 70),
            ("preview", "Текст", 480),
        ):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, anchor="w")
        vsb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda _e: self._show_text())
        ttk.Button(self, text="Показать полный текст", command=self._show_text).pack(
            pady=6
        )
        self._show_all()

    def _fill(self, rows) -> None:
        self.tree.delete(*self.tree.get_children())
        for r in rows:
            kind = "микрофон" if r["kind"] == "mic" else "файл"
            preview = (r["text"] or "").replace("\n", " ")[:120]
            self.tree.insert(
                "",
                "end",
                iid=str(r["id"]),
                values=(
                    r["id"],
                    (r["created_at"] or "")[:16].replace("T", " "),
                    kind,
                    r["lang"] or "?",
                    f"{r['audio_s'] or 0:.1f}s",
                    preview,
                ),
            )

    def _show_all(self) -> None:
        self._fill(self.db.list(limit=500))

    def _refresh(self) -> None:
        q = self.query.get().strip()
        self._fill(self.db.search(q, limit=500) if q else self.db.list(limit=500))

    def _show_text(self) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        row = self.db.get(int(sel[0]))
        if not row:
            return
        win = tk.Toplevel(self)
        win.title(f"Запись #{row['id']}")
        win.geometry("700x420")
        box = tk.Text(win, wrap="word")
        box.pack(fill="both", expand=True, padx=8, pady=8)
        box.insert("1.0", row["text"] or "")
        box.configure(state="disabled")


def main(argv: Optional[list[str]] = None) -> int:
    """Запуск tkinter-версии. Возвращает код возврата."""
    setup_console()
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"Не удалось открыть окно (нужен графический сеанс): {e}")
        return 1
    DictophoneApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
