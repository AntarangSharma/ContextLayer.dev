"""Tier router unit tests."""
from __future__ import annotations

import os

import pytest

from contextlayer import tier as tier_mod


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("CONTEXTLAYER_TIER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    yield


def test_default_tier_is_hybrid_without_key(monkeypatch):
    r = tier_mod.resolve()
    assert r.tier == "hybrid"
    assert r.has_api_key is False
    assert r.can_call_llm is False
    assert r.llm_first is False


def test_hybrid_with_key_can_escalate(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    r = tier_mod.resolve()
    assert r.tier == "hybrid"
    assert r.can_call_llm is True
    assert r.llm_first is False
    assert r.escalation_threshold == 0.6


def test_hybrid_with_gemini_key_can_escalate(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSy-test")
    r = tier_mod.resolve()
    assert r.tier == "hybrid"
    assert r.can_call_llm is True
    assert r.llm_first is False
    assert r.escalation_threshold == 0.6


def test_hybrid_with_openai_key_can_escalate(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    r = tier_mod.resolve()
    assert r.tier == "hybrid"
    assert r.can_call_llm is True
    assert r.llm_first is False
    assert r.escalation_threshold == 0.6


def test_free_tier_never_calls_llm_even_with_key(monkeypatch):
    monkeypatch.setenv("CONTEXTLAYER_TIER", "free")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    r = tier_mod.resolve()
    assert r.tier == "free"
    assert r.can_call_llm is False
    assert r.escalation_threshold == 0.0


def test_premium_with_key_goes_llm_first(monkeypatch):
    monkeypatch.setenv("CONTEXTLAYER_TIER", "premium")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    r = tier_mod.resolve()
    assert r.tier == "premium"
    assert r.llm_first is True
    assert r.escalation_threshold == 1.0


def test_premium_without_key_degrades(monkeypatch):
    monkeypatch.setenv("CONTEXTLAYER_TIER", "premium")
    r = tier_mod.resolve()
    assert r.tier == "premium"
    assert r.can_call_llm is False
    assert r.llm_first is False  # no key → don't try LLM-first


def test_unknown_tier_falls_back_to_hybrid(monkeypatch):
    monkeypatch.setenv("CONTEXTLAYER_TIER", "enterprise")  # not a real value
    r = tier_mod.resolve()
    assert r.tier == "hybrid"
