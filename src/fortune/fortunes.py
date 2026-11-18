"""Where the fortunes come from. By default, one fortune per line in data/fortunes.txt."""

import random
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

DEFAULT_FILE = files("fortune") / "data" / "fortunes.txt"


class FortuneSource:
    """Holds the fortunes in memory and hands out a random one."""

    def __init__(self, path: Path | Traversable | None = None):
        self.path = path or DEFAULT_FILE
        # Read once at start-up: every request is then served from memory
        lines = self.path.read_text(encoding="utf-8").splitlines()
        self.fortunes = [line.strip() for line in lines if line.strip()]
        if not self.fortunes:
            raise ValueError(f"no fortunes in {self.path}")

    def random(self) -> str:
        """Return one fortune, chosen at random."""
        return random.choice(self.fortunes)
