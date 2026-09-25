"""Тесты аудио и распознавания (transcribe.py) — без реальных моделей VOSK."""
from __future__ import annotations

import json
import threading
import wave
from pathlib import Path

import pytest

from dictophone import transcribe


class FakeRecognizer:
    """Подмена KaldiRecognizer: отдаёт заранее заданные результаты."""

    def __init__(self, *args, **kwargs):
        self._n = 0

    def SetWords(self, flag):  # noqa: N802 - имя как в VOSK
        self._words = flag

    def AcceptWaveform(self, data):  # noqa: N802
        self._n += 1
        return self._n >= 2

    def Result(self):  # noqa: N802
        return json.dumps({"text": "финальный"})

    def PartialResult(self):  # noqa: N802
        return json.dumps({"partial": "черновой"})

    def FinalResult(self):  # noqa: N802
        return json.dumps({"text": "хвост"})


@pytest.fixture
def patched_vosk(monkeypatch):
    """Подменяет vosk.KaldiRecognizer на FakeRecognizer."""
    import sys
    import types

    fake = types.ModuleType("vosk")
    fake.KaldiRecognizer = FakeRecognizer
    monkeypatch.setitem(sys.modules, "vosk", fake)
    return fake


class TestToWav16k:
    def test_passthrough_for_valid_wav(self, make_wav):
        path = make_wav("ok.wav")
        assert transcribe.to_wav_16k(path) == path

    def test_converts_when_params_differ(self, make_wav, monkeypatch, tmp_path):
        src = make_wav("bad.wav", rate=44100, channels=2)
        produced = {}

        def fake_run(cmd, **kw):
            produced["cmd"] = cmd
            out = Path(cmd[-1])
            with wave.open(str(out), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes(b"\x00" * 3200)
            return None

        monkeypatch.setattr(transcribe.shutil, "which", lambda n: "ffmpeg")
        monkeypatch.setattr(transcribe.subprocess, "run", fake_run)
        out = transcribe.to_wav_16k(src)
        assert out.suffix == ".wav"
        assert "16000" in produced["cmd"]
        with wave.open(str(out), "rb") as w:
            assert w.getframerate() == 16000 and w.getnchannels() == 1

    def test_no_ffmpeg_raises_systemexit(self, make_wav, monkeypatch):
        src = make_wav("bad2.wav", rate=8000)
        monkeypatch.setattr(transcribe.shutil, "which", lambda n: None)
        with pytest.raises(SystemExit, match="ffmpeg"):
            transcribe.to_wav_16k(src)


class TestTranscribeFile:
    def test_joins_segments(self, make_wav, patched_vosk):
        # нужно >= 2 чанков, чтобы FakeRecognizer закрыл сегмент
        wav = make_wav(seconds=1.5)
        text = transcribe.transcribe_file(object(), wav)
        assert "финальный" in text
        assert "хвост" in text


class TestIterMic:
    """Микрофон проверяем с подменённым sounddevice — без реального устройства."""

    @pytest.fixture
    def fake_sounddevice(self, monkeypatch):
        import sys
        import types

        class FakeStream:
            def __init__(self, **kw):
                self.kw = kw
                self._reads = 0

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n):
                self._reads += 1
                if self._reads > 4:      # иначе тест зациклится
                    raise KeyboardInterrupt
                return (b"\x00" * n * 2), False

        module = types.ModuleType("sounddevice")
        module.RawInputStream = FakeStream
        monkeypatch.setitem(sys.modules, "sounddevice", module)
        return module

    def test_yields_partial_and_final(self, patched_vosk, fake_sounddevice):
        events = list(transcribe.iter_mic(object()))
        kinds = {e.kind for e in events}
        assert transcribe.PARTIAL in kinds
        assert transcribe.FINAL in kinds
        assert all(isinstance(e, transcribe.SpeechEvent) for e in events)

    def test_device_is_passed_to_stream(self, patched_vosk, fake_sounddevice):
        seen = {}
        original = fake_sounddevice.RawInputStream

        def spy(**kw):
            seen.update(kw)
            return original(**kw)

        fake_sounddevice.RawInputStream = spy
        list(transcribe.iter_mic(object(), device=3))
        assert seen.get("device") == 3

    def test_stop_event_ends_stream(self, patched_vosk, fake_sounddevice):
        stop = threading.Event()
        stop.set()
        events = list(transcribe.iter_mic(object(), stop_event=stop))
        # поток сразу остановлен, но финальный сброс всё равно отдаётся
        assert [e.kind for e in events] == [transcribe.FINAL]

    def test_pause_discards_audio_until_resumed(self, patched_vosk, fake_sounddevice):
        pause = threading.Event()
        pause.set()
        capture = transcribe.Capture()
        events = list(transcribe.iter_mic(
            object(), pause_event=pause, capture=capture
        ))
        assert capture.audio_s == 0.0
        assert [e.kind for e in events] == [transcribe.FINAL]

    def test_transcribe_mic_returns_text(self, patched_vosk, fake_sounddevice, capsys):
        text = transcribe.transcribe_mic(object())
        assert "финальный" in text
        capsys.readouterr()


class TestPcmHelpers:
    """Распознавание сырого PCM и измерение уровня (для проверки микрофона)."""

    def test_pcm_peak_quiet(self):
        assert transcribe.pcm_peak(b"\x00\x00" * 100) == 0.0

    def test_pcm_peak_loud(self):
        import struct

        pcm = struct.pack("<" + "h" * 100, *([32767] * 100))
        assert transcribe.pcm_peak(pcm) == pytest.approx(1.0, abs=0.01)

    def test_pcm_peak_half(self):
        import struct

        pcm = struct.pack("<" + "h" * 10, *([16384] * 10))
        assert transcribe.pcm_peak(pcm) == pytest.approx(0.5, abs=0.01)

    def test_pcm_peak_empty(self):
        assert transcribe.pcm_peak(b"") == 0.0

    def test_pcm_peak_ignores_odd_tail(self):
        # нечётное число байт не должно ронять array.frombytes
        assert transcribe.pcm_peak(b"\x01\x00\x02") >= 0.0

    def test_recognize_pcm(self, patched_vosk):
        pcm = b"\x00" * 40000        # ~1.2 с
        text = transcribe.recognize_pcm(object(), pcm)
        assert "финальный" in text or "хвост" in text


class TestFacadeOutput:
    def test_writes_output_file(self, make_wav, patched_vosk, monkeypatch, tmp_path):
        src = make_wav("speech.wav")
        out = tmp_path / "nested" / "result.txt"
        # подменяем загрузку модели, чтобы не качать 50 МБ в тестах
        monkeypatch.setattr("dictophone.models.load_model", lambda *a, **k: object())
        result = transcribe.transcribe(src, output=out)
        assert isinstance(result, transcribe.Result)
        assert out.is_file()
        assert out.read_text(encoding="utf-8").strip() == result.text

    def test_postprocess_off_keeps_raw(self, make_wav, patched_vosk,
                                       monkeypatch, tmp_path):
        src = make_wav("speech.wav")
        out = tmp_path / "raw.txt"
        monkeypatch.setattr("dictophone.models.load_model", lambda *a, **k: object())
        result = transcribe.transcribe(src, output=out, postprocess="off")
        # без постобработки в конце нет точки
        assert not result.text.endswith(".")


class TestResultAndCapture:
    def test_capture_avg_conf(self):
        cap = transcribe.Capture()
        assert cap.avg_conf == 0.0
        cap.words, cap.conf_sum = 2, 1.5
        assert cap.avg_conf == 0.75

    def test_capture_add_segment(self):
        cap = transcribe.Capture()
        cap.add_segment("раз")
        assert cap.segments == ["раз"]

    def test_result_chars(self):
        assert transcribe.Result(text="абв").chars == 3

    def test_recognize_file_reports_duration(self, make_wav, patched_vosk):
        wav = make_wav(seconds=1.5)
        res = transcribe.recognize_file(object(), wav)
        assert res.audio_s == 1.5
        assert "финальный" in res.text

    def test_wav_duration_helper(self, make_wav):
        assert transcribe.wav_duration_s(make_wav(seconds=2.0)) == 2.0

    def test_wav_duration_bad_file(self, tmp_path):
        bad = tmp_path / "not.wav"
        bad.write_text("nope", encoding="utf-8")
        assert transcribe.wav_duration_s(bad) == 0.0
