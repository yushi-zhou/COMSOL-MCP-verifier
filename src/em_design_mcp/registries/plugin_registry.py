from __future__ import annotations

import importlib.util
import inspect
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from .package_registry import PackageRegistry, PluginSpec


@dataclass(frozen=True)
class LoadedPlugin:
    plugin_id: str
    kind: str
    package_id: str
    path: Path
    function: Callable[..., Any]
    metadata: dict[str, Any]


class PluginRegistry:
    """Load package-owned Python callables without adding packages to sys.path."""

    def __init__(self, packages: PackageRegistry | None = None) -> None:
        self.packages = packages if packages is not None else PackageRegistry()

    def list(self, kind: str) -> list[dict[str, Any]]:
        return [
            {
                "plugin_id": spec.plugin_id,
                "kind": spec.kind,
                "package_id": spec.package.package_id,
                **spec.metadata,
            }
            for spec in self.packages.plugin_specs(kind)
        ]

    def get(self, kind: str, plugin_id: str) -> LoadedPlugin:
        matches = [
            spec
            for spec in self.packages.plugin_specs(kind)
            if spec.plugin_id == plugin_id
        ]
        if not matches:
            label = kind[:-1] if kind.endswith("s") else kind
            raise KeyError(f"Unknown {label}_id: {plugin_id}")
        if len(matches) > 1:
            sources = ", ".join(str(spec.path) for spec in matches)
            raise ValueError(f"Duplicate {kind} plugin {plugin_id!r}: {sources}")
        return self._load(matches[0])

    @staticmethod
    def call(plugin: LoadedPlugin, *args: Any, **kwargs: Any) -> Any:
        signature = inspect.signature(plugin.function)
        supported = {
            name: value
            for name, value in kwargs.items()
            if name in signature.parameters
        }
        return plugin.function(*args, **supported)

    def _load(self, spec: PluginSpec) -> LoadedPlugin:
        module_name = (
            f"_em_design_plugin_{spec.kind}_{spec.package.package_id}_{spec.plugin_id}"
            .replace("-", "_")
        )
        module = _load_module(module_name, spec.path)
        function = getattr(module, spec.callable_name, None)
        if not callable(function):
            raise ValueError(
                f"Plugin callable {spec.callable_name!r} was not found in {spec.path}"
            )
        return LoadedPlugin(
            plugin_id=spec.plugin_id,
            kind=spec.kind,
            package_id=spec.package.package_id,
            path=spec.path,
            function=function,
            metadata=spec.metadata,
        )


def _load_module(module_name: str, path: Path) -> ModuleType:
    module_spec = importlib.util.spec_from_file_location(module_name, path)
    if module_spec is None or module_spec.loader is None:
        raise ImportError(f"Unable to create module spec for plugin: {path}")
    module = importlib.util.module_from_spec(module_spec)
    # Execute the fingerprinted source, not a timestamp-based .pyc cache.
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return module
