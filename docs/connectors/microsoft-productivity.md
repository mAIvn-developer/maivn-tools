# Microsoft productivity

Read and edit Office documents -- Excel workbooks, Word documents, and
PowerPoint decks -- through Microsoft Graph.

`MicrosoftExcelToolSet`, `MicrosoftWordToolSet`, and
`MicrosoftPowerPointToolSet` wrap document-format operations on top of
Microsoft Graph. They share the auth and HTTP-client plumbing used by
[`microsoft_graph` connectors](microsoft-graph.md). Pass ``drive_id`` to
target a specific drive instead of ``/me/drive``.

All three toolsets are content-level editors -- they assume you already
have the Graph drive-item ID for the workbook/document/deck. To find
one by name, use
[`MicrosoftFilesToolSet.search_files(include_ids=True)`](microsoft-graph.md)
and pass the returned item dict into any of these tools. Each Excel /
Word / PowerPoint tool accepts either a raw item-ID string or a Graph
item dict and will pull the right ID out.

## MicrosoftExcelToolSet

```python
from maivn_tools import MicrosoftExcelToolSet

connector = MicrosoftExcelToolSet(token=token_cache)
```

| Tool | Permission | Description |
| --- | --- | --- |
| `list_worksheets(item_id)` / `get_worksheet(item_id, name)` | READ | Worksheets. |
| `add_worksheet(item_id, name)` | WRITE | Add a worksheet. |
| `delete_worksheet(item_id, name)` | DELETE (destructive) | Remove a worksheet. |
| `get_range(item_id, worksheet, address)` / `get_used_range(item_id, worksheet, values_only)` | READ | Ranges. |
| `update_range(item_id, worksheet, address, values, formulas, number_format)` | WRITE | Patch a range. |
| `clear_range(item_id, worksheet, address, apply_to)` | DELETE (destructive) | Clear cell contents. |
| `list_tables(item_id, worksheet)` / `add_table(item_id, worksheet, address, has_headers)` | READ / WRITE | Tables. |
| `add_table_rows(item_id, table_name, values, index)` / `get_table_rows(item_id, table_name)` | WRITE / READ | Table rows. |
| `delete_table(item_id, table_name)` | DELETE (destructive) | Remove a table. |
| `create_session(item_id, persist_changes)` / `close_session(item_id, workbook_session_id)` | WRITE | Workbook sessions. |

### Agent-ready behavior

- `MicrosoftExcelToolSet` is a worksheet/range/table editor -- use
  `MicrosoftFilesToolSet.search_files(include_ids=True)` to locate a
  workbook, then pass the returned item dict to any of these tools.
  The connector reads `item_id` / `file_id` / `workbook_id` / `id`
  out of the dict.
- `list_worksheets`, `get_used_range`, `list_tables`, and `get_table_rows`
  return the raw Graph response (e.g. `{"value": [...]}`); they are
  small enough that no summary mode is needed. Use `list_worksheets`
  or `get_used_range` as a first call when you do not know a
  workbook's extent.
- `create_session` returns ``{"id": <session_id>, ...}``. Pass that
  ``id`` to subsequent calls via the ``Workbook-Session-Id`` header
  for efficient batched edits, then call `close_session` to commit
  or discard.

```python
file = files.search_files("Q4 forecast.xlsx", include_ids=True)["items"][0]
excel.list_worksheets(file)
excel.get_used_range(file, worksheet="Plan", values_only=True)
```

### Destructive tools

`delete_worksheet`, `clear_range`, and `delete_table` are tagged
`destructive` and require `PermissionFlag.DELETE`. `clear_range`'s
`apply_to` argument controls whether contents, formats, or both are
cleared (`"All"` by default). Filter the destructive surface off the
toolset with `exclude_tags=["destructive"]` for read-only / safe-edit
agents.

## MicrosoftWordToolSet

```python
from maivn_tools import MicrosoftWordToolSet

connector = MicrosoftWordToolSet(token=token_cache)
```

Word does not expose structured editing through Microsoft Graph; this
toolset covers the surface that *does* exist.

| Tool | Permission | Description |
| --- | --- | --- |
| `get_metadata(item_id)` | READ | DriveItem metadata. |
| `download_content(item_id)` | READ | Raw `.docx` bytes. |
| `convert_to(item_id, format)` | READ | Download in another format (`pdf`, `html`, `jpg`, `glb`). |
| `replace_content(item_id, content_bytes)` | WRITE | Overwrite the document. |
| `upload_new(path, content_bytes)` | WRITE | Upload a new `.docx`. |

### Agent-ready behavior

- `MicrosoftWordToolSet` has no list/search of its own -- use
  `MicrosoftFilesToolSet.search_files(include_ids=True)` to locate a
  document, then pass the returned item dict to `get_metadata` /
  `download_content` / `convert_to` / `replace_content`. The
  connector reads `item_id` / `file_id` / `id` out of the dict.
- `download_content` and `convert_to` return
  ``{"item_id": ..., "status": ..., "body": <bytes>}`` (with `format`
  on `convert_to`). The body is raw bytes, not base64 -- if you need
  to ship it through a JSON-only tool channel, base64-encode it
  yourself.
- `replace_content` is limited to ~4 MB; for larger files use
  [`MicrosoftFilesToolSet.create_upload_session`](microsoft-graph.md).

```python
file = files.search_files("Launch plan.docx", include_ids=True)["items"][0]
word.convert_to(file, format="pdf")
```

### Destructive tools

`MicrosoftWordToolSet` does not expose any DELETE-tagged tools.
`replace_content` does overwrite the existing document in place --
treat it as destructive in workflow even though it is tagged WRITE
(filtering on `exclude_tags=["destructive"]` will *not* remove it).
For file deletion, use
[`MicrosoftFilesToolSet`](microsoft-graph.md).

## MicrosoftPowerPointToolSet

```python
from maivn_tools import MicrosoftPowerPointToolSet

connector = MicrosoftPowerPointToolSet(token=token_cache)
```

| Tool | Permission | Description |
| --- | --- | --- |
| `get_metadata(item_id)` | READ | DriveItem metadata. |
| `download_content(item_id)` | READ | Raw `.pptx` bytes. |
| `convert_to(item_id, format)` | READ | Download as PDF / JPG. |
| `list_thumbnails(item_id)` | READ | Slide thumbnails. |
| `replace_content(item_id, content_bytes)` | WRITE | Overwrite the deck. |
| `upload_new(path, content_bytes)` | WRITE | Upload a new `.pptx`. |

### Agent-ready behavior

- `MicrosoftPowerPointToolSet` has no list/search of its own -- use
  `MicrosoftFilesToolSet.search_files(include_ids=True)` to locate a
  deck, then pass the returned item dict to `get_metadata` /
  `download_content` / `convert_to` / `list_thumbnails` /
  `replace_content`. The connector reads `item_id` / `file_id` /
  `presentation_id` / `id` out of the dict.
- `download_content` and `convert_to` return
  ``{"item_id": ..., "status": ..., "body": <bytes>}`` (with `format`
  on `convert_to`). The body is raw bytes; `convert_to` accepts
  ``pdf`` or ``jpg`` only.
- `replace_content` is limited to ~4 MB; for larger files use
  [`MicrosoftFilesToolSet.create_upload_session`](microsoft-graph.md).

```python
file = files.search_files("All-hands deck.pptx", include_ids=True)["items"][0]
powerpoint.list_thumbnails(file)
```

### Destructive tools

`MicrosoftPowerPointToolSet` does not expose any DELETE-tagged tools.
`replace_content` does overwrite the existing deck in place -- treat
it as destructive in workflow even though it is tagged WRITE
(filtering on `exclude_tags=["destructive"]` will *not* remove it).
For file deletion, use
[`MicrosoftFilesToolSet`](microsoft-graph.md).
