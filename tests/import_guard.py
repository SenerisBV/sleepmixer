"""AST-based import detection for regression testing.

Substring checks on source text miss ordinary import spellings. These guards are
the only enforcement two Global Constraints have, so they must not be bypassable
by spelling variations like ``from numpy import array`` instead of
``import numpy``.

This module resolves every import in a Python file to a fully-qualified dotted
module name, using the importing file's own package location, then matches
against forbidden names by dotted-prefix (so forbidding ``"numpy"`` catches
``"numpy.fft"`` and forbidding ``"sleepmix.audio"`` catches everything under it).
"""
import ast
from pathlib import Path


def resolved_imports(path: Path, repo_root: Path) -> set[str]:
    """Resolve all imports in a file to fully-qualified dotted module names.

    The returned set contains module names as they would appear in absolute
    import statements, accounting for the file's own package location when
    resolving relative imports.

    Args:
        path: Path to the Python file to analyze (must be absolute)
        repo_root: Root of the repository containing the file

    Returns:
        Set of fully-qualified module names that the file imports
    """
    with open(path) as f:
        tree = ast.parse(f.read(), filename=str(path))

    # Derive the file's own package from its path relative to repo_root
    rel_path = path.relative_to(repo_root)
    # Convert path to module name: sleepmix/night/plan.py -> sleepmix.night.plan
    # Then take parent to get package: sleepmix.night
    module_path = rel_path.with_suffix('').as_posix().replace('/', '.')
    if module_path.endswith('.__init__'):
        own_package = module_path[:-len('.__init__')]
    else:
        own_package = '.'.join(module_path.split('.')[:-1])

    imports = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            # ``import numpy`` or ``import sleepmix.audio as a``
            for alias in node.names:
                # Take the full module name
                imports.add(alias.name)

        elif isinstance(node, ast.ImportFrom):
            # ``from X import Y`` or relative ``from . import Z``
            if node.level == 0:
                # Absolute import: from sleepmix import audio
                if node.module:
                    imports.add(node.module)
                    # Also add module.name for each imported name
                    # (could be submodule: from sleepmix import audio)
                    for alias in node.names:
                        imports.add(f"{node.module}.{alias.name}")
            else:
                # Relative import: from ..audio import X or from . import Y
                # Walk up level-1 components from own_package
                parts = own_package.split('.')
                # level=1 means from current package (parts[-1:])
                # level=2 means from parent package (parts[:-1])
                base_parts = parts[:-(node.level - 1)] if node.level > 1 else parts
                base_package = '.'.join(base_parts) if base_parts else ''

                if node.module:
                    # from ..audio import X -> base_package.audio
                    if base_package:
                        full_module = f"{base_package}.{node.module}"
                    else:
                        full_module = node.module
                    imports.add(full_module)
                    # Also add the specific names being imported
                    for alias in node.names:
                        imports.add(f"{full_module}.{alias.name}")
                else:
                    # from . import Y -> base_package.Y
                    if base_package:
                        for alias in node.names:
                            imports.add(f"{base_package}.{alias.name}")

    return imports


def forbidden_imports(path: Path, repo_root: Path,
                      forbidden: set[str]) -> set[str]:
    """Find imports that match any forbidden module name.

    An import is forbidden if it equals or is a dotted-prefix descendant of
    any entry in the forbidden set. For example:
    - Forbidding "numpy" catches "numpy", "numpy.fft", "numpy.random.Generator"
    - Forbidding "sleepmix.audio" catches "sleepmix.audio", "sleepmix.audio.engine"
    - Forbidding "sleepmix" would catch "sleepmix.audio" but not "sleepmixer"

    Args:
        path: Path to the Python file to analyze
        repo_root: Root of the repository
        forbidden: Set of module names that are not allowed

    Returns:
        Set of resolved imports that violate the forbidden list (empty if none)
    """
    resolved = resolved_imports(path, repo_root)
    violations = set()

    for imp in resolved:
        for f in forbidden:
            # Match by equality or by dotted-prefix descendant
            if imp == f or imp.startswith(f + "."):
                violations.add(imp)
                break

    return violations
