from __future__ import annotations

from pathlib import Path
from typing import Any

from ..schemas.model_profile import ModelProfile
from ..utils.yaml_io import load_yaml_file
from .package_registry import PackageFile, PackageRegistry


class ModelProfileRegistry:
    def __init__(
        self,
        root_dir: str | Path | None = None,
        *,
        packages: PackageRegistry | None = None,
    ):
        self.root_dir = Path(root_dir) if root_dir is not None else None
        self.packages = packages if packages is not None else PackageRegistry()
        self._index: dict[str, tuple[Path, dict[str, Any], str | None, Path | None]] | None = None

    def list_profiles(self) -> list[dict[str, str]]:
        indexed = self._index_profiles()
        return [
            {"model_profile_id": model_profile_id, "description": str(data.get("description", ""))}
            for model_profile_id, (_, data, _, _) in indexed.items()
        ]

    def get(self, model_profile_id: str) -> ModelProfile:
        path, _, _, _ = self._resolve_entry(model_profile_id)
        return ModelProfile.model_validate(load_yaml_file(path))

    def as_dict(self, model_profile_id: str) -> dict[str, Any]:
        path, data, package_id, package_root = self._resolve_entry(model_profile_id)
        data = load_yaml_file(path)
        result = ModelProfile.model_validate(data).model_dump()
        result["_source_path"] = str(path.resolve())
        if package_id is not None:
            result["_package_id"] = package_id
            result["_package_root"] = str(package_root)
        return result

    def _resolve_entry(self, model_profile_id: str) -> tuple[Path, dict[str, Any], str | None, Path | None]:
        indexed = self._index_profiles()
        if model_profile_id not in indexed:
            raise KeyError(f"Unknown model_profile_id: {model_profile_id}")
        return indexed[model_profile_id]

    def _index_profiles(self) -> dict[str, tuple[Path, dict[str, Any], str | None, Path | None]]:
        if self._index is not None:
            return self._index
        indexed: dict[str, tuple[Path, dict[str, Any], str | None, Path | None]] = {}
        for package_file in self._iter_profile_files():
            path = package_file.path
            data = load_yaml_file(path)
            if not isinstance(data, dict):
                continue
            model_profile_id = str(data.get("model_profile_id", "")).strip()
            if not model_profile_id:
                continue
            if model_profile_id in indexed:
                existing_path = indexed[model_profile_id][0]
                raise ValueError(
                    f"Duplicate model_profile_id {model_profile_id!r} in {existing_path} and {path}."
                )
            package = package_file.package
            indexed[model_profile_id] = (
                path,
                data,
                package.package_id if package else None,
                package.root if package else None,
            )
        self._index = indexed
        return indexed

    def _iter_profile_files(self):
        if self.root_dir is None:
            yield from self.packages.profile_files()
            return
        self._ensure_root_dir()
        for path in self._iter_yaml_files():
            yield PackageFile(package=None, path=path)

    def _iter_yaml_files(self):
        assert self.root_dir is not None
        for path in sorted(self.root_dir.rglob("*")):
            if not path.is_file():
                continue
            if any(part.startswith(".") for part in path.relative_to(self.root_dir).parts):
                continue
            if path.name.startswith(".") or path.name.endswith((".disabled.yaml", ".disabled.yml")):
                continue
            if path.suffix.lower() not in {".yaml", ".yml"}:
                continue
            yield path

    def _ensure_root_dir(self) -> None:
        assert self.root_dir is not None
        if not self.root_dir.exists():
            raise FileNotFoundError(f"Configured model profile directory does not exist: {self.root_dir}")
        if not self.root_dir.is_dir():
            raise NotADirectoryError(f"Configured model profile directory is not a directory: {self.root_dir}")
