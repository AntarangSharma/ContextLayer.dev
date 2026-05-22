"""Unit tests for the unified LLM Client abstraction."""
from __future__ import annotations

import os
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from contextlayer.extract.llm_client import LLMClient


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    yield


def test_llm_client_initialization_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    with patch("anthropic.AsyncAnthropic") as mock_anthropic:
        client = LLMClient()
        assert client.provider == "anthropic"
        assert client._anthropic_client is not None
        assert client._openai_client is None
        mock_anthropic.assert_called_once()


def test_llm_client_initialization_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSy-test")
    with patch("openai.AsyncOpenAI") as mock_openai:
        client = LLMClient()
        assert client.provider == "gemini"
        assert client._openai_client is not None
        assert client._anthropic_client is None
        mock_openai.assert_called_once_with(
            api_key="AIzaSy-test",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
        )


def test_llm_client_initialization_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oa-test")
    with patch("openai.AsyncOpenAI") as mock_openai:
        client = LLMClient()
        assert client.provider == "openai"
        assert client._openai_client is not None
        assert client._anthropic_client is None
        mock_openai.assert_called_once()


def test_llm_client_anthropic_call(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    
    mock_resp = MagicMock()
    
    mock_block_1 = MagicMock()
    mock_block_1.type = "text"
    mock_block_1.text = "Hello back"
    
    mock_block_2 = MagicMock()
    mock_block_2.type = "tool_use"
    mock_block_2.name = "report_violations"
    mock_block_2.input = {"passes": True}
    
    mock_resp.content = [mock_block_1, mock_block_2]
    mock_resp.usage = MagicMock(
        input_tokens=10,
        output_tokens=20,
        cache_read_input_tokens=5,
        cache_creation_input_tokens=3
    )

    with patch("anthropic.AsyncAnthropic") as mock_class:
        mock_instance = MagicMock()
        mock_instance.messages.create = AsyncMock(return_value=mock_resp)
        mock_class.return_value = mock_instance

        client = LLMClient()
        resp = asyncio.run(client.create_message(
            model="claude-3-5-haiku-latest",
            messages=[{"role": "user", "content": "Hello"}],
            system="System prompt",
            max_tokens=100,
            tools=[{"name": "test_tool", "input_schema": {"type": "object"}}]
        ))

        mock_instance.messages.create.assert_called_once_with(
            model="claude-3-5-haiku-latest",
            max_tokens=100,
            system="System prompt",
            messages=[{"role": "user", "content": "Hello"}],
            tools=[{"name": "test_tool", "input_schema": {"type": "object"}}],
            tool_choice=None
        )

        assert len(resp.content) == 2
        assert resp.content[0].type == "text"
        assert resp.content[0].text == "Hello back"
        assert resp.content[1].type == "tool_use"
        assert resp.content[1].name == "report_violations"
        assert resp.content[1].input == {"passes": True}
        assert resp.usage is not None
        assert resp.usage.input_tokens == 10
        assert resp.usage.output_tokens == 20
        assert resp.usage.cache_read_input_tokens == 5
        assert resp.usage.cache_creation_input_tokens == 3


def test_llm_client_openai_call(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oa-test")

    mock_choice = MagicMock()
    mock_choice.message.content = "Response text"
    
    mock_tool_call = MagicMock()
    mock_tool_call.function.name = "report_violations"
    mock_tool_call.function.arguments = '{"passes": false}'
    
    mock_choice.message.tool_calls = [mock_tool_call]
    
    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    mock_resp.usage = MagicMock(prompt_tokens=15, completion_tokens=25)

    with patch("openai.AsyncOpenAI") as mock_class:
        mock_instance = MagicMock()
        mock_instance.chat.completions.create = AsyncMock(return_value=mock_resp)
        mock_class.return_value = mock_instance

        client = LLMClient()
        resp = asyncio.run(client.create_message(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Hello"}],
            system="System prompt",
            max_tokens=100,
            tools=[{"name": "test_tool", "input_schema": {"type": "object"}}]
        ))

        # Verify that tools schema mapped input_schema to parameters
        expected_tools = [{
            "type": "function",
            "function": {
                "name": "test_tool",
                "description": "",
                "parameters": {"type": "object"}
            }
        }]

        mock_instance.chat.completions.create.assert_called_once_with(
            model="gpt-4o-mini",
            max_tokens=100,
            messages=[
                {"role": "system", "content": "System prompt"},
                {"role": "user", "content": "Hello"}
            ],
            tools=expected_tools
        )

        assert len(resp.content) == 2
        assert resp.content[0].type == "text"
        assert resp.content[0].text == "Response text"
        assert resp.content[1].type == "tool_use"
        assert resp.content[1].name == "report_violations"
        assert resp.content[1].input == {"passes": False}
        assert resp.usage is not None
        assert resp.usage.input_tokens == 15
        assert resp.usage.output_tokens == 25
