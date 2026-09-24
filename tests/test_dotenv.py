from __future__ import annotations

import os
from pathlib import Path

import pytest

from em_design_mcp.utils.dotenv import load_dotenv_file


def test_dotenv_values_are_loaded_when_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / ".env"
    path.write_text("EM_TEST_VALUE=from_file\nEM_QUOTED_VALUE=\"quoted text\"\n", encoding="utf-8")
    monkeypatch.delenv("EM_TEST_VALUE", raising=False)
    monkeypatch.delenv("EM_QUOTED_VALUE", raising=False)

    loaded = load_dotenv_file(path)

    assert loaded == {
        "EM_TEST_VALUE": "from_file",
        "EM_QUOTED_VALUE": "quoted text",
    }
    assert os.environ["EM_TEST_VALUE"] == "from_file"
    assert os.environ["EM_QUOTED_VALUE"] == "quoted text"


def test_dotenv_does_not_overwrite_existing_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / ".env"
    path.write_text("EM_EXISTING_VALUE=from_file\n", encoding="utf-8")
    monkeypatch.setenv("EM_EXISTING_VALUE", "from_os")

    loaded = load_dotenv_file(path)

    assert loaded == {}
    assert loaded.get("EM_EXISTING_VALUE") is None
    assert os.environ["EM_EXISTING_VALUE"] == "from_os"


def test_dotenv_ignores_comments_blank_lines_and_invalid_lines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / ".env"
    path.write_text(
        """
# comment

EM_ONE='one'
not-a-key-without-equals
  # indented comment
EM_TWO=two
""",
        encoding="utf-8",
    )
    monkeypatch.delenv("EM_ONE", raising=False)
    monkeypatch.delenv("EM_TWO", raising=False)

    loaded = load_dotenv_file(path)

    assert loaded == {"EM_ONE": "one", "EM_TWO": "two"}
