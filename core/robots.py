from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser


class RobotsChecker:
    def __init__(self, base_url: str):
        robots_url = urljoin(base_url, "/robots.txt")
        self.parser = RobotFileParser()
        self.parser.set_url(robots_url)
        self.parser.read()

    def is_allowed(self, url: str, user_agent: str = "*") -> bool:
        return self.parser.can_fetch(user_agent, url)
