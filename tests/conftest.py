"""Общие фикстуры тестов.

Путь к src/ добавляется, чтобы пакет был импортируемым без установки.
"""

from __future__ import annotations

import os
import sys
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Тесты не должны блокировать друг друга реальным замком запуска: проверка
# единственного экземпляра изолирована в tests/test_single_instance.py.
os.environ.setdefault("VOXVAULT_NO_SINGLE_INSTANCE", "1")


@pytest.fixture
def fake_model_dir(tmp_path: Path) -> Path:
    """Каталог с «установленными» моделями (только нужные файлы-маркеры)."""

    def make(name: str) -> Path:
        model = tmp_path / name
        (model / "am").mkdir(parents=True, exist_ok=True)
        (model / "am" / "final.mdl").write_bytes(b"fake")
        return model

    make("vosk-model-small-ru-0.22")
    make("vosk-model-ru-0.42")
    make("vosk-model-small-en-us-0.15")
    make("vosk-model-en-us-0.22")
    make("vosk-model-small-ar-tn-0.1-linto")  # НЕ должен попадать на --lang ar
    make("vosk-model-ar-mgb2-0.4")
    make("vosk-recasepunc-ru-0.22")  # не ASR-модель — игнорируется
    (tmp_path / "not-a-model").mkdir()  # мусор — игнорируется
    return tmp_path


@pytest.fixture
def make_wav(tmp_path: Path):
    """Создать WAV 16 кГц mono int16 заданной длительности (тишина)."""

    def _make(
        name: str = "sample.wav",
        seconds: float = 0.5,
        rate: int = 16000,
        channels: int = 1,
        width: int = 2,
    ) -> Path:
        path = tmp_path / name
        with wave.open(str(path), "wb") as w:
            w.setnchannels(channels)
            w.setsampwidth(width)
            w.setframerate(rate)
            w.writeframes(b"\x00" * int(rate * seconds) * channels * width)
        return path

    return _make
