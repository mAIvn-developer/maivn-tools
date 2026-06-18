# pyright: strict
from __future__ import annotations

import re

import maivn_tools


def test_package_exports_version() -> None:
    # Assert the version is exported and well-formed rather than pinning a
    # literal, so routine version bumps don't break this test.
    assert re.fullmatch(r"\d+\.\d+\.\d+\S*", maivn_tools.__version__) is not None
