"""Anthropic model IDs used in the 3-stage extraction pipeline.

Defaults verified working on 2026-05-18; override via env if needed.
"""
from __future__ import annotations

import os

HAIKU_MODEL = os.environ.get("CONTEXTLAYER_HAIKU_MODEL", "claude-haiku-4-5")
SONNET_MODEL = os.environ.get("CONTEXTLAYER_SONNET_MODEL", "claude-sonnet-4-5")
OPUS_MODEL = os.environ.get("CONTEXTLAYER_OPUS_MODEL", "claude-opus-4-1")
