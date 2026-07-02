import urllib.request
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser


class RobotsChecker:
    USER_AGENT = "Mozilla/5.0 (compatible; UniversalDataExtractor/1.0)"

    def __init__(self, base_url: str):
        robots_url = urljoin(base_url, "/robots.txt")
        self.parser = RobotFileParser()
        self.parser.set_url(robots_url)

        try:
            request = urllib.request.Request(
                robots_url,
                headers={"User-Agent": self.USER_AGENT},
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                content = response.read().decode("utf-8", errors="replace")
            self.parser.parse(content.splitlines())
        except Exception:
            # Treat an unreadable robots.txt as non-blocking so transient
            # fetch failures do not incorrectly disallow every page.
            self.parser.allow_all = True

    def is_allowed(self, url: str, user_agent: str = "*") -> bool:
        return self.parser.can_fetch(user_agent, url)
