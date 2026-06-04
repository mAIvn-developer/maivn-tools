"""Local filesystem connector.

All tools are sandboxed to a configurable ``root`` directory. Any path
argument is normalized and re-checked to ensure it does not escape the root
via symlinks or ``..`` traversal.

Read tools cover directory listing, text/binary reads, recursive walking,
substring search, and stat. Write tools cover text/binary writes, append,
mkdir, copy, and move. Destructive tools (delete file, remove directory)
are tagged so hosts can filter them out with ``exclude_tags=["destructive"]``.
"""

# pyright: strict

from __future__ import annotations

import base64
import fnmatch
import os
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from maivn import toolify, toolset

from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet


class PathOutsideRootError(ValueError):
    """Raised when a requested path resolves outside the connector root."""


@dataclass(frozen=True)
class _FileEntry:
    path: str
    is_dir: bool
    size: int | None
    mime_hint: str | None
    modified_at: str | None


def _extract_local_path(candidate: Any) -> str:
    """Pull a local path string out of a raw string or a list_directory dict.

    Accepts a raw path, a summary dict (``{"path": ..., ...}``), or a
    list of such (first valid wins).
    """
    if isinstance(candidate, str):
        return candidate
    if isinstance(candidate, dict):
        mapping = cast("dict[object, object]", candidate)
        for key in ("path", "file_path", "destination", "source"):
            value = mapping.get(key)
            if isinstance(value, str):
                return value
        raise ValueError("dict candidate has no path")
    if isinstance(candidate, (list, tuple)):
        sequence = cast("tuple[object, ...] | list[object]", candidate)
        for item in sequence:
            try:
                return _extract_local_path(item)
            except ValueError:
                continue
        raise ValueError("no usable path in candidate sequence")
    raise ValueError("path must be a string or a file dict")


@toolset(prefix="local_files")
class LocalFilesToolSet:
    """A connector that exposes read/write tools over a sandboxed local directory.

    Args:
        root: Directory the connector is allowed to read from. Every tool
            call is sandboxed to this directory.
        follow_symlinks: When False (the default) symlinks that resolve
            outside ``root`` are rejected.
        max_read_bytes: Upper bound on the number of bytes ``read_text_file``
            will return. Files exceeding this size return their first
            ``max_read_bytes`` and a truncation marker in the metadata.
    """

    metadata = ProviderMetadata(
        name="local_files",
        display_name="Local Filesystem",
        version="0.1.0",
        description="Read and write a sandboxed local directory tree.",
        auth_modes=(AuthMode.NONE,),
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
            }
        ),
        tags=("files", "local"),
    )

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        follow_symlinks: bool = False,
        max_read_bytes: int = 1_000_000,
        max_write_bytes: int = 10_000_000,
    ) -> None:
        resolved = Path(root).expanduser().resolve(strict=True)
        if not resolved.is_dir():
            raise NotADirectoryError(f"root must be a directory: {resolved}")
        if max_read_bytes < 1:
            raise ValueError("max_read_bytes must be at least 1")
        if max_write_bytes < 1:
            raise ValueError("max_write_bytes must be at least 1")
        self._root = resolved
        self._follow_symlinks = follow_symlinks
        self._max_read_bytes = max_read_bytes
        self._max_write_bytes = max_write_bytes
        self.connection = None

    @property
    def root(self) -> Path:
        """Return the resolved sandbox root."""
        return self._root

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_directory(
        self,
        path: Any = "",
        pattern: str | None = None,
        *,
        max_results: int = 25,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> list[dict[str, Any]]:
        """List the entries under ``path``, optionally filtered by ``pattern``.

        Best first tool for browsing a local folder. Accepts a raw path or
        a dict from a previous ``list_directory`` call. Returns compact
        summaries: ``file_ref`` / ``folder_ref``, ``name``, ``kind``,
        ``size``, ``modified_at``, ``mime_hint``. The relative ``path`` is
        also included since local paths are how follow-up tools
        (``read_text_file``, ``delete_file``) address files. Set
        ``include_metadata=False`` for the legacy raw shape. ``include_ids``
        is accepted for symmetry but has no effect — local files have no
        opaque IDs.
        """
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        path = _extract_local_path(path) if not isinstance(path, str) else path
        target = self._safe_path(path)
        if not target.is_dir():
            raise NotADirectoryError(f"Not a directory: {self._relative_str(target)}")
        entries: list[_FileEntry] = []
        for child in sorted(target.iterdir()):
            if pattern and not fnmatch.fnmatch(child.name, pattern):
                continue
            entries.append(self._describe(child))
            if len(entries) >= max_results:
                break
        if not include_metadata:
            return [
                {
                    "path": entry.path,
                    "is_dir": entry.is_dir,
                    "size": entry.size,
                    "mime_hint": entry.mime_hint,
                }
                for entry in entries
            ]
        # include_ids has no provider-side meaning here (local paths are
        # already the identifier); preserved for API symmetry with the
        # cloud connectors.
        _ = include_ids
        summaries: list[dict[str, Any]] = []
        for index, entry in enumerate(entries, start=1):
            ref_prefix = "folder" if entry.is_dir else "file"
            summary: dict[str, Any] = {
                f"{ref_prefix}_ref": f"{ref_prefix}_{index}",
                "name": Path(entry.path).name,
                "path": entry.path,
                "kind": "folder" if entry.is_dir else "file",
                "size": entry.size,
                "modified_at": entry.modified_at,
                "mime_hint": entry.mime_hint,
            }
            summaries.append(summary)
        return summaries

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def read_text_file(self, path: Any, encoding: str = "utf-8") -> dict[str, Any]:
        """Read ``path`` as text and return its content plus metadata.

        Accepts a relative path string or a file dict from
        ``list_directory``. Returns ``{"path": ..., "encoding": ...,
        "content": ..., "truncated": ..., "size": ...}``. If the file is
        larger than the configured ``max_read_bytes`` the content is
        truncated and ``truncated`` is True.
        """
        target = self._safe_path(_extract_local_path(path))
        if not target.is_file():
            raise FileNotFoundError(self._relative_str(target))
        raw = target.read_bytes()
        truncated = False
        if len(raw) > self._max_read_bytes:
            raw = raw[: self._max_read_bytes]
            truncated = True
        return {
            "path": self._relative_str(target),
            "encoding": encoding,
            "content": raw.decode(encoding, errors="replace"),
            "truncated": truncated,
            "size": target.stat().st_size,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def search_text(
        self,
        query: str,
        *,
        path: Any = "",
        pattern: str = "*",
        max_results: int = 25,
    ) -> list[dict[str, Any]]:
        """Substring-search ``query`` across files matching ``pattern``.

        Best first tool for finding which file contains a string. Returns
        a list of compact match summaries: ``match_ref``, ``path``,
        ``line``, ``snippet``. Defaults to 25 results — increase
        ``max_results`` cautiously for noisy patterns.
        """
        if not query:
            raise ValueError("query must be a non-empty string")
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        path = _extract_local_path(path) if not isinstance(path, str) else path
        target = self._safe_path(path)
        if not target.is_dir():
            raise NotADirectoryError(f"Not a directory: {self._relative_str(target)}")
        results: list[dict[str, Any]] = []
        needle = query.encode("utf-8")
        for file_path in self._walk_files(target, pattern):
            try:
                contents = file_path.read_bytes()
            except OSError:
                continue
            idx = contents.find(needle)
            if idx == -1:
                continue
            line_no = contents[:idx].count(b"\n") + 1
            line_start = contents.rfind(b"\n", 0, idx) + 1
            line_end = contents.find(b"\n", idx)
            if line_end == -1:
                line_end = len(contents)
            snippet = contents[line_start:line_end].decode("utf-8", errors="replace").strip()
            results.append(
                {
                    "match_ref": f"match_{len(results) + 1}",
                    "path": self._relative_str(file_path),
                    "line": line_no,
                    "snippet": snippet,
                }
            )
            if len(results) >= max_results:
                break
        return results

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def read_bytes_file(self, path: Any) -> dict[str, Any]:
        """Read ``path`` as bytes and return base64-encoded content.

        Accepts a path string or a file dict. Returns
        ``{"path": ..., "content_base64": ..., "truncated": ..., "size": ...}``.
        """
        target = self._safe_path(_extract_local_path(path))
        if not target.is_file():
            raise FileNotFoundError(self._relative_str(target))
        raw = target.read_bytes()
        truncated = False
        if len(raw) > self._max_read_bytes:
            raw = raw[: self._max_read_bytes]
            truncated = True
        return {
            "path": self._relative_str(target),
            "content_base64": base64.b64encode(raw).decode("ascii"),
            "truncated": truncated,
            "size": target.stat().st_size,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_tree(
        self,
        path: Any = "",
        *,
        pattern: str = "*",
        max_depth: int = 5,
        max_results: int = 1000,
    ) -> list[dict[str, Any]]:
        """Recursively list entries under ``path`` up to ``max_depth``.

        Returns the raw flat shape (``{"path": ..., "is_dir": ..., "size": ...,
        "mime_hint": ...}``). For human-friendly summaries prefer
        ``list_directory``. ``max_results`` defaults to 1000 — use it as a
        guardrail for large trees.
        """
        if max_depth < 0:
            raise ValueError("max_depth must be >= 0")
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        path = _extract_local_path(path) if not isinstance(path, str) else path
        target = self._safe_path(path)
        if not target.is_dir():
            raise NotADirectoryError(f"Not a directory: {self._relative_str(target)}")
        results: list[dict[str, Any]] = []
        base_depth = len(target.parts)
        for current, dirs, files in os.walk(target, followlinks=self._follow_symlinks):
            depth = len(Path(current).parts) - base_depth
            if depth > max_depth:
                dirs[:] = []
                continue
            dirs.sort()
            files.sort()
            for name in files:
                if pattern != "*" and not fnmatch.fnmatch(name, pattern):
                    continue
                file_path = Path(current) / name
                try:
                    self._enforce_root(file_path)
                except PathOutsideRootError:
                    continue
                entry = self._describe(file_path)
                results.append(
                    {
                        "path": entry.path,
                        "is_dir": entry.is_dir,
                        "size": entry.size,
                        "mime_hint": entry.mime_hint,
                    }
                )
                if len(results) >= max_results:
                    return results
        return results

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def file_exists(self, path: Any) -> dict[str, Any]:
        """Return whether ``path`` exists, and whether it is a file or directory.

        Accepts a path string or a file dict.
        """
        target = self._safe_path(_extract_local_path(path))
        exists = target.exists()
        return {
            "path": self._relative_str(target),
            "exists": exists,
            "is_dir": target.is_dir() if exists else False,
            "is_file": target.is_file() if exists else False,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_file_info(self, path: Any) -> dict[str, Any]:
        """Return file/directory metadata (size, mtime, type).

        Accepts a path string or a file dict.
        """
        target = self._safe_path(_extract_local_path(path))
        if not target.exists():
            raise FileNotFoundError(self._relative_str(target))
        st = target.stat()
        return {
            "path": self._relative_str(target),
            "is_dir": target.is_dir(),
            "is_file": target.is_file(),
            "size": st.st_size,
            "modified_at": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            "created_at": datetime.fromtimestamp(st.st_ctime, tz=timezone.utc).isoformat(),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def write_text_file(
        self,
        path: Any,
        content: str,
        *,
        encoding: str = "utf-8",
        overwrite: bool = False,
        create_parents: bool = False,
    ) -> dict[str, Any]:
        """Write ``content`` to ``path`` as text.

        Accepts a path string or a file dict. Refuses to clobber an existing
        file unless ``overwrite=True``.
        """
        target = self._safe_path(_extract_local_path(path))
        data = content.encode(encoding)
        return self._write_bytes(target, data, overwrite=overwrite, create_parents=create_parents)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def write_bytes_file(
        self,
        path: Any,
        content_base64: str,
        *,
        overwrite: bool = False,
        create_parents: bool = False,
    ) -> dict[str, Any]:
        """Write base64-decoded ``content_base64`` to ``path``.

        Accepts a path string or a file dict.
        """
        try:
            data = base64.b64decode(content_base64, validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"content_base64 must be valid base64: {exc}") from exc
        target = self._safe_path(_extract_local_path(path))
        return self._write_bytes(target, data, overwrite=overwrite, create_parents=create_parents)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def append_text_file(
        self,
        path: Any,
        content: str,
        *,
        encoding: str = "utf-8",
    ) -> dict[str, Any]:
        """Append ``content`` to an existing file (creates if missing).

        Accepts a path string or a file dict.
        """
        target = self._safe_path(_extract_local_path(path))
        data = content.encode(encoding)
        existing_size = target.stat().st_size if target.is_file() else 0
        total = existing_size + len(data)
        if total > self._max_write_bytes:
            raise ValueError(f"append would exceed max_write_bytes ({self._max_write_bytes})")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("ab") as fh:
            fh.write(data)
        return {
            "path": self._relative_str(target),
            "appended_bytes": len(data),
            "size": target.stat().st_size,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def make_directory(
        self,
        path: str,
        *,
        parents: bool = True,
        exist_ok: bool = True,
    ) -> dict[str, Any]:
        """Create a directory (and intermediate parents when ``parents=True``)."""
        target = self._safe_path(path)
        if target == self._root:
            raise ValueError("Refusing to recreate the connector root")
        target.mkdir(parents=parents, exist_ok=exist_ok)
        return {"path": self._relative_str(target), "created": True}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def copy_file(
        self,
        source: Any,
        destination: Any,
        *,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Copy a file from ``source`` to ``destination``.

        Both arguments accept a path string or a file dict.
        """
        src = self._safe_path(_extract_local_path(source))
        dst = self._safe_path(_extract_local_path(destination))
        if not src.is_file():
            raise FileNotFoundError(self._relative_str(src))
        if dst.exists() and not overwrite:
            raise FileExistsError(self._relative_str(dst))
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return {
            "source": self._relative_str(src),
            "destination": self._relative_str(dst),
            "size": dst.stat().st_size,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def move_file(
        self,
        source: Any,
        destination: Any,
        *,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Move/rename a file from ``source`` to ``destination``.

        Both arguments accept a path string or a file dict.
        """
        src = self._safe_path(_extract_local_path(source))
        dst = self._safe_path(_extract_local_path(destination))
        if not src.exists():
            raise FileNotFoundError(self._relative_str(src))
        if dst.exists():
            if not overwrite:
                raise FileExistsError(self._relative_str(dst))
            if dst.is_dir():
                shutil.rmtree(dst)
            else:
                dst.unlink()
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return {
            "source": self._relative_str(src),
            "destination": self._relative_str(dst),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_file(self, path: Any) -> dict[str, Any]:
        """Permanently delete a file. Refuses directories. Destructive — confirm with user.

        Accepts a path string or a file dict from ``list_directory``.
        Use ``remove_directory`` for folders.
        """
        target = self._safe_path(_extract_local_path(path))
        if target == self._root:
            raise ValueError("Refusing to delete the connector root")
        if not target.exists():
            raise FileNotFoundError(self._relative_str(target))
        if target.is_dir():
            raise IsADirectoryError(self._relative_str(target))
        target.unlink()
        return {"path": self._relative_str(target), "deleted": True}

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def remove_directory(
        self,
        path: Any,
        *,
        recursive: bool = False,
    ) -> dict[str, Any]:
        """Remove a directory. ``recursive=True`` removes contents too. Destructive.

        Accepts a path string or a folder dict. Confirm with the user
        before calling with ``recursive=True``.
        """
        target = self._safe_path(_extract_local_path(path))
        if target == self._root:
            raise ValueError("Refusing to remove the connector root")
        if not target.is_dir():
            raise NotADirectoryError(self._relative_str(target))
        if recursive:
            shutil.rmtree(target)
        else:
            target.rmdir()
        return {"path": self._relative_str(target), "removed": True}

    # MARK: - Internal helpers (not tools)

    def _write_bytes(
        self,
        target: Path,
        data: bytes,
        *,
        overwrite: bool,
        create_parents: bool,
    ) -> dict[str, Any]:
        if len(data) > self._max_write_bytes:
            raise ValueError(f"payload exceeds max_write_bytes ({self._max_write_bytes})")
        if target == self._root:
            raise IsADirectoryError(self._relative_str(target))
        if target.exists() and not overwrite:
            raise FileExistsError(self._relative_str(target))
        if create_parents:
            target.parent.mkdir(parents=True, exist_ok=True)
        elif not target.parent.exists():
            raise FileNotFoundError(self._relative_str(target.parent))
        target.write_bytes(data)
        return {
            "path": self._relative_str(target),
            "bytes_written": len(data),
            "size": target.stat().st_size,
        }

    def _walk_files(self, start: Path, pattern: str) -> Iterable[Path]:
        for current, dirs, files in os.walk(start, followlinks=self._follow_symlinks):
            dirs.sort()
            files.sort()
            for name in files:
                if pattern != "*" and not fnmatch.fnmatch(name, pattern):
                    continue
                file_path = Path(current) / name
                try:
                    self._enforce_root(file_path)
                except PathOutsideRootError:
                    continue
                yield file_path

    def _safe_path(self, path: str) -> Path:
        candidate = (self._root / path).expanduser() if path else self._root
        resolved = candidate.resolve(strict=False)
        self._enforce_root(resolved)
        return resolved

    def _enforce_root(self, candidate: Path) -> None:
        try:
            candidate.relative_to(self._root)
        except ValueError as exc:
            raise PathOutsideRootError(
                f"Path {candidate} escapes the connector root {self._root}"
            ) from exc

    def _relative_str(self, path: Path) -> str:
        try:
            return str(path.relative_to(self._root)).replace(os.sep, "/")
        except ValueError:
            return str(path)

    def _describe(self, path: Path) -> _FileEntry:
        is_dir = path.is_dir()
        size: int | None = None
        mime_hint: str | None = None
        modified_at: str | None = None
        try:
            st = path.stat()
            modified_at = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
            if not is_dir:
                size = st.st_size
        except OSError:
            pass
        if not is_dir:
            from ...files.mime import guess_mime_type

            mime_hint = guess_mime_type(path)
        return _FileEntry(
            path=self._relative_str(path),
            is_dir=is_dir,
            size=size,
            mime_hint=mime_hint,
            modified_at=modified_at,
        )
