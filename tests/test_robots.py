import urllib.error

from core.robots import RobotsChecker


class FakeResponse:
    def __init__(self, content: str) -> None:
        self._content = content

    def read(self) -> bytes:
        return self._content.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_robots_checker_uses_custom_user_agent_and_parses_rules(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_urlopen(request, timeout: int):
        captured["user_agent"] = request.headers["User-agent"]
        captured["url"] = request.full_url
        captured["timeout"] = str(timeout)
        return FakeResponse("User-agent: *\nDisallow: /private\n")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    checker = RobotsChecker("https://example.com/articles")

    assert captured["url"] == "https://example.com/robots.txt"
    assert captured["user_agent"] == RobotsChecker.USER_AGENT
    assert captured["timeout"] == "10"
    assert checker.is_allowed("https://example.com/public") is True
    assert checker.is_allowed("https://example.com/private") is False


def test_robots_checker_allows_when_robots_cannot_be_fetched(monkeypatch) -> None:
    def fake_urlopen(request, timeout: int):
        raise urllib.error.URLError("blocked")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    checker = RobotsChecker("https://example.com/articles")

    assert checker.is_allowed("https://example.com/private") is True
