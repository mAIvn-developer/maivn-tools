"""Canonical ZIP packaging for byte-stable OOXML files."""

# pyright: strict

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable

_CANONICAL_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def canonicalize_zip(
    raw: bytes,
    *,
    member_transform: Callable[[str, bytes], bytes] | None = None,
) -> bytes:
    """Return the same ZIP members in stable order with fixed metadata."""
    source = io.BytesIO(raw)
    destination = io.BytesIO()
    with (
        zipfile.ZipFile(source, 'r') as archive,
        zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as out,
    ):
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('refusing to canonicalize ZIP with duplicate members')
        for name in sorted(names):
            content = archive.read(name)
            if member_transform is not None:
                content = member_transform(name, content)
            info = zipfile.ZipInfo(name, date_time=_CANONICAL_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0
            info.flag_bits = 0
            out.writestr(info, content, compresslevel=9)
    return destination.getvalue()
