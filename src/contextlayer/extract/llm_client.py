"""Unified LLM Client abstraction supporting Anthropic, OpenAI, and Google Gemini."""
from __future__ import annotations

import os
import logging
from typing import Any
import anthropic
import openai
from contextlayer.models import get_provider

log = logging.getLogger(__name__)

def _map_anthropic_to_openai_tool(anthropic_tool: dict[str, Any]) -> dict[str, Any]:
    """Map Anthropic tool format to OpenAI/Gemini tool format."""
    return {
        "type": "function",
        "function": {
            "name": anthropic_tool["name"],
            "description": anthropic_tool.get("description", ""),
            "parameters": anthropic_tool.get("input_schema", {}),
        }
    }

def _map_anthropic_to_openai_tool_choice(tool_choice: dict[str, Any] | str | None) -> dict[str, Any] | str | None:
    """Map Anthropic tool choice format to OpenAI/Gemini format."""
    if isinstance(tool_choice, dict):
        if tool_choice.get("type") == "tool" or tool_choice.get("type") == "function":
            name = tool_choice.get("name")
            if name:
                return {
                    "type": "function",
                    "function": {"name": name}
                }
    return tool_choice

class LLMClient:
    """Unified client that routes messages to Anthropic, OpenAI, or Google Gemini."""

    def __init__(self) -> None:
        self.provider = get_provider()
        self._anthropic_client: anthropic.AsyncAnthropic | None = None
        self._openai_client: openai.AsyncOpenAI | None = None

        if self.provider == "anthropic":
            self._anthropic_client = anthropic.AsyncAnthropic()
        elif self.provider == "gemini":
            gemini_key = os.environ.get("GEMINI_API_KEY")
            self._openai_client = openai.AsyncOpenAI(
                api_key=gemini_key,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
            )
        elif self.provider == "openai":
            self._openai_client = openai.AsyncOpenAI()

    async def create_message(
        self,
        model: str,
        messages: list[dict[str, Any]],
        system: list[dict[str, Any]] | str | None = None,
        max_tokens: int = 1000,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | str | None = None,
        thinking_budget: int | None = None,
    ) -> LLMResponse:
        """Send message request to active provider and return normalized response."""
        
        # 1. Route to Anthropic if active
        if self._anthropic_client is not None:
            extra_params = {}
            if thinking_budget is not None and "opus" in model.lower():
                extra_params["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
            
            # Map system prompts to Anthropic expected list-of-blocks or string
            formatted_system = system
            
            resp = await self._anthropic_client.messages.create(
                model=model,
                max_tokens=max_tokens + (thinking_budget or 0),
                system=formatted_system,
                messages=messages,
                tools=tools or [],
                tool_choice=tool_choice,
                **extra_params
            )
            return AnthropicResponse(resp)

        # 2. Route to OpenAI / Gemini (via OpenAI compatibility)
        elif self._openai_client is not None:
            # Map system prompt into messages list
            api_messages = []
            if system:
                if isinstance(system, list):
                    system_text = "\n".join(
                        block.get("text", "") if isinstance(block, dict) else str(block)
                        for block in system
                    )
                else:
                    system_text = str(system)
                api_messages.append({"role": "system", "content": system_text})
            
            # Clean up message formats (strip Anthropic specific cache controls)
            for msg in messages:
                content = msg.get("content", "")
                if isinstance(content, list):
                    content_text = ""
                    for block in content:
                        if isinstance(block, dict):
                            content_text += block.get("text", "")
                        else:
                            content_text += str(block)
                    api_messages.append({"role": msg["role"], "content": content_text})
                else:
                    api_messages.append(msg)

            # Map tools
            api_tools = None
            if tools:
                api_tools = [_map_anthropic_to_openai_tool(t) for t in tools]

            # Map tool choice
            api_tool_choice = _map_anthropic_to_openai_tool_choice(tool_choice)

            # Build params
            params: dict[str, Any] = {
                "model": model,
                "messages": api_messages,
                "max_tokens": max_tokens,
            }
            if api_tools:
                params["tools"] = api_tools
            if api_tool_choice:
                params["tool_choice"] = api_tool_choice

            # Handle reasoning/thinking models (e.g. o3-mini)
            if "o3-mini" in model.lower() or "o1" in model.lower():
                # OpenAI's o3-mini uses reasoning_effort instead of thinking_budget,
                # and max_completion_tokens instead of max_tokens
                params["max_completion_tokens"] = max_tokens + (thinking_budget or 0)
                params.pop("max_tokens", None)
                if thinking_budget:
                    params["reasoning_effort"] = "medium"

            resp = await self._openai_client.chat.completions.create(**params)
            return OpenAIResponse(resp)

        raise RuntimeError("No LLM client is initialized.")


class LLMResponse:
    """Interface to normalize responses across providers."""
    @property
    def content(self) -> list[LLMBlock]:
        raise NotImplementedError

    @property
    def usage(self) -> LLMUsage | None:
        raise NotImplementedError


class LLMBlock:
    """Normalized response block (text or tool call)."""
    @property
    def type(self) -> str:  # "text" | "tool_use"
        raise NotImplementedError

    @property
    def text(self) -> str | None:
        raise NotImplementedError

    @property
    def name(self) -> str | None:  # For tool_use
        raise NotImplementedError

    @property
    def input(self) -> dict[str, Any] | None:  # For tool_use
        raise NotImplementedError


class LLMUsage:
    """Normalized token usage numbers."""
    def __init__(self, input_tokens=0, output_tokens=0, cache_read=0, cache_write=0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = cache_read
        self.cache_creation_input_tokens = cache_write


# --- Anthropic Adapter Implementations ---

class AnthropicBlock(LLMBlock):
    def __init__(self, block: Any):
        self._block = block

    @property
    def type(self) -> str:
        return self._block.type

    @property
    def text(self) -> str | None:
        return getattr(self._block, "text", None)

    @property
    def name(self) -> str | None:
        return getattr(self._block, "name", None)

    @property
    def input(self) -> dict[str, Any] | None:
        return getattr(self._block, "input", None)


class AnthropicResponse(LLMResponse):
    def __init__(self, resp: Any):
        self._resp = resp

    @property
    def content(self) -> list[LLMBlock]:
        return [AnthropicBlock(b) for b in self._resp.content]

    @property
    def usage(self) -> LLMUsage | None:
        u = getattr(self._resp, "usage", None)
        if u is None:
            return None
        return LLMUsage(
            input_tokens=getattr(u, "input_tokens", 0) or 0,
            output_tokens=getattr(u, "output_tokens", 0) or 0,
            cache_read=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_write=getattr(u, "cache_creation_input_tokens", 0) or 0,
        )


# --- OpenAI Adapter Implementations ---

class OpenAIBlock(LLMBlock):
    def __init__(self, message_or_tool_call: Any, is_tool: bool = False):
        self._item = message_or_tool_call
        self._is_tool = is_tool

    @property
    def type(self) -> str:
        return "tool_use" if self._is_tool else "text"

    @property
    def text(self) -> str | None:
        if self._is_tool:
            return None
        return getattr(self._item, "content", None)

    @property
    def name(self) -> str | None:
        if not self._is_tool:
            return None
        return getattr(self._item.function, "name", None)

    @property
    def input(self) -> dict[str, Any] | None:
        if not self._is_tool:
            return None
        args_str = getattr(self._item.function, "arguments", "{}")
        import json
        try:
            return json.loads(args_str)
        except Exception:
            return {}


class OpenAIResponse(LLMResponse):
    def __init__(self, resp: Any):
        self._resp = resp

    @property
    def content(self) -> list[LLMBlock]:
        choice = self._resp.choices[0]
        msg = choice.message
        blocks = []
        
        # If there is regular text content
        if msg.content:
            blocks.append(OpenAIBlock(msg, is_tool=False))
            
        # If there are tool calls
        if getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                blocks.append(OpenAIBlock(tc, is_tool=True))
                
        return blocks

    @property
    def usage(self) -> LLMUsage | None:
        u = getattr(self._resp, "usage", None)
        if u is None:
            return None
        return LLMUsage(
            input_tokens=getattr(u, "prompt_tokens", 0) or 0,
            output_tokens=getattr(u, "completion_tokens", 0) or 0,
            cache_read=0,
            cache_write=0,
        )
