"""Smoke tests for the scaffolding: every module imports, and the config reads its defaults."""

import importlib

import pytest

from fortune.config import Config
from fortune.fortunes import DEFAULT_FILE


@pytest.mark.parametrize("module", [
    "fortune", "fortune.__main__", "fortune.config", "fortune.election",
    "fortune.fortunes", "fortune.web", "fortune.web.app",
])
def test_module_imports(module):
    importlib.import_module(module)


def test_config_defaults():
    assert Config.from_env({}) == Config(web_port=8080, log_level="INFO")


def test_config_reads_env():
    assert Config.from_env({"WEB_PORT": "9999", "LOG_LEVEL": "debug"}) == Config(9999, "DEBUG")


def test_config_rejects_bad_port():
    with pytest.raises(ValueError, match="WEB_PORT"):
        Config.from_env({"WEB_PORT": "abc"})


def test_fortunes_file_is_packaged():
    assert DEFAULT_FILE.read_text().strip()
