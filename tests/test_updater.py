"""Проверка обновлений: разбор версий, ответ GitHub, решение «новее/нет».

Сеть здесь не нужна: HTTP-слой подменяется функцией-заглушкой, поэтому
тесты не зависят ни от GitHub, ни от интернета.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from dictophone import __version__, updater


def _payload(tag="v9.9.9", **extra):
    payload = {
        "tag_name": tag,
        "html_url": "https://github.com/a/b/releases/tag/v9.9.9",
        "body": "  Что нового  ",
        "assets": [
            {
                "name": "SHA256SUMS.txt",
                "browser_download_url": "https://example/SHA256SUMS.txt",
            },
            {
                "name": "VoxVault-9.9.9-win64.zip",
                "browser_download_url": "https://example/VoxVault-9.9.9-win64.zip",
            },
        ],
    }
    payload.update(extra)
    return payload


class TestVersionParsing:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("v0.1.1", (0, 1, 1)),
            ("0.2.0", (0, 2, 0)),
            ("  v1.12.3  ", (1, 12, 3)),
            ("v0.2.0-rc1", (0, 2, 0)),
            ("release-2.0.1", (2, 0, 1)),
            ("мусор", (0, 0, 0)),
            ("", (0, 0, 0)),
        ],
    )
    def test_parse(self, text, expected):
        assert updater.parse_version(text) == expected

    def test_ten_is_newer_than_nine(self):
        """Строковое сравнение здесь ломается: '0.10.0' < '0.9.9'."""
        assert updater.is_newer("v0.10.0", "0.9.9") is True
        assert updater.is_newer("v0.9.9", "0.10.0") is False

    def test_same_and_older_are_not_newer(self):
        assert updater.is_newer(__version__, __version__) is False
        assert updater.is_newer("v0.0.1", __version__) is False

    def test_unparsable_is_never_newer(self):
        assert updater.is_newer("latest", __version__) is False


class TestRelease:
    def test_newer_release_is_parsed(self):
        release = updater.parse_release(_payload(), current="0.1.0")
        assert release is not None
        assert release.version == "9.9.9"  # без префикса 'v'
        assert release.notes == "Что нового"  # без пробелов по краям
        assert release.url.endswith("/v9.9.9")

    def test_download_url_points_to_zip(self):
        release = updater.parse_release(_payload(), current="0.1.0")
        assert release.download_url.endswith("VoxVault-9.9.9-win64.zip")
        assert release.asset_url().endswith(".zip")

    def test_without_asset_falls_back_to_page(self):
        payload = _payload(assets=[])
        release = updater.parse_release(payload, current="0.1.0")
        assert release.download_url is None
        assert release.asset_url() == release.url

    def test_same_or_older_release_returns_none(self):
        assert updater.parse_release(_payload(tag=__version__)) is None
        assert updater.parse_release(_payload(tag="v0.0.1")) is None

    def test_garbage_payload_returns_none(self):
        assert updater.parse_release(None) is None
        assert updater.parse_release([1, 2, 3]) is None
        assert updater.parse_release({}) is None
        assert updater.parse_release({"tag_name": "latest"}) is None

    def test_asset_picker_skips_non_zip(self):
        assets = [
            {
                "name": "VoxVault-1.2.3-win64.zip.sig",
                "browser_download_url": "https://example/sig",
            }
        ]
        assert updater.pick_asset(assets, "1.2.3") is None
        assert updater.pick_asset([], "1.2.3") is None


class TestFetch:
    def test_uses_releases_api(self):
        seen = {}

        def fake_get(url, timeout):
            seen["url"], seen["timeout"] = url, timeout
            return _payload(tag="v0.2.0")

        release = updater.fetch_latest("0.1.0", 3.0, get_json=fake_get)
        assert seen["url"] == updater.RELEASES_API
        assert seen["timeout"] == 3.0
        assert release.version == "0.2.0"

    def test_network_error_becomes_update_error(self):
        def boom(url, timeout):
            raise updater.UpdateError("connection reset")

        with pytest.raises(updater.UpdateError):
            updater.fetch_latest("0.1.0", get_json=boom)

    def test_missing_releases_is_not_an_error(self):
        """404 = релизов ещё нет; это «обновлений нет», а не поломка."""
        assert updater.fetch_latest("0.1.0", get_json=lambda url, t: None) is None

    def test_get_json_reports_html_response(self, monkeypatch):
        import requests

        class FakeResponse:
            status_code = 200
            headers: ClassVar[dict] = {"Content-Type": "text/html; charset=utf-8"}

            def json(self):
                raise ValueError("не JSON")

        monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse())
        with pytest.raises(updater.UpdateError) as err:
            updater._get_json(updater.RELEASES_PAGE, 5.0)
        message = str(err.value)
        assert "не JSON" in message
        assert "text/html" in message
        assert updater.RELEASES_PAGE in message  # адрес в сообщении

    def test_get_json_treats_404_as_no_releases(self, monkeypatch):
        import requests

        class FakeResponse:
            status_code = 404
            headers: ClassVar[dict] = {"Content-Type": "application/json"}

            def json(self):
                return {"message": "Not Found"}

        monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse())
        assert updater._get_json(updater.RELEASES_API, 5.0) is None

    def test_get_json_explains_rate_limit(self, monkeypatch):
        import requests

        class FakeResponse:
            status_code = 403
            headers: ClassVar[dict] = {"Content-Type": "application/json"}

        monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse())
        with pytest.raises(updater.UpdateError, match="лимит"):
            updater._get_json(updater.RELEASES_API, 5.0)

    def test_repository_url_is_voxvault(self):
        assert "alex37529/voxvault" in updater.RELEASES_API
        assert updater.RELEASES_API.startswith("https://")
        assert updater.TIMEOUT <= 30, "слишком долгий таймаут для проверки"

    def test_api_url_is_api_github_not_website(self):
        """Регресс: страница github.com отдаёт HTML, а не JSON.

        С адресом сайта вместо API проверка всегда падала с «непонятный
        ответ GitHub», хотя сеть и релиз были в порядке.
        """
        assert (
            f"https://api.github.com/repos/{updater.GITHUB_OWNER}"
            f"/{updater.GITHUB_REPO}/releases/latest"
        ) == updater.RELEASES_API
        assert updater.RELEASES_API.startswith("https://api.github.com/repos/")
        assert updater.RELEASES_API != updater.RELEASES_PAGE
        # страница релиза остаётся человеческой (её открывает кнопка)
        assert updater.RELEASES_PAGE.startswith("https://github.com/")

    def test_real_api_answers_json(self):
        """Боевая проверка адреса: сеть нужна, но молчание API хуже падения.

        Пропускается без сети — тест не должен ронять сборку офлайн.
        """
        import requests

        try:
            response = requests.get(
                updater.RELEASES_API,
                timeout=updater.TIMEOUT,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": updater.USER_AGENT,
                },
            )
        except Exception:  # noqa: BLE001 - офлайн
            pytest.skip("нет сети")
        if response.status_code != 200:
            pytest.skip(f"GitHub ответил {response.status_code}")
        assert isinstance(response.json(), dict)

    def test_user_agent_mentions_version(self):
        assert __version__ in updater.USER_AGENT
        assert "VoxVault" in updater.USER_AGENT


class TestCheckInterval:
    def test_never_checked_is_due(self):
        assert updater.is_due(None) is True
        assert updater.is_due(0) is True

    def test_recent_check_is_not_due(self):
        assert updater.is_due(1000.0, now=1000.0) is False
        assert updater.is_due(1000.0, now=1000.0 + updater.CHECK_INTERVAL_S - 1) is False

    def test_day_later_is_due(self):
        assert updater.is_due(1000.0, now=1000.0 + updater.CHECK_INTERVAL_S) is True
