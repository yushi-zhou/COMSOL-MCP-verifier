from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .package_registry import PackageRegistry
from .plugin_registry import PluginRegistry


@dataclass(frozen=True)
class VerifierEntry:
    verifier_id: str
    description: str
    required_outputs: list[str]
    verify: Callable[[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any]]
    version: str = "0.1"
    precheck_constraints: list[dict[str, Any]] | None = None


class VerifierRegistry:
    def __init__(
        self,
        packages: PackageRegistry | None = None,
        *,
        plugins: PluginRegistry | None = None,
    ) -> None:
        self.packages = packages if packages is not None else PackageRegistry()
        self.plugins = plugins if plugins is not None else PluginRegistry(self.packages)

    def list_verifiers(self) -> list[dict[str, Any]]:
        return [
            {
                "verifier_id": item["plugin_id"],
                "version": str(item.get("version") or "0.1"),
                "description": str(item.get("description") or ""),
                "required_outputs": list(item.get("required_outputs") or []),
                "package_id": item["package_id"],
            }
            for item in self.plugins.list("verifiers")
        ]

    def get(self, verifier_id: str) -> VerifierEntry:
        plugin = self.plugins.get("verifiers", verifier_id)
        metadata = plugin.metadata
        return VerifierEntry(
            verifier_id=verifier_id,
            description=str(metadata.get("description") or ""),
            required_outputs=[str(value) for value in metadata.get("required_outputs") or []],
            verify=plugin.function,
            version=str(metadata.get("version") or "0.1"),
            precheck_constraints=(
                list(metadata["precheck_constraints"])
                if isinstance(metadata.get("precheck_constraints"), list)
                else None
            ),
        )
