import os

import pytest

from routemaker.config import load_env
from routemaker.llm import LLMError, call_tool


def test_load_env(tmp_path, monkeypatch):
    monkeypatch.delenv("RM_TEST_A", raising=False)
    monkeypatch.setenv("RM_TEST_B", "keep")
    f = tmp_path / ".env"
    f.write_text('# c\nRM_TEST_A="abc"\nRM_TEST_B=new\nEMPTY=\n', encoding="utf-8")
    load_env(f)
    assert os.environ["RM_TEST_A"] == "abc"
    assert os.environ["RM_TEST_B"] == "keep"
    assert "EMPTY" not in os.environ


def test_missing_key_message(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LLMError, match="지금은 AI 분석을 쓸 수 없어요"):
        call_tool("s", "u", "t", {"type": "object"})
