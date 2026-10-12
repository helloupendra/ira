"""Ira: a self-hosted voice assistant over your own data and tools.

Register read tools and action tools with the decorators below; Ira answers by
text and voice, and an action only runs after the owner confirms it with a PIN.
"""

from ira.tools import ToolContext, ToolError, ToolRegistry, action, default_registry, tool

__version__ = "0.2.0"

__all__ = [
    "ToolContext",
    "ToolError",
    "ToolRegistry",
    "__version__",
    "action",
    "default_registry",
    "tool",
]
