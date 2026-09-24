from __future__ import annotations

from pathlib import Path
from typing import Any

from ..schemas.problem_spec import ProblemSpec
from ..utils.yaml_io import load_yaml_file
from .package_registry import PackageFile, PackageRegistry


class ProblemSpecRegistry:
    def __init__(self, root_dir: str | Path | None = None, *, packages: PackageRegistry | None = None):
        self.root_dir = Path(root_dir) if root_dir is not None else None
        self.packages = packages if packages is not None else PackageRegistry()
        self._index: dict[str, tuple[Path, dict[str, Any], str | None, Path | None]] | None = None

    def list_specs(self) -> list[dict[str, str]]:
        indexed = self._index_specs()
        return [
            {"problem_id": problem_id, "summary": str(data.get("description", ""))}
            for problem_id, (_, data, _, _) in indexed.items()
        ]

    def get(self, problem_id: str) -> ProblemSpec:
        path, _, _, _ = self._resolve_entry(problem_id)
        return ProblemSpec.model_validate(load_yaml_file(path))

    def as_dict(self, problem_id: str) -> dict[str, Any]:
        path, data, package_id, package_root = self._resolve_entry(problem_id)
        data = load_yaml_file(path)
        result = ProblemSpec.model_validate(data).model_dump()
        result["_source_path"] = str(path.resolve())
        if package_id is not None:
            result["_package_id"] = package_id
            result["_package_root"] = str(package_root)
        return result

    def _resolve_entry(self, problem_id: str) -> tuple[Path, dict[str, Any], str | None, Path | None]:
        indexed = self._index_specs()
        if problem_id not in indexed:
            raise KeyError(f"Unknown problem_id: {problem_id}")
        return indexed[problem_id]

    def _index_specs(self) -> dict[str, tuple[Path, dict[str, Any], str | None, Path | None]]:
        if self._index is not None:
            return self._index
        indexed: dict[str, tuple[Path, dict[str, Any], str | None, Path | None]] = {}
        for package_file in self._iter_problem_files():
            path = package_file.path
            data = load_yaml_file(path)
            if not isinstance(data, dict):
                continue
            problem_id = str(data.get("problem_id", "")).strip()
            if not problem_id:
                continue
            if problem_id in indexed:
                existing_path = indexed[problem_id][0]
                raise ValueError(f"Duplicate problem_id {problem_id!r} in {existing_path} and {path}.")
            package = package_file.package
            indexed[problem_id] = (
                path,
                data,
                package.package_id if package else None,
                package.root if package else None,
            )
        self._index = indexed
        return indexed

    def _iter_problem_files(self):
        if self.root_dir is None:
            yield from self.packages.problem_files()
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
            raise FileNotFoundError(f"Configured problem spec directory does not exist: {self.root_dir}")
        if not self.root_dir.is_dir():
            raise NotADirectoryError(f"Configured problem spec directory is not a directory: {self.root_dir}")
