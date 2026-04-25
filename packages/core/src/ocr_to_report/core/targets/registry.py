"""Target registry — loads target bundles from a base directory."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ocr_to_report.core.errors.domain import TargetNotFoundError
from ocr_to_report.core.targets.loader import TargetLoadError, load_target_bundle

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ocr_to_report.core.target.bundle import TargetBundle


class TargetRegistry:
    """In-memory registry of target bundles. Lazy-loaded.

    Mirrors :class:`ProfileRegistry` exactly. See its docstring for the
    semantic model.
    """

    def __init__(self, root: Path) -> None:
        if not root.is_dir():
            raise TargetLoadError(
                f"target root directory not found: {root}",
                root=str(root),
            )
        self._root = root
        self._cache: dict[str, TargetBundle] = {}
        self._discovered: dict[str, Path] = {}
        self._discover()

    @property
    def root(self) -> Path:
        return self._root

    def _discover(self) -> None:
        for child in sorted(self._root.iterdir()):
            if not child.is_dir() or not (child / "manifest.yaml").is_file():
                continue
            self._discovered[child.name] = child

    def ids(self) -> list[str]:
        return sorted(self._discovered.keys())

    def has(self, target_id: str) -> bool:
        return target_id in self._discovered

    def get(self, target_id: str) -> TargetBundle:
        if target_id in self._cache:
            return self._cache[target_id]
        try:
            bundle_dir = self._discovered[target_id]
        except KeyError as e:
            raise TargetNotFoundError(
                f"no target bundle with id={target_id!r} under {self._root}",
                target_id=target_id,
            ) from e
        bundle = load_target_bundle(bundle_dir)
        if bundle.id != target_id:
            raise TargetLoadError(
                f"directory name {target_id!r} does not match manifest id {bundle.id!r}",
                directory=target_id,
                manifest_id=bundle.id,
            )
        self._cache[target_id] = bundle
        return bundle

    def all(self) -> Iterable[TargetBundle]:
        for tid in self.ids():
            yield self.get(tid)


__all__ = ["TargetRegistry"]
