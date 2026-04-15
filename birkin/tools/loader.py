"""Tool loader -- dynamic discovery and loading of Tool implementations."""

from __future__ import annotations

import importlib
import inspect
import logging
from pathlib import Path
from typing import Optional

from birkin.tools.base import Tool
from birkin.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class ToolLoader:
    """Loads Tool implementations from directories and modules."""

    @staticmethod
    def load_from_directory(
        path: Path,
        registry: Optional[ToolRegistry] = None,
    ) -> list[str]:
        """Load all Tool subclasses from Python files in a directory.

        Args:
            path: Directory to scan for tool modules.
            registry: Registry to register tools in (optional).

        Returns:
            List of tool names that were loaded.
        """
        if registry is None:
            from birkin.tools.registry import get_registry

            registry = get_registry()

        path = Path(path)
        if not path.is_dir():
            logger.warning(f"Tool directory not found: {path}")
            return []

        loaded_names = []
        for py_file in path.glob("*.py"):
            if py_file.name.startswith("_"):
                continue

            try:
                module_name = f"birkin.tools.{py_file.stem}"
                spec = importlib.util.spec_from_file_location(
                    module_name,
                    py_file,
                )
                if not spec or not spec.loader:
                    continue

                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # Find Tool subclasses in the module
                for name, obj in inspect.getmembers(module):
                    if inspect.isclass(obj) and issubclass(obj, Tool) and obj is not Tool:
                        try:
                            tool_instance = obj()
                            registry.register(tool_instance)
                            loaded_names.append(tool_instance.spec.name)
                            logger.info(f"Loaded tool: {tool_instance.spec.name}")
                        except Exception as e:
                            logger.error(f"Failed to instantiate {name} from {py_file}: {e}")
            except Exception as e:
                logger.error(f"Failed to load module {py_file}: {e}")

        return loaded_names

    @staticmethod
    def load_from_module(
        module_path: str,
        registry: Optional[ToolRegistry] = None,
    ) -> list[str]:
        """Load Tool subclasses from a module by dotted path.

        Args:
            module_path: Dotted module path (e.g., 'my_tools.search_tool').
            registry: Registry to register tools in (optional).

        Returns:
            List of tool names that were loaded.
        """
        if registry is None:
            from birkin.tools.registry import get_registry

            registry = get_registry()

        loaded_names = []

        try:
            module = importlib.import_module(module_path)

            for name, obj in inspect.getmembers(module):
                if inspect.isclass(obj) and issubclass(obj, Tool) and obj is not Tool:
                    try:
                        tool_instance = obj()
                        registry.register(tool_instance)
                        loaded_names.append(tool_instance.spec.name)
                        logger.info(f"Loaded tool: {tool_instance.spec.name}")
                    except Exception as e:
                        logger.error(f"Failed to instantiate {name} from {module_path}: {e}")
        except ImportError as e:
            logger.error(f"Failed to import module {module_path}: {e}")

        return loaded_names


def load_tools() -> list[Tool]:
    """Discover and instantiate all available tools.

    Currently returns empty list; will be expanded to load from
    configured directories and entry points.
    """
    from birkin.tools.registry import get_registry

    return get_registry().list_all()
