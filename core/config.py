from pathlib import Path
from typing import Any

import yaml


InvalidProfileError = ValueError


class ProfileLoader:
    REQUIRED_KEYS = ("site_name", "engine", "start_url", "fields")
    VALID_ENGINES = ("static", "browser")

    def load(self, path: str | Path) -> dict[str, Any]:
        profile_path = Path(path)

        try:
            content = profile_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise InvalidProfileError(
                f"Unable to read profile: {profile_path}"
            ) from exc

        try:
            profile = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            raise InvalidProfileError(
                f"Invalid YAML in profile: {profile_path}"
            ) from exc

        if not isinstance(profile, dict):
            raise InvalidProfileError("Profile must be a YAML mapping.")

        self.validate(profile)
        return profile

    def validate(self, profile: dict[str, Any]) -> None:
        for key in self.REQUIRED_KEYS:
            if key not in profile:
                raise InvalidProfileError(f"Missing required key: {key}")

        engine = profile["engine"]
        if engine not in self.VALID_ENGINES:
            raise InvalidProfileError(
                "Invalid engine.\n\nExpected:\nstatic\nbrowser\n\nReceived:\n"
                f"{engine}"
            )

        start_url = profile["start_url"]
        if not isinstance(start_url, str) or not start_url.startswith(
            ("http://", "https://")
        ):
            raise InvalidProfileError(
                "Invalid start_url. Expected a URL starting with http:// or https://"
            )

        fields = profile["fields"]
        if not isinstance(fields, dict):
            raise InvalidProfileError("Invalid fields. Expected a dictionary.")
