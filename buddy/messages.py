"""Scrollback plug-in surface (skeleton).

The chat scrollback (not built yet) will hold a list of `Message` objects.
Each kind renders through a function registered here. Adding a new message
type (user, claude, tool_call, buddy_aside, system, ...) is a one-liner:

    @register("tool_call")
    def _draw_tool_call(stdscr, rect, msg, ctx):
        ...
        return lines_used

No scrollback or renderer changes needed to add a kind. This module exists
now so the chat PR lands additively.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict


@dataclass
class Message:
    kind: str
    text: str
    ts: float = field(default_factory=time.time)
    meta: dict = field(default_factory=dict)


# A renderer draws `msg` inside `rect` and returns the number of rows it used.
# `ctx` is the same per-tick Ctx passed to region renderers (gives access to
# attr, mood, etc. without re-reading state).
MessageRenderer = Callable[["object", "object", Message, "object"], int]

REGISTRY: Dict[str, MessageRenderer] = {}


def register(kind: str):
    def deco(fn: MessageRenderer) -> MessageRenderer:
        REGISTRY[kind] = fn
        return fn
    return deco


def render_for(kind: str) -> MessageRenderer | None:
    return REGISTRY.get(kind)
