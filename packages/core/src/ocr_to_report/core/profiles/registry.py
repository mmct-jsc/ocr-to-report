"""Profile registry — loads all profile bundles from a base directory.

Lazy by default: bundles are scanned at construction time but YAML is only
read when a bundle is first requested. Once loaded, bundles are cached
indefinitely; constructing a fresh registry re-reads the disk.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ocr_to_report.core.errors.domain import ProfileNotFoundError
from ocr_to_report.core.profiles.loader import (
    ProfileLoadError,
    load_profile_bundle,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ocr_to_report.core.profile.bundle import ProfileBundle


class ProfileRegistry:
    """In-memory registry of profile bundles.

    A registry is bound to a single root directory containing one
    subdirectory per profile bundle. Loading is lazy — a bundle is read
    only when first requested via :meth:`get`.

    Construction does NOT raise on missing/invalid bundles: invalid
    bundles surface only when their id is requested. This lets the API
    start up even if one tenant's custom bundle is broken; the broken
    one just fails at request time with a clear error.
    """

    def __init__(self, root: Path) -> None:
        if not root.is_dir():
            raise ProfileLoadError(
                f"profile root directory not found: {root}",
                root=str(root),
            )
        self._root = root
        self._cache: dict[str, ProfileBundle] = {}
        self._discovered: dict[str, Path] = {}
        self._discover()

    @property
    def root(self) -> Path:
        return self._root

    def _discover(self) -> None:
        """Build id → bundle_dir map from manifest files (cheap scan)."""
        # We trust the directory name to match the bundle id. Loaders
        # validate the manifest's id matches when first opened.
        for child in sorted(self._root.iterdir()):
            if not child.is_dir():
                continue
            if not (child / "manifest.yaml").is_file():
                # Skip non-bundle directories (READMEs, etc.) silently.
                continue
            self._discovered[child.name] = child

    def ids(self) -> list[str]:
        """Return all discovered bundle ids (sorted)."""
        return sorted(self._discovered.keys())

    def has(self, profile_id: str) -> bool:
        return profile_id in self._discovered

    def get(self, profile_id: str) -> ProfileBundle:
        """Return a (cached) bundle by id.

        Raises :class:`ProfileNotFoundError` if the id is unknown,
        :class:`ProfileLoadError` if loading or validation fails.
        """
        if profile_id in self._cache:
            return self._cache[profile_id]
        try:
            bundle_dir = self._discovered[profile_id]
        except KeyError as e:
            raise ProfileNotFoundError(
                f"no profile bundle with id={profile_id!r} under {self._root}",
                profile_id=profile_id,
            ) from e
        bundle = load_profile_bundle(bundle_dir)
        if bundle.id != profile_id:
            raise ProfileLoadError(
                f"directory name {profile_id!r} does not match manifest id {bundle.id!r}",
                directory=profile_id,
                manifest_id=bundle.id,
            )
        self._cache[profile_id] = bundle
        return bundle

    def all(self) -> Iterable[ProfileBundle]:
        """Iterate all bundles, loading any that haven't been touched yet."""
        for pid in self.ids():
            yield self.get(pid)


__all__ = ["ProfileRegistry"]
