# pyright: strict
from __future__ import annotations

from pathlib import Path

import pytest

from maivn_tools.connectors.files import LocalFilesToolSet, PathOutsideRootError


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    (tmp_path / "subdir").mkdir()
    (tmp_path / "a.txt").write_text("hello world\nsecond line\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("# title\nhello again\n", encoding="utf-8")
    (tmp_path / "subdir" / "c.txt").write_text("nested content with hello\n", encoding="utf-8")
    return tmp_path


def test_local_files_validates_root(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        LocalFilesToolSet(tmp_path / "missing")

    file_path = tmp_path / "file"
    file_path.write_text("x")
    with pytest.raises(NotADirectoryError):
        LocalFilesToolSet(file_path)


def test_local_files_validates_max_read_bytes(sandbox: Path) -> None:
    with pytest.raises(ValueError):
        LocalFilesToolSet(sandbox, max_read_bytes=0)


def test_list_directory_root_and_pattern(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    entries = connector.list_directory()
    names = {entry["path"]: entry for entry in entries}
    assert "a.txt" in names
    assert "subdir" in names
    assert names["subdir"]["kind"] == "folder"
    assert names["a.txt"]["mime_hint"] == "text/plain"

    md_only = connector.list_directory(pattern="*.md")
    assert {entry["path"] for entry in md_only} == {"b.md"}


def test_list_directory_returns_ref_summaries_by_default(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    entries = connector.list_directory()
    assert entries, "expected at least one entry"
    # Each entry has a file_ref or folder_ref, plus name/kind/modified_at.
    for entry in entries:
        assert any(key in entry for key in ("file_ref", "folder_ref"))
        assert "kind" in entry
        assert "name" in entry
        assert "path" in entry


def test_list_directory_include_metadata_false_returns_raw_shape(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    entries = connector.list_directory(include_metadata=False)
    by_path = {entry["path"]: entry for entry in entries}
    assert "subdir" in by_path
    assert by_path["subdir"]["is_dir"] is True


def test_list_directory_respects_max_results(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    entries = connector.list_directory(max_results=1)
    assert len(entries) == 1


def test_list_directory_rejects_outside_paths(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    with pytest.raises(PathOutsideRootError):
        connector.list_directory(path="../escape")


def test_list_directory_requires_dir(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    with pytest.raises(NotADirectoryError):
        connector.list_directory(path="a.txt")


def test_read_text_file_truncation(sandbox: Path) -> None:
    big = sandbox / "big.txt"
    big.write_text("x" * 100, encoding="utf-8")
    connector = LocalFilesToolSet(sandbox, max_read_bytes=10)
    result = connector.read_text_file(path="big.txt")
    assert result["truncated"] is True
    assert len(result["content"]) == 10
    assert result["size"] == 100


def test_read_text_file_not_found(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    with pytest.raises(FileNotFoundError):
        connector.read_text_file(path="missing.txt")


def test_search_text_finds_matches_with_line_numbers(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    results = connector.search_text("hello")
    snippets = {result["path"]: result for result in results}
    assert "a.txt" in snippets
    assert snippets["a.txt"]["line"] == 1
    assert "hello" in snippets["a.txt"]["snippet"]


def test_search_text_validates_inputs(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    with pytest.raises(ValueError):
        connector.search_text("")
    with pytest.raises(ValueError):
        connector.search_text("hi", max_results=0)
    with pytest.raises(NotADirectoryError):
        connector.search_text("hi", path="a.txt")


def test_search_text_pattern_filter(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    results = connector.search_text("hello", pattern="*.md")
    assert all(result["path"].endswith(".md") for result in results)


def test_toolset_marker_is_present(sandbox: Path) -> None:
    """LocalFilesToolSet should be discoverable as a @toolset class."""
    from maivn._internal.utils.toolset import get_toolify_options, get_toolset_options

    opts = get_toolset_options(LocalFilesToolSet)
    assert opts is not None
    assert opts.prefix == "local_files"
    connector = LocalFilesToolSet(sandbox)
    assert get_toolify_options(connector.list_directory) is not None
    assert get_toolify_options(connector.read_text_file) is not None
    assert get_toolify_options(connector.search_text) is not None


def test_symlink_outside_root_is_rejected(tmp_path: Path) -> None:
    sandbox = tmp_path / "sb"
    sandbox.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    try:
        (sandbox / "link.txt").symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        # Windows without admin / Developer Mode can't create symlinks.
        pytest.skip(f"host cannot create symlinks: {exc}")

    connector = LocalFilesToolSet(sandbox)
    with pytest.raises(PathOutsideRootError):
        connector.read_text_file(path="link.txt")


def test_read_bytes_file_returns_base64(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    result = connector.read_bytes_file(path="a.txt")
    import base64

    decoded = base64.b64decode(result["content_base64"]).decode()
    assert "hello" in decoded


def test_list_tree_recursive_with_depth(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    flat = connector.list_tree(max_depth=0)
    paths = {entry["path"] for entry in flat}
    assert "a.txt" in paths
    assert all("/" not in p for p in paths)

    deep = connector.list_tree(max_depth=5)
    deep_paths = {entry["path"] for entry in deep}
    assert "subdir/c.txt" in deep_paths


def test_list_tree_validates_inputs(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    with pytest.raises(ValueError):
        connector.list_tree(max_depth=-1)
    with pytest.raises(ValueError):
        connector.list_tree(max_results=0)


def test_file_exists_reports_state(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    assert connector.file_exists("a.txt")["exists"] is True
    assert connector.file_exists("a.txt")["is_file"] is True
    assert connector.file_exists("subdir")["is_dir"] is True
    assert connector.file_exists("missing")["exists"] is False


def test_get_file_info_returns_size_and_timestamps(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    info = connector.get_file_info("a.txt")
    assert info["is_file"] is True
    assert info["size"] > 0
    assert "T" in info["modified_at"]


def test_get_file_info_missing_raises(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    with pytest.raises(FileNotFoundError):
        connector.get_file_info("missing")


def test_write_text_file_creates_and_protects(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    result = connector.write_text_file("new.txt", "abc")
    assert (sandbox / "new.txt").read_text() == "abc"
    assert result["bytes_written"] == 3

    with pytest.raises(FileExistsError):
        connector.write_text_file("new.txt", "x")

    connector.write_text_file("new.txt", "x", overwrite=True)
    assert (sandbox / "new.txt").read_text() == "x"


def test_write_text_file_requires_parent_or_create_parents(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    with pytest.raises(FileNotFoundError):
        connector.write_text_file("nested/x.txt", "abc")
    connector.write_text_file("nested/x.txt", "abc", create_parents=True)
    assert (sandbox / "nested" / "x.txt").read_text() == "abc"


def test_write_text_file_respects_max_write_bytes(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox, max_write_bytes=5)
    with pytest.raises(ValueError):
        connector.write_text_file("big.txt", "x" * 6)


def test_write_bytes_file_decodes_base64(sandbox: Path) -> None:
    import base64

    connector = LocalFilesToolSet(sandbox)
    payload = base64.b64encode(b"\x00\x01\x02").decode()
    connector.write_bytes_file("bin.dat", payload)
    assert (sandbox / "bin.dat").read_bytes() == b"\x00\x01\x02"


def test_write_bytes_file_rejects_bad_base64(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    with pytest.raises(ValueError):
        connector.write_bytes_file("bin.dat", "not!!!valid!!!")


def test_append_text_file_concatenates(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    connector.write_text_file("log.txt", "line1\n")
    connector.append_text_file("log.txt", "line2\n")
    assert (sandbox / "log.txt").read_text() == "line1\nline2\n"


def test_append_text_file_creates_missing(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    connector.append_text_file("brand-new.txt", "hello")
    assert (sandbox / "brand-new.txt").read_text() == "hello"


def test_make_directory_creates_nested(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    connector.make_directory("a/b/c")
    assert (sandbox / "a" / "b" / "c").is_dir()


def test_make_directory_refuses_root(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    with pytest.raises(ValueError):
        connector.make_directory("")


def test_copy_file_writes_destination(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    connector.copy_file("a.txt", "subdir/a-copy.txt")
    assert (sandbox / "subdir" / "a-copy.txt").read_text() == (sandbox / "a.txt").read_text()


def test_copy_file_overwrite_guard(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    connector.copy_file("a.txt", "copy.txt")
    with pytest.raises(FileExistsError):
        connector.copy_file("a.txt", "copy.txt")
    connector.copy_file("a.txt", "copy.txt", overwrite=True)


def test_move_file_renames(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    connector.move_file("a.txt", "renamed.txt")
    assert not (sandbox / "a.txt").exists()
    assert (sandbox / "renamed.txt").exists()


def test_move_file_missing_source_raises(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    with pytest.raises(FileNotFoundError):
        connector.move_file("missing.txt", "x.txt")


def test_delete_file_removes(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    connector.delete_file("a.txt")
    assert not (sandbox / "a.txt").exists()


def test_delete_file_refuses_directory(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    with pytest.raises(IsADirectoryError):
        connector.delete_file("subdir")


def test_delete_file_refuses_root(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    with pytest.raises(ValueError):
        connector.delete_file("")


def test_remove_directory_empty_and_recursive(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    (sandbox / "empty").mkdir()
    connector.remove_directory("empty")
    assert not (sandbox / "empty").exists()

    with pytest.raises(OSError):
        connector.remove_directory("subdir")
    connector.remove_directory("subdir", recursive=True)
    assert not (sandbox / "subdir").exists()


def test_read_text_file_accepts_dict_input(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    entry = connector.list_directory()[0]
    # The summary dict's path field is what we use to round-trip.
    result = connector.read_text_file(entry)
    assert "content" in result
    assert result["path"] == entry["path"]


def test_delete_file_accepts_dict_input(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    (sandbox / "doomed.txt").write_text("x")
    summaries = connector.list_directory()
    doomed = next(item for item in summaries if item["path"] == "doomed.txt")
    connector.delete_file(doomed)
    assert not (sandbox / "doomed.txt").exists()


def test_move_file_accepts_dict_input(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    # Move a.txt -> renamed.txt by passing the list_directory dict.
    summaries = connector.list_directory()
    a = next(item for item in summaries if item["path"] == "a.txt")
    connector.move_file(a, {"path": "renamed.txt"})
    assert not (sandbox / "a.txt").exists()
    assert (sandbox / "renamed.txt").exists()


def test_destructive_markers_on_local_files(sandbox: Path) -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector = LocalFilesToolSet(sandbox)
    delete_opts = get_toolify_options(connector.delete_file)
    remove_opts = get_toolify_options(connector.remove_directory)
    assert delete_opts is not None and delete_opts.destructive is True
    assert remove_opts is not None and remove_opts.destructive is True


def test_search_text_returns_match_refs(sandbox: Path) -> None:
    connector = LocalFilesToolSet(sandbox)
    results = connector.search_text("hello")
    assert results
    for index, match in enumerate(results, start=1):
        assert match["match_ref"] == f"match_{index}"
