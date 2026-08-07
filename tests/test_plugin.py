"""Tests for Agent Plugins generation and instruction template."""
from pathlib import Path

from context_engine.editors import get_instructions_base


def test_instructions_base_loads_from_file():
    """Instruction template must load from data/instructions.md."""
    text = get_instructions_base()
    assert "context_search" in text
    assert "record_decision" in text
    assert "session_recall" in text
    assert len(text) > 100


def test_instructions_base_has_no_claude_specific_content():
    """The base template is agent-neutral (no Claude Code references)."""
    text = get_instructions_base()
    assert "Claude Code" not in text
    assert "CLAUDE.md" not in text
