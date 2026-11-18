import pytest

from fortune.fortunes import DEFAULT_FILE, FortuneSource


def test_loads_the_packaged_fortunes():
    source = FortuneSource()
    expected = [line for line in DEFAULT_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert source.fortunes == expected
    assert source.random() in expected


def test_skips_blank_lines_and_surrounding_spaces(tmp_path):
    path = tmp_path / "fortunes.txt"
    path.write_text("\n  first  \n\n second\n   \n", encoding="utf-8")
    assert FortuneSource(path).fortunes == ["first", "second"]


def test_random_eventually_returns_every_fortune(tmp_path):
    path = tmp_path / "fortunes.txt"
    path.write_text("a\nb\nc\n", encoding="utf-8")
    source = FortuneSource(path)
    assert {source.random() for _ in range(200)} == {"a", "b", "c"}


def test_empty_file_is_an_error(tmp_path):
    path = tmp_path / "fortunes.txt"
    path.write_text("\n \n", encoding="utf-8")
    with pytest.raises(ValueError, match="no fortunes"):
        FortuneSource(path)
