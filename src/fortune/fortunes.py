"""Where the fortunes come from. By default, one fortune per line in data/fortunes.txt."""

from importlib.resources import files
from pathlib import Path

DEFAULT_FILE = files("fortune") / "data" / "fortunes.txt"


class FortuneSource:
    """Holds the fortunes in memory and hands out a random one."""

    def __init__(self, path: Path | None = None):
        self.path = path or DEFAULT_FILE

    def random(self) -> str:
        """Return one fortune, chosen at random."""
        raise NotImplementedError
