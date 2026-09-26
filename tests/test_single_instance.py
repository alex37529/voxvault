"""Проверка единственного экземпляра приложения (single_instance.py)."""

from __future__ import annotations

import pytest

from dictophone import single_instance

pytest.importorskip("PySide6", reason="PySide6 не установлен — GUI-проверки пропущены")


@pytest.fixture(autouse=True)
def _real_lock(monkeypatch):
    """Тесты проверяют настоящий замок, а не аварийный обход из conftest."""
    monkeypatch.delenv(single_instance.NO_LOCK_ENV, raising=False)


class TestSingleInstance:
    def test_first_instance_acquires(self, tmp_path):
        guard = single_instance.SingleInstance(path=tmp_path / "run.lock")
        try:
            assert guard.acquire() is True
        finally:
            guard.release()

    def test_second_instance_is_rejected(self, tmp_path):
        path = tmp_path / "run.lock"
        first = single_instance.SingleInstance(path=path)
        assert first.acquire() is True
        try:
            second = single_instance.SingleInstance(path=path)
            assert second.acquire() is False
            assert second.acquired is False
        finally:
            first.release()

    def test_lock_is_reusable_after_release(self, tmp_path):
        path = tmp_path / "run.lock"
        first = single_instance.SingleInstance(path=path)
        first.acquire()
        first.release()
        second = single_instance.SingleInstance(path=path)
        try:
            assert second.acquire() is True
        finally:
            second.release()

    def test_context_manager_raises_when_busy(self, tmp_path):
        path = tmp_path / "run.lock"
        first = single_instance.SingleInstance(path=path)
        first.acquire()
        try:
            with pytest.raises(RuntimeError):
                with single_instance.SingleInstance(path=path):
                    pass
        finally:
            first.release()

    def test_context_manager_releases_on_exit(self, tmp_path):
        path = tmp_path / "run.lock"
        with single_instance.SingleInstance(path=path):
            pass
        assert single_instance.SingleInstance(path=path).acquire() is True

    def test_env_switch_disables_lock(self, tmp_path, monkeypatch):
        monkeypatch.setenv(single_instance.NO_LOCK_ENV, "1")
        path = tmp_path / "run.lock"
        first = single_instance.SingleInstance(path=path)
        second = single_instance.SingleInstance(path=path)
        try:
            assert first.acquire() is True
            assert second.acquire() is True
        finally:
            first.release()
            second.release()

    def test_lock_dir_is_user_writable(self, tmp_path, monkeypatch):
        """Замок лежит в пользовательском каталоге, а не рядом с exe."""
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        path = single_instance.lock_dir()
        assert path == tmp_path / "VoxVault"
        assert path.is_absolute()
