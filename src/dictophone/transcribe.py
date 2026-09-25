"""Аудио и распознавание речи (файл / микрофон).

Микрофон отдаёт поток событий (`iter_mic`) — слой пригоден и для CLI, и для
GUI: потребитель читает генератор в своём потоке и получает
`SpeechEvent(kind="partial"|"final", text=...)`. Печать, запись файла и
сохранение в историю — забота вызывающего кода.

Зависимости: models.load_model, postprocess, vosk, sounddevice (микрофон),
ffmpeg (только для не-WAV).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import threading
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional, Sequence

SAMPLE_RATE = 16000
BLOCK_SAMPLES = 6000  # ~0.4 с при 16 кГц — кадр для realtime
FILE_CHUNK_BYTES = 8000 * 2  # 0.5 с при 16 кГц, int16

PARTIAL = "partial"
FINAL = "final"


@dataclass
class SpeechEvent:
    """Событие распознавания: «на лету» (partial) или закрытый сегмент."""

    kind: str
    text: str


@dataclass
class Capture:
    """Накопительные метрики записи/чтения — заполняется по ходу."""

    audio_s: float = 0.0
    segments: list[str] = field(default_factory=list)
    words: int = 0
    conf_sum: float = 0.0

    @property
    def avg_conf(self) -> float:
        return self.conf_sum / self.words if self.words else 0.0

    def add_segment(self, text: str) -> None:
        self.segments.append(text)


@dataclass
class Result:
    """Итог распознавания."""

    text: str
    audio_s: float = 0.0
    avg_conf: float = 0.0
    segments: list[str] = field(default_factory=list)
    lang: Optional[str] = None

    @property
    def chars(self) -> int:
        return len(self.text)


# ---------------------------------------------------------------------------
# Аудио-утилиты
# ---------------------------------------------------------------------------

def to_wav_16k(src: Path) -> Path:
    """Вернуть путь к wav 16 кГц mono int16.

    Если файл уже подходит — возвращается без копирования. Иначе переконвертит
    через ffmpeg. Ошибка: SystemExit, если ffmpeg отсутствует.
    """
    if src.suffix.lower() == ".wav":
        try:
            with wave.open(str(src), "rb") as w:
                if (
                    w.getframerate() == SAMPLE_RATE
                    and w.getnchannels() == 1
                    and w.getsampwidth() == 2
                ):
                    return src
        except (wave.Error, OSError, EOFError):
            pass  # повреждённый/не-wav — пойдём через ffmpeg

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise SystemExit(
            "Файл не 16 кГц mono WAV, а ffmpeg не найден.\n"
            "Установите ffmpeg (winget install Gyan.FFmpeg)"
            " или сконвертируйте файл в 16 кГц mono WAV вручную."
        )

    tmp = Path(tempfile.gettempdir()) / f"{src.stem}_dictophone_16k.wav"
    subprocess.run(
        [ffmpeg, "-y", "-i", str(src),
         "-ar", str(SAMPLE_RATE), "-ac", "1", "-sample_fmt", "s16",
         "-f", "wav", str(tmp)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return tmp


def _ensure_parent(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def wav_duration_s(wav_path: Path) -> float:
    """Длительность wav в секундах (0.0, если не удалось прочитать)."""
    try:
        with wave.open(str(wav_path), "rb") as w:
            rate = w.getframerate() or SAMPLE_RATE
            return w.getnframes() / float(rate)
    except (wave.Error, OSError, EOFError):
        return 0.0


# ---------------------------------------------------------------------------
# Распознавание файла
# ---------------------------------------------------------------------------

def recognize_file(model, wav_path: Path, words: bool = True) -> Result:
    """Ядро распознавания файла: текст + длительность + средняя уверенность.

    words=True включает выравнивание по словам — без него не посчитать conf.
    """
    from vosk import KaldiRecognizer

    with wave.open(str(wav_path), "rb") as w:
        pcm = w.readframes(w.getnframes())
        rate = w.getframerate() or SAMPLE_RATE

    rec = KaldiRecognizer(model, SAMPLE_RATE)
    if words:
        rec.SetWords(True)

    cap = Capture()
    cap.audio_s = w.getnframes() / float(rate)

    segments: list[str] = []
    for i in range(0, len(pcm), FILE_CHUNK_BYTES):
        if rec.AcceptWaveform(pcm[i:i + FILE_CHUNK_BYTES]):
            text = _take_result(rec, cap)
            if text:
                segments.append(text)

    text = _take_result(rec, cap, final=True)
    if text:
        segments.append(text)
    return Result(
        text=" ".join(segments).strip(),
        audio_s=cap.audio_s,
        avg_conf=cap.avg_conf,
        segments=segments,
    )


def _take_result(rec, capture: Optional[Capture] = None, final: bool = False) -> str:
    """Разобрать Result()/FinalResult(): вернуть текст, накопить conf в capture."""
    raw = rec.FinalResult() if final else rec.Result()
    data = json.loads(raw)
    if capture is not None:
        for word in data.get("result") or []:
            conf = float(word.get("conf") or 0.0)
            if conf > 0:
                capture.words += 1
                capture.conf_sum += conf
    return data.get("text", "") or ""


def recognize_pcm(model, pcm: bytes, sample_rate: int = SAMPLE_RATE) -> str:
    """Распознать сырой PCM (int16 mono) — без записи во временный файл.

    Используется для коротких проверок микрофона, где файл не нужен.
    """
    from vosk import KaldiRecognizer

    rec = KaldiRecognizer(model, sample_rate)
    rec.SetWords(True)
    parts: list[str] = []
    for i in range(0, len(pcm), FILE_CHUNK_BYTES):
        if rec.AcceptWaveform(pcm[i:i + FILE_CHUNK_BYTES]):
            text = _take_result(rec)
            if text:
                parts.append(text)
    text = _take_result(rec, final=True)
    if text:
        parts.append(text)
    return " ".join(parts).strip()


def pcm_peak(pcm: bytes) -> float:
    """Пиковая громкость PCM int16 в диапазоне 0..1 (для индикатора уровня)."""
    import array

    if not pcm:
        return 0.0
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    if not samples:
        return 0.0
    return max(abs(s) for s in samples) / 32768.0


def transcribe_file(model, wav_path: Path, words: bool = False) -> str:
    """Совместимая обёртка: только текст."""
    return recognize_file(model, wav_path, words=words).text


def detect_language(
    models_by_lang: dict[str, object],
    wav_path: Path,
) -> tuple[str, Result]:
    """Определить язык файла: пробуем модели и берём лучшую по средней уверенности.

    Эвристика: у «не своего» языка слова получают низкий conf. Возвращает
    (lang, Result) лучшего кандидата.
    """
    best_lang, best_res = "", Result(text="", audio_s=0.0, avg_conf=-1.0)
    for lang, model in models_by_lang.items():
        res = recognize_file(model, wav_path, words=True)
        if res.avg_conf > best_res.avg_conf:
            best_lang, best_res = lang, res
    best_res.lang = best_lang
    return best_lang, best_res


# ---------------------------------------------------------------------------
# Микрофон: поток событий
# ---------------------------------------------------------------------------

def iter_mic(
    model,
    *,
    device: Optional[int] = None,
    sample_rate: int = SAMPLE_RATE,
    block: int = BLOCK_SAMPLES,
    stop_event: Optional[threading.Event] = None,
    pause_event: Optional[threading.Event] = None,
    words: bool = False,
    capture: Optional[Capture] = None,
) -> Iterator[SpeechEvent]:
    """Поток событий распознавания с микрофона.

    Остановка: `stop_event` (GUI) или Ctrl+C (CLI — исключение перехватывается
    внутри, чтобы успеть отдать последний сегмент). Пауза: `pause_event`;
    во время паузы входной поток читается и отбрасывается без распознавания.
    capture: заполняется длительностью и сегментами.
    """
    try:
        import sounddevice as sd
    except ImportError as e:
        raise SystemExit(
            "Для записи с микрофона нужна sounddevice: pip install sounddevice"
        ) from e

    from vosk import KaldiRecognizer

    rec = KaldiRecognizer(model, sample_rate)
    if words:
        rec.SetWords(True)

    last_partial = ""
    with sd.RawInputStream(
        samplerate=sample_rate, blocksize=block,
        dtype="int16", channels=1, device=device,
    ) as stream:
        while stop_event is None or not stop_event.is_set():
            try:
                data, _ = stream.read(block)
            except KeyboardInterrupt:
                break  # Ctrl+C — мягко доходим до финального сброса
            if pause_event is not None and pause_event.is_set():
                continue
            pcm = bytes(data)
            if capture is not None:
                capture.audio_s += len(pcm) / 2 / sample_rate
            if rec.AcceptWaveform(pcm):
                text = _take_result(rec, capture)
                last_partial = ""
                if text:
                    if capture is not None:
                        capture.add_segment(text)
                    yield SpeechEvent(FINAL, text)
            else:
                hyp = json.loads(rec.PartialResult()).get("partial", "")
                if hyp and hyp != last_partial:
                    last_partial = hyp
                    yield SpeechEvent(PARTIAL, hyp)

    # Финальный сброс: сегмент, который не закрылся автоматически.
    text = _take_result(rec, capture, final=True)
    if text:
        if capture is not None:
            capture.add_segment(text)
        yield SpeechEvent(FINAL, text)


def _clear_line() -> None:
    """Стереть текущую строку консоли (если это вообще терминал)."""
    try:
        if sys.stdout.isatty():
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()
    except Exception:
        pass


def transcribe_mic(
    model,
    *,
    device: Optional[int] = None,
    stop_event: Optional[threading.Event] = None,
    pause_event: Optional[threading.Event] = None,
    on_event=None,
    words: bool = False,
    capture: Optional[Capture] = None,
) -> str:
    """CLI-обёртка над iter_mic: печатает live-текст, возвращает результат."""
    parts: list[str] = []
    for event in iter_mic(
        model, device=device, stop_event=stop_event,
        pause_event=pause_event, words=words, capture=capture,
    ):
        if on_event is not None:
            on_event(event)
        if event.kind == FINAL:
            print("\n" + event.text, flush=True)
            parts.append(event.text)
        else:
            sys.stdout.write("\r\033[K" + "(... " + event.text + " ..)")
            sys.stdout.flush()
    _clear_line()
    return " ".join(p for p in parts if p).strip()


# ---------------------------------------------------------------------------
# Фасад: «даны файл/микрофон → Result»
# ---------------------------------------------------------------------------

def transcribe(
    source: Optional[Path] = None,
    *,
    lang: str = "ru",
    size: Optional[str] = None,
    model_dir: Optional[Path] = None,
    output: Optional[Path] = None,
    device: Optional[int] = None,
    words: bool = False,
    postprocess: str = "heuristic",
) -> Result:
    """Единый вход: source=None → микрофон, иначе файл.

    lang='auto' — определить язык файла, перебрав установленные модели.
    Возвращает Result; при заданном output текст пишется в файл.
    """
    from dictophone import models, postprocess as pp

    if model_dir is None:
        model_dir = models.DEFAULT_MODEL_DIR
    processor = pp.get_mode(postprocess)

    if source is None:
        model = models.load_model(model_dir, lang, size)
        capture = Capture()
        print("Слушаю микрофон. Говорите. Ctrl+C — остановка и сохранение.",
              flush=True)
        raw = transcribe_mic(
            model, device=device, words=words, capture=capture
        )
        result = Result(
            text=processor.apply(raw, capture.segments),
            audio_s=capture.audio_s,
            avg_conf=capture.avg_conf,
            segments=list(capture.segments),
            lang=lang,
        )
    else:
        wav = to_wav_16k(source)
        if lang == "auto":
            candidates = models.installed_langs(model_dir)
            if not candidates:
                raise SystemExit(
                    "Для --lang auto нужна хотя бы одна установленная модель"
                )
            loaded = {lg: models.load_model(model_dir, lg, size) for lg in candidates}
            detected, res = detect_language(loaded, wav)
            print(f"Определён язык: {detected}", flush=True)
            result = Result(
                text=processor.apply(res.text, res.segments),
                audio_s=res.audio_s,
                avg_conf=res.avg_conf,
                segments=res.segments,
                lang=detected,
            )
        else:
            model = models.load_model(model_dir, lang, size)
            res = recognize_file(model, wav, words=words or True)
            result = Result(
                text=processor.apply(res.text, res.segments),
                audio_s=res.audio_s,
                avg_conf=res.avg_conf,
                segments=res.segments,
                lang=lang,
            )
        print(result.text)

    if output is not None:
        _ensure_parent(output)
        output.write_text(result.text + "\n", encoding="utf-8")
        print(f"\nСохранено: {output}")
    return result
