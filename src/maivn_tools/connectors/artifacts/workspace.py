"""Persisted manifest workspace used by local file generators."""

# pyright: strict

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import cast

_PROCESS_LOCK_GUARD = threading.Lock()
_PROCESS_LOCKS: dict[Path, threading.RLock] = {}
_PROCESS_BOUNDARY_ERROR = (
    'manifest workspace requires single-process-per-workspace ownership; '
    'create a separate workspace per process'
)
_HANDLE_ID_PATTERN = re.compile(r'[0-9a-f]{32}')
# Six attempts back off over ~310ms total; the prior ~70ms budget lost to
# foreign handles held 150ms (measured in the documents connector, same
# exposure - see its _replace_with_retry).
_ATOMIC_REPLACE_ATTEMPTS = 6
_ATOMIC_REPLACE_INITIAL_DELAY_SECONDS = 0.01


def _replace_with_retry(source: Path, target: Path) -> None:
    """Atomically replace a file, tolerating brief Windows scanner locks."""
    for attempt in range(_ATOMIC_REPLACE_ATTEMPTS):
        try:
            source.replace(target)
            return
        except PermissionError:
            if attempt == _ATOMIC_REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_ATOMIC_REPLACE_INITIAL_DELAY_SECONDS * (2**attempt))


def process_lock_for(workspace_dir: Path) -> threading.RLock:
    """Return the process-local lock for one manifest workspace.

    The lock deliberately coordinates threads only. Exactly one OS process must
    own a workspace directory; there is no file-lock protocol. If multi-process
    workspace sharing becomes a supported runtime topology, this seam must gain
    an inter-process lock and recovery design before that topology is enabled.
    """
    with _PROCESS_LOCK_GUARD:
        return _PROCESS_LOCKS.setdefault(workspace_dir, threading.RLock())


def assert_process_owner(owner_process_id: int) -> None:
    if os.getpid() != owner_process_id:
        raise RuntimeError(_PROCESS_BOUNDARY_ERROR)


class ManifestWorkspace:
    """Atomic JSON manifests beneath an output directory with isolated handles."""

    def __init__(
        self,
        output_dir: str | os.PathLike[str],
        *,
        workspace_name: str,
        id_field: str,
        extension: str,
    ) -> None:
        self.output_dir = Path(output_dir).expanduser().resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_dir = self.output_dir / f'.maivn-{workspace_name}'
        self.workspace_dir.mkdir(exist_ok=True)
        self.id_field = id_field
        self.extension = extension
        self._owner_process_id = os.getpid()
        self.lock = process_lock_for(self.workspace_dir)

    def create(self, filename: str, initial: Mapping[str, object]) -> dict[str, str]:
        assert_process_owner(self._owner_process_id)
        self.safe_output_path(filename)
        artifact_id = uuid.uuid4().hex
        handle = {self.id_field: artifact_id, 'filename': filename}
        manifest = {
            'version': 1,
            self.id_field: artifact_id,
            'filename': filename,
            **dict(initial),
        }
        self.write(artifact_id, manifest)
        return handle

    def load(self, handle: Mapping[str, object]) -> dict[str, object]:
        assert_process_owner(self._owner_process_id)
        artifact_id = handle.get(self.id_field)
        filename = handle.get('filename')
        if not isinstance(artifact_id, str) or _HANDLE_ID_PATTERN.fullmatch(artifact_id) is None:
            raise ValueError(f'invalid {self.id_field} handle')
        if not isinstance(filename, str):
            raise ValueError(f'invalid {self.id_field} handle')
        path = self.workspace_dir / f'{artifact_id}.json'
        if not path.is_file():
            raise ValueError(f'unknown {self.id_field}: {artifact_id}')
        manifest = cast('dict[str, object]', json.loads(path.read_text(encoding='utf-8')))
        if manifest.get('version') != 1:
            raise ValueError('unsupported manifest version')
        if manifest.get(self.id_field) != artifact_id or filename not in (
            manifest.get('filename'),
            manifest.get('private_handle_filename'),
        ):
            raise ValueError(f'{self.id_field} handle does not match its persisted workspace')
        return manifest

    def write(self, artifact_id: str, manifest: Mapping[str, object]) -> None:
        assert_process_owner(self._owner_process_id)
        target = self.workspace_dir / f'{artifact_id}.json'
        temporary = self.workspace_dir / f'.{artifact_id}.{uuid.uuid4().hex}.tmp'
        try:
            temporary.write_text(
                json.dumps(
                    dict(manifest), ensure_ascii=False, sort_keys=True, separators=(',', ':')
                )
                + '\n',
                encoding='utf-8',
            )
            _replace_with_retry(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def discard(self, handle: Mapping[str, object]) -> None:
        assert_process_owner(self._owner_process_id)
        artifact_id = handle.get(self.id_field)
        if isinstance(artifact_id, str) and _HANDLE_ID_PATTERN.fullmatch(artifact_id):
            (self.workspace_dir / f'{artifact_id}.json').unlink(missing_ok=True)

    def safe_output_path(self, filename: str) -> Path:
        assert_process_owner(self._owner_process_id)
        target = (self.output_dir / filename).resolve()
        if target.parent != self.output_dir or target.suffix.lower() != self.extension:
            raise ValueError(
                f'filename must be a {self.extension} file directly beneath output_dir'
            )
        return target

    def write_output(self, filename: str, raw: bytes, *, overwrite: bool) -> Path:
        assert_process_owner(self._owner_process_id)
        target = self.safe_output_path(filename)
        if overwrite:
            temporary = self.output_dir / f'.{target.name}.{uuid.uuid4().hex}.tmp'
            try:
                temporary.write_bytes(raw)
                _replace_with_retry(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        else:
            with target.open('xb') as stream:
                stream.write(raw)
        return target
