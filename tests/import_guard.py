"""AST-based import detection for regression testing.

Substring checks on source text miss ordinary import spellings. These guards are
the only enforcement two Global Constraints have, so they must not be bypassable
by spelling variations like ``from numpy import array`` instead of
``import numpy``.
"""
import ast
from typing import NamedTuple


class ImportInfo(NamedTuple):
    """One import found in a module."""
    module: str | None
    names: list[str]
    is_relative: bool


def imports_from_file(path: str) -> list[ImportInfo]:
    """Parse a Python file and return all imports it contains.

    Walks the AST for ``ast.Import`` and ``ast.ImportFrom`` nodes. For each:
    - ``ast.Import``: records the top-level module name (before the dot)
    - ``ast.ImportFrom``: records the module name and any imported names

    Handles relative imports correctly: when ``node.level > 0``, the import is
    relative to the current package.
    """
    with open(path) as f:
        tree = ast.parse(f.read(), filename=path)

    imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            # ``import numpy`` or ``import scipy.signal``
            for alias in node.names:
                # Take the top-level module name (before first dot)
                top_level = alias.name.split(".")[0]
                imports.append(ImportInfo(
                    module=top_level,
                    names=[],
                    is_relative=False
                ))
        elif isinstance(node, ast.ImportFrom):
            # ``from numpy import array`` or ``from .night import Voice``
            # node.module is None for bare ``from . import x``
            # node.level > 0 means it's a relative import
            names = [alias.name for alias in node.names]

            # For relative imports, node.module might be None
            module = node.module
            imports.append(ImportInfo(
                module=module,
                names=names,
                is_relative=node.level > 0
            ))

    return imports


def imports_any(path: str, forbidden_modules: set[str],
                forbidden_from_modules: set[str] | None = None) -> bool:
    """Check if a file imports any of the forbidden modules.

    Args:
        path: Path to the Python file to check
        forbidden_modules: Set of module names that are forbidden (e.g., {"numpy", "scipy"})
        forbidden_from_modules: Set of module paths forbidden in ``from X import ...`` (e.g., {"sleepmix.audio"})

    Returns:
        True if the file imports any forbidden module, False otherwise
    """
    if forbidden_from_modules is None:
        forbidden_from_modules = set()

    imports = imports_from_file(path)

    for imp in imports:
        # Check top-level module names (``import numpy`` catches "numpy")
        if imp.module and imp.module.split(".")[0] in forbidden_modules:
            return True

        # Check full module paths for ``from X import ...`` statements
        if imp.module and imp.module in forbidden_from_modules:
            return True

    return False
