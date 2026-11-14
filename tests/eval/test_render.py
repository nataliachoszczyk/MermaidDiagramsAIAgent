import pytest

from mermaiddiagramsaiagent.eval.render import PUPPETEER_CONFIG_ENV, puppeteer_args


def test_no_puppeteer_config_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PUPPETEER_CONFIG_ENV, raising=False)
    assert puppeteer_args() == []


def test_puppeteer_config_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PUPPETEER_CONFIG_ENV, "/tmp/puppeteer.json")
    assert puppeteer_args() == ["-p", "/tmp/puppeteer.json"]
