# KENNY
"""Unit tests for Jev threshold → action routing (no live TypeSafe API)."""

import os

import pytest

from pr_agent.kenny.jev_checks import (
    auto_comment_min,
    hint_min,
    route_action,
)


@pytest.fixture(autouse=True)
def _clear_jev_threshold_env(monkeypatch):
    monkeypatch.delenv("JEV_AUTO_COMMENT_MIN", raising=False)
    monkeypatch.delenv("JEV_HINT_MIN", raising=False)


def test_default_thresholds():
    assert auto_comment_min() == 0.85
    assert hint_min() == 0.55


def test_route_action_defaults():
    assert route_action(0.90) == "auto_comment"
    assert route_action(0.85) == "auto_comment"
    assert route_action(0.70) == "hint_for_llm"
    assert route_action(0.55) == "hint_for_llm"
    assert route_action(0.54) == "ignore"
    assert route_action(0.0) == "ignore"


def test_route_action_respects_env(monkeypatch):
    monkeypatch.setenv("JEV_AUTO_COMMENT_MIN", "0.9")
    monkeypatch.setenv("JEV_HINT_MIN", "0.4")
    assert route_action(0.85) == "hint_for_llm"
    assert route_action(0.91) == "auto_comment"
    assert route_action(0.39) == "ignore"


def test_route_action_prefers_confidence_when_passed():
    # Explicit confidence overrides probability for the signal.
    assert route_action(0.99, confidence=0.2) == "ignore"
    assert route_action(0.1, confidence=0.9) == "auto_comment"


def test_invalid_threshold_env_falls_back(monkeypatch):
    monkeypatch.setenv("JEV_AUTO_COMMENT_MIN", "not-a-float")
    monkeypatch.setenv("JEV_HINT_MIN", "also-bad")
    assert auto_comment_min() == 0.85
    assert hint_min() == 0.55
