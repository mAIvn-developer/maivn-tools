from __future__ import annotations

import maivn_tools


def test_package_exports_version() -> None:
    assert maivn_tools.__version__ == "0.1.0"
