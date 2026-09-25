"""Фоновые задачи Qt-интерфейса: загрузка модели, микрофон, скачивание.

Все на QRunnable + сигналы: блокирующие C-вызовы (VOSK Model, сеть) выполняются
в фоновом потоке и не блокируют окно. Emit защищены от «Signal source has been
deleted»: если окно закрылось раньше, чем задача завершилась, таск молча
выходит, а не падает.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Optional

from PySide6 import QtCore

from dictophone import models


class LoadSignals(QtCore.QObject):
    """Сигналы загрузчика модели."""
    phase = QtCore.Signal(str, float)     # (фаза, прошло секунд)
    ready = QtCore.Signal(object)          # готовая модель
    failed = QtCore.Signal(str)


class LoadTask(QtCore.QRunnable):
    """Загрузка модели в фоне.

    auto_download=False для предогрева: не установленная модель НЕ должна
    молча качать 1.8 ГБ при старте приложения.
    """

    def __init__(self, model_dir: Path, lang: str, size: Optional[str],
                 auto_download: bool = True):
        super().__init__()
        self.signals = LoadSignals()
        self._model_dir = model_dir
        self._lang = lang
        self._size = size
        self._auto_download = auto_download
        self._cancelled = False

    def cancel(self) -> None:
        """Пометить задачу ненужной (окно закрылось)."""
        self._cancelled = True

    def _emit(self, sig, *args) -> None:
        if self._cancelled:
            return
        try:
            sig.emit(*args)
        except RuntimeError:
            # 'Signal source has been deleted' — окно уже уничтожено
            self._cancelled = True

    def run(self) -> None:  # pragma: no cover - требует реальной модели
        try:
            model = models.load_model(
                self._model_dir, self._lang, self._size,
                auto_download=self._auto_download,
                progress_cb=lambda p, e: self._emit(self.signals.phase, p, e),
            )
            self._emit(self.signals.ready, model)
        except SystemExit as e:
            self._emit(self.signals.failed, str(e))
        except Exception as e:  # noqa: BLE001
            self._emit(self.signals.failed, f"{type(e).__name__}: {e}")


class MicSignals(QtCore.QObject):
    """Сигналы распознавания с микрофона."""
    event = QtCore.Signal(str, str)        # (kind, text)
    finished = QtCore.Signal(object)       # Capture
    failed = QtCore.Signal(str)


class MicTask(QtCore.QRunnable):
    """Распознавание с микрофона в фоне; остановка — через stop_event."""

    def __init__(self, model, device: Optional[int], stop: threading.Event,
                 pause: Optional[threading.Event] = None):
        super().__init__()
        self.signals = MicSignals()
        self._model = model
        self._device = device
        self._stop = stop
        self._pause = pause
        self.capture = None

    def run(self) -> None:  # pragma: no cover - требует микрофона
        from dictophone import transcribe

        capture = transcribe.Capture()
        self.capture = capture
        try:
            for ev in transcribe.iter_mic(
                self._model, device=self._device,
                stop_event=self._stop, pause_event=self._pause,
                capture=capture,
            ):
                try:
                    self.signals.event.emit(ev.kind, ev.text)
                except RuntimeError:
                    return
            self.signals.finished.emit(capture)
        except SystemExit as e:
            try:
                self.signals.failed.emit(str(e))
            except RuntimeError:
                pass
        except Exception as e:  # noqa: BLE001
            try:
                self.signals.failed.emit(f"{type(e).__name__}: {e}")
            except RuntimeError:
                pass


class MicTestSignals(QtCore.QObject):
    """Сигналы проверки микрофона."""
    result = QtCore.Signal(str)      # (текст + уровень)
    failed = QtCore.Signal(str)


class MicTestTask(QtCore.QRunnable):
    """Записать пару секунд и распознать — проверка, что микрофон живой.

    Модель необязательна: без неё покажем только уровень сигнала, чтобы
    пользователь понял, ловит ли микрофон звук.
    """

    def __init__(self, device: Optional[int], seconds: float = 3.0, model=None):
        super().__init__()
        self.signals = MicTestSignals()
        self._device = device
        self._seconds = seconds
        self._model = model

    def run(self) -> None:  # pragma: no cover - требует микрофона
        from dictophone import transcribe

        try:
            import sounddevice as sd
        except ImportError as e:
            self.signals.failed.emit(str(e))
            return
        try:
            rate = transcribe.SAMPLE_RATE
            block = transcribe.BLOCK_SAMPLES
            frames = int(rate * self._seconds)
            with sd.RawInputStream(
                samplerate=rate, blocksize=block, dtype="int16",
                channels=1, device=self._device,
            ) as stream:
                chunks: list[bytes] = []
                got = 0
                while got < frames:
                    data, _ = stream.read(block)
                    chunks.append(bytes(data))
                    got += len(bytes(data)) // 2
            pcm = b"".join(chunks)
            if not pcm:
                self.signals.result.emit("Нет данных с микрофона.")
                return
            peak = transcribe.pcm_peak(pcm)
            self.signals.result.emit(f"Уровень сигнала: {peak * 100:.0f}%")
            if self._model is not None:
                text = transcribe.recognize_pcm(self._model, pcm)
                if text:
                    self.signals.result.emit(f"Услышано: «{text}»")
                else:
                    self.signals.result.emit("Звук есть, но речь не распознана.")
        except Exception as e:  # noqa: BLE001
            self.signals.failed.emit(f"{type(e).__name__}: {e}")


class ModelDownloadSignals(QtCore.QObject):
    """Сигналы фонового скачивания модели."""
    progress = QtCore.Signal(int, int)     # (скачано, всего)
    done = QtCore.Signal(str)               # язык
    failed = QtCore.Signal(str)
    cancelled = QtCore.Signal()


class ModelDownloadTask(QtCore.QRunnable):
    """Скачивание модели в фоне. Отмена — через stop_event.

    Здесь прогресс НАСТОЯЩИЙ: сервер отдаёт content-length, поэтому видно
    проценты (в отличие от загрузки модели в память, где VOSK молчит).
    """

    def __init__(self, model_dir: Path, lang: str, size: str,
                 stop: threading.Event):
        super().__init__()
        self.signals = ModelDownloadSignals()
        self.model_dir = model_dir
        self.lang = lang
        self.size = size
        self.stop_event = stop
        self.started = time.time()

    def run(self) -> None:  # pragma: no cover - требует сети
        try:
            models.download_model(
                self.lang, self.size, self.model_dir,
                progress_cb=self.signals.progress.emit,
                stop_event=self.stop_event,
            )
        except models.DownloadCancelled:
            self.signals.cancelled.emit()
        except SystemExit as e:
            self.signals.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001
            self.signals.failed.emit(f"{type(e).__name__}: {e}")
        else:
            self.signals.done.emit(self.lang)
