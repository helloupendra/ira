"""Import the tool modules named in ``ira.yaml``.

An entry is either a dotted module name (``myshop.tools``) or a path to a
``.py`` file, relative to the config file. Importing the module registers its
tools through the ``@tool`` and ``@action`` decorators. A module may also
define two optional hooks:

* ``setup(ctx)`` - called once after import, e.g. to remember ``ctx.data_dir``;
* ``seed(ctx)``  - called by ``ira demo seed`` to create demo data.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from ira.tools.registry import ToolContext


def _module_name(path: Path) -> str:
    digest = hashlib.sha1(str(path).encode(), usedforsecurity=False).hexdigest()[:8]
    return f"ira_tools_{path.stem}_{digest}"


def import_tool_module(spec: str, base_dir: Path) -> ModuleType:
    if spec.endswith(".py") or "/" in spec or "\\" in spec:
        path = Path(spec)
        if not path.is_absolute():
            path = base_dir / path
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(f"tool module not found: {path}")
        name = _module_name(path)
        if name in sys.modules:  # already loaded; importing again would re-register
            return sys.modules[name]
        module_spec = importlib.util.spec_from_file_location(name, path)
        if module_spec is None or module_spec.loader is None:
            raise ImportError(f"cannot import {path}")
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[name] = module
        try:
            module_spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(name, None)
            raise
        return module
    return importlib.import_module(spec)


def load_tool_modules(specs: list[str], ctx: ToolContext) -> list[ModuleType]:
    modules = [import_tool_module(spec, ctx.config_dir) for spec in specs]
    for module in modules:
        hook = getattr(module, "setup", None)
        if callable(hook):
            hook(ctx)
    return modules


def run_seed(modules: list[ModuleType], ctx: ToolContext) -> list[tuple[str, Any]]:
    """Call every module's ``seed(ctx)``; returns (module, result) pairs."""
    results = []
    for module in modules:
        hook = getattr(module, "seed", None)
        if callable(hook):
            results.append((module.__name__, hook(ctx)))
    return results
