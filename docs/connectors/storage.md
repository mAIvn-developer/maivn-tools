# Storage

Local filesystem and cloud storage connectors. For Google Drive see
[Google Workspace](google-workspace.md); for OneDrive / SharePoint see
[Microsoft Graph](microsoft-graph.md).

Every connector follows the standard `@toolset` / `@toolify` shape and
marks destructive deletes / removals so hosts can filter them out via
`exclude_tags=["destructive"]`.

All three toolsets follow the same agent-ready conventions:

- List / search tools return compact summaries by default with a stable
  display ref (`file_ref`, `folder_ref`, `item_ref`, `match_ref`).
- Raw provider IDs are omitted by default. Pass `include_ids=True` only
  when a follow-up tool needs the raw ID.
- Pass `include_metadata=False` to get the unmodified provider response.
- Default `max_results` / `limit` is 25 unless noted otherwise.
- Write and delete tools accept either a raw ID/path or the dict
  returned by the corresponding list/get tool, so the natural
  `list -> act` chain works without unwrapping IDs by hand.

## LocalFilesToolSet

`LocalFilesToolSet` exposes filesystem tools sandboxed to a configured
root directory. Read tools cover directory listing, text / binary reads,
recursive walking, substring search, and stat. Write tools cover
text / binary writes, append, mkdir, copy, and move. Destructive tools
(file delete, directory remove) are tagged so hosts can filter them out
via `exclude_tags=["destructive"]`.

```python
from maivn import Agent
from maivn_tools import LocalFilesToolSet, register_connector

connector = LocalFilesToolSet(
    "/srv/exports",
    max_read_bytes=512_000,
    max_write_bytes=10_000_000,
)
agent = Agent(model="auto")
register_connector(agent, connector)
```

### Tools

| Tool | Permission | Description |
| --- | --- | --- |
| `list_directory(path, pattern, max_results, include_metadata, include_ids)` | READ | List entries under `path` with optional glob filter. Returns compact `file_ref` / `folder_ref` summaries by default. |
| `list_tree(path, pattern, max_depth, max_results)` | READ | Recursively list entries up to `max_depth`. Returns the flat raw shape. |
| `read_text_file(path, encoding)` | READ | Read text; reports true size and truncation. Accepts a path string or a file dict. |
| `read_bytes_file(path)` | READ | Read binary file as base64 plus metadata. Accepts a path string or a file dict. |
| `search_text(query, path, pattern, max_results)` | READ | Substring search across files. Returns `match_ref` summaries. |
| `file_exists(path)` | READ | Report whether `path` exists and what kind it is. |
| `get_file_info(path)` | READ | Return size, type, mtime, ctime for a path. |
| `write_text_file(path, content, encoding, overwrite, create_parents)` | WRITE | Write text to a file. |
| `write_bytes_file(path, content_base64, overwrite, create_parents)` | WRITE | Write base64-decoded bytes to a file. |
| `append_text_file(path, content, encoding)` | WRITE | Append text to a file (creates if missing). |
| `make_directory(path, parents, exist_ok)` | WRITE | Create a directory (and intermediate parents). |
| `copy_file(source, destination, overwrite)` | WRITE | Copy a file. Both arguments accept a path string or a file dict. |
| `move_file(source, destination, overwrite)` | WRITE | Move or rename a file. Both arguments accept a path string or a file dict. |
| `delete_file(path)` | DELETE (destructive) | Permanently delete a file. Accepts a path string or a file dict. |
| `remove_directory(path, recursive)` | DELETE (destructive) | Remove a directory (optionally recursive). Accepts a path string or a folder dict. |

### Agent-ready behavior

- `list_directory` returns compact summaries with `file_ref` /
  `folder_ref` (`file_1`, `folder_1`, ...), `name`, `path`, `kind`,
  `size`, `modified_at`, and `mime_hint`. The relative `path` is always
  included because that is how follow-up tools address local files.
  `include_metadata=False` returns the legacy flat shape.
  `include_ids=True` is accepted for symmetry but is a no-op (local
  paths *are* the identifier).
- `search_text` returns a list of `match_ref` summaries with `path`,
  `line`, and `snippet`. Default `max_results=25`.
- Read and write tools (`read_text_file`, `read_bytes_file`,
  `write_text_file`, `write_bytes_file`, `append_text_file`,
  `get_file_info`, `file_exists`, `delete_file`, `remove_directory`,
  `copy_file`, `move_file`) accept either a raw path string or a file
  dict from `list_directory`, so the natural `list -> read` /
  `list -> delete` chain works without manual unwrapping.

```python
entries = connector.list_directory("reports")
# [{"file_ref": "file_1", "name": "Q3.csv", "path": "reports/Q3.csv",
#   "kind": "file", "size": 12034, "modified_at": "...", "mime_hint": "text/csv"}]
connector.read_text_file(entries[0])
```

### Destructive tools

`delete_file` and `remove_directory` (with `recursive=True`) are tagged
`destructive` and require `PermissionFlag.DELETE`. Filter them off the
toolset with `exclude_tags=["destructive"]` for read-only / safe-edit
agents. Both refuse to operate on the connector root.

### Sandbox guarantees

Every path argument is resolved against the configured root before any
I/O runs. The connector raises `PathOutsideRootError` for:

- Absolute paths outside the root.
- Relative paths that traverse out via `..`.
- Symlink targets that escape the root, unless `follow_symlinks=True`.

These checks run after `pathlib.resolve()`, so `.` and `..` segments
are collapsed before comparison.

| Argument | Default | Purpose |
| --- | --- | --- |
| `root` | required | Sandbox directory. Must already exist. |
| `follow_symlinks` | `False` | Whether `os.walk` should follow symlinks. |
| `max_read_bytes` | `1_000_000` | Cap on bytes returned by `read_text_file`/`read_bytes_file`. |
| `max_write_bytes` | `10_000_000` | Cap on bytes accepted by write/append tools. |

## BoxToolSet

Wraps Box Content API v2 with an OAuth bearer token.

```python
from maivn_tools import BoxToolSet

connector = BoxToolSet(token=secrets["BOX_TOKEN"])
```

Tools: `get_current_user`, `get_user`, `get_folder(folder_id="0")`,
`list_folder_items(folder_id, offset, limit, fields, include_metadata, include_ids)`,
`create_folder`, `update_folder`, `copy_folder`,
`delete_folder` (destructive), `get_file`, `update_file`, `copy_file`,
`delete_file` (destructive), `get_file_download_url`,
`list_file_versions`,
`search(query, type, scope, offset, limit, file_extensions, include_metadata, include_ids)`,
`list_collaborations`, `create_collaboration`,
`delete_collaboration` (destructive), `create_shared_link`,
`list_trash`, `empty_trash` (destructive, raises -- use
`permanently_delete`), `permanently_delete` (destructive).

### Agent-ready behavior

- `list_folder_items` and `search` return compact item summaries by
  default: `file_ref` / `folder_ref` (`file_1`, `folder_1`, ...),
  `name`, `kind`, `size`, `modified_time`, `owner`. Default `limit=25`.
  Raw Box IDs are omitted; pass `include_ids=True` to add `file_id` /
  `folder_id` (and `parent_id`) for follow-up tools. Pass
  `include_metadata=False` to return the raw provider response.
- `get_folder`, `update_folder`, `delete_folder`, `copy_folder`,
  `get_file`, `update_file`, `copy_file`, `delete_file`,
  `get_file_download_url`, and `list_file_versions` accept either a
  raw ID string or a dict returned from `list_folder_items` / `search`
  (the connector looks up `file_id` / `folder_id` / `item_id` / `id`).

```python
results = connector.search("Q3 plan", type="file")
# [{"file_ref": "file_1", "name": "Q3 plan.docx", "kind": "file",
#   "size": 14821, "modified_time": "...", "owner": "Alice"}]

with_ids = connector.search("Q3 plan", type="file", include_ids=True)
connector.delete_file(with_ids["items"][0])  # accepts the dict directly
```

### Destructive tools

`delete_folder`, `delete_file`, `delete_collaboration`, `empty_trash`,
and `permanently_delete` are tagged `destructive` and require
`PermissionFlag.DELETE`. Box `empty_trash` raises by design (Box has no
bulk endpoint); iterate trashed items and call `permanently_delete` per
item. Filter destructive tools off the toolset with
`exclude_tags=["destructive"]` when wiring a read-only / safe-edit
agent.

## DropboxToolSet

Wraps the Dropbox API v2 (RPC-style POST endpoints).

```python
from maivn_tools import DropboxToolSet

connector = DropboxToolSet(token=secrets["DROPBOX_TOKEN"])
```

Tools: `get_current_account`, `get_space_usage`,
`list_folder(path, recursive, include_deleted, limit, include_metadata, include_ids)`,
`list_folder_continue(cursor, include_metadata, include_ids)`,
`get_metadata`,
`search(query, path, max_results, include_metadata, include_ids)`,
`get_temporary_link`, `create_folder`, `move`, `copy`,
`delete` (destructive), `restore`, `list_revisions`,
`create_shared_link`, `list_shared_links`,
`revoke_shared_link` (destructive), `list_file_requests`,
`create_file_request`.

### Agent-ready behavior

- `list_folder`, `list_folder_continue`, and `search` return compact
  item summaries by default: `file_ref` / `folder_ref` (`file_1`,
  `folder_1`, ...), `name`, `kind`, `path`, `size`, `modified_time`.
  Paths are how Dropbox identifies items and are safe to show in final
  answers. Default `limit` / `max_results=25`. Pass `include_ids=True`
  to add the Dropbox content `id` (and `rev` for files) for
  `restore` / `list_revisions`. Pass `include_metadata=False` to return
  the raw provider response. Use `has_more` / `cursor` from the
  summary payload to drive `list_folder_continue`.
- `get_metadata`, `get_temporary_link`, `move` (`from_path`),
  `copy` (`from_path`), `delete`, `list_revisions`, and
  `create_shared_link` accept either a raw Dropbox path string or a
  file/folder dict from `list_folder` / `search` (the connector reads
  `path`, `path_lower`, `path_display`, or `id`, and also unwraps
  `search_v2`-style nested `metadata` entries).

```python
results = connector.search("budget", max_results=5)
# {"items": [{"file_ref": "file_1", "name": "budget.xlsx", "kind": "file",
#             "path": "/Finance/budget.xlsx", "size": 8204,
#             "modified_time": "..."}, ...]}
connector.get_temporary_link(results["items"][0])
```

### Destructive tools

`delete` (soft-delete, recoverable via `restore`) and
`revoke_shared_link` are tagged `destructive` and require
`PermissionFlag.DELETE`. Filter them off the toolset with
`exclude_tags=["destructive"]` for read-only / safe-edit agents.
