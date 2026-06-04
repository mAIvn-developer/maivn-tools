# Google productivity

`GoogleDocsToolSet`, `GoogleSheetsToolSet`, and `GoogleSlidesToolSet`
wrap the Docs, Sheets, and Slides APIs respectively. They share the
OAuth bearer token handling from
[`google_workspace._shared`](google-workspace.md).

All three toolsets are content-level editors -- they assume you already
have the document/spreadsheet/presentation ID. To find one by name,
use [`GoogleDriveToolSet.search_files(include_ids=True)`](google-workspace.md)
and pass the returned file dict into any of these tools. The Docs /
Sheets / Slides tools accept either a raw ID string or a Drive file
dict (or a dict from another tool in the same toolset) and will pull
the right ID out.

## GoogleDocsToolSet

```python
from maivn_tools import GoogleDocsToolSet

connector = GoogleDocsToolSet(token=token_cache)
```

| Tool | Permission | Description |
| --- | --- | --- |
| `get_document(document_id)` | READ | Fetch a Doc. Accepts a raw doc ID or a Drive file dict. |
| `create_document(title)` | WRITE | Create a blank Doc. |
| `batch_update(document_id, requests, write_control)` | WRITE | Apply Docs API update requests. |
| `insert_text(document_id, text, index)` | WRITE | Insert text. |
| `replace_text(document_id, find, replace, match_case)` | WRITE | Find/replace. |
| `delete_content_range(document_id, start_index, end_index)` | DELETE (destructive) | Delete a range. |

### Agent-ready behavior

- `GoogleDocsToolSet` has no list/search of its own -- use
  `GoogleDriveToolSet.search_files(include_ids=True)` to locate a Doc,
  then pass the returned file dict to `get_document` /
  `batch_update` / `insert_text` / `replace_text` /
  `delete_content_range`. The connector reads `doc_id` /
  `document_id` / `documentId` / `file_id` / `id` out of the dict.
- `create_document` returns the new Doc resource; pass its
  `documentId` (or the whole dict) to the edit tools to populate it.

```python
# Find then edit, without unwrapping IDs by hand.
file = drive.search_files("Launch plan", include_ids=True)["files"][0]
docs.insert_text(file, text="Status update\n")
```

### Destructive tools

`delete_content_range` is tagged `destructive` and requires
`PermissionFlag.DELETE`. Filter it off the toolset with
`exclude_tags=["destructive"]` for read-only / safe-edit agents.

## GoogleSheetsToolSet

```python
from maivn_tools import GoogleSheetsToolSet

connector = GoogleSheetsToolSet(token=token_cache)
```

| Tool | Permission | Description |
| --- | --- | --- |
| `get_spreadsheet(spreadsheet_id, include_grid_data, ranges)` | READ | Metadata + grid data. Accepts a raw ID or a Drive file dict. |
| `create_spreadsheet(title, sheets)` | WRITE | Create a spreadsheet. |
| `get_values(spreadsheet_id, range, major_dimension, value_render_option, date_time_render_option)` | READ | Read a range. |
| `batch_get_values(spreadsheet_id, ranges, major_dimension, value_render_option)` | READ | Multi-range read. |
| `update_values(spreadsheet_id, range, values, value_input_option)` | WRITE | Overwrite a range. |
| `append_values(spreadsheet_id, range, values, value_input_option, insert_data_option)` | WRITE | Append rows. |
| `clear_values(spreadsheet_id, range)` | DELETE (destructive) | Clear a range. |
| `batch_update(spreadsheet_id, requests)` | WRITE | Spreadsheet-level updates. |
| `add_sheet(spreadsheet_id, title, row_count, column_count)` | WRITE | Add a sheet. |
| `delete_sheet(spreadsheet_id, sheet_id)` | DELETE (destructive) | Remove a sheet. |

### Agent-ready behavior

- `GoogleSheetsToolSet` is a value/range editor -- use
  `GoogleDriveToolSet.search_files(include_ids=True)` to locate a
  spreadsheet, then pass the returned file dict to any of these tools.
  The connector reads `sheet_ref_id` / `spreadsheet_id` /
  `spreadsheetId` / `file_id` / `id` out of the dict.
- `get_spreadsheet` returns the full Sheets resource; with
  `include_grid_data=True` and `ranges` you also get cell-level values.
- `create_spreadsheet` returns the new resource; pass its
  `spreadsheetId` (or the whole dict) to the value / batch_update
  tools.

```python
file = drive.search_files("Q4 forecast", include_ids=True)["files"][0]
sheets.get_values(file, range="Plan!A1:D20")
```

### Destructive tools

`clear_values` and `delete_sheet` are tagged `destructive` and require
`PermissionFlag.DELETE`. `clear_values` removes cell contents but
leaves formatting; `delete_sheet` removes an entire tab. Filter them
off the toolset with `exclude_tags=["destructive"]` for read-only /
safe-edit agents.

## GoogleSlidesToolSet

```python
from maivn_tools import GoogleSlidesToolSet

connector = GoogleSlidesToolSet(token=token_cache)
```

| Tool | Permission | Description |
| --- | --- | --- |
| `get_presentation(presentation_id)` | READ | Fetch presentation. Accepts a raw ID or a Drive file dict. |
| `get_page(presentation_id, page_object_id)` | READ | One slide / master / layout. |
| `get_page_thumbnail(presentation_id, page_object_id, thumbnail_size, mime_type)` | READ | Slide thumbnail URL. |
| `create_presentation(title)` | WRITE | New deck. |
| `batch_update(presentation_id, requests)` | WRITE | Slides API update requests. |
| `create_slide(presentation_id, insertion_index, layout, object_id)` | WRITE | Insert a slide. |
| `insert_text(presentation_id, object_id, text, insertion_index)` | WRITE | Add text to a shape. |
| `replace_all_text(presentation_id, find, replace, match_case)` | WRITE | Find/replace. |
| `delete_object(presentation_id, object_id)` | DELETE (destructive) | Remove a slide / shape. |

### Agent-ready behavior

- `GoogleSlidesToolSet` is a slide/shape/text editor -- use
  `GoogleDriveToolSet.search_files(include_ids=True)` to locate a
  deck, then pass the returned file dict to any of these tools. The
  connector reads `presentation_id` / `presentationId` / `file_id` /
  `id` out of the dict.
- `get_presentation` returns the full Slides resource with
  `slides[*]`, `masters[*]`, `layouts[*]`. Each slide's `objectId` is
  the `page_object_id` argument for `get_page` /
  `get_page_thumbnail`, and the input for the `object_id` argument of
  `insert_text` / `delete_object`.
- `create_presentation` returns the new resource; pass its
  `presentationId` (or the whole dict) to the edit tools.

```python
file = drive.search_files("All-hands deck", include_ids=True)["files"][0]
deck = slides.get_presentation(file)
slides.replace_all_text(file, find="{{date}}", replace="2026-05-16")
```

### Destructive tools

`delete_object` is tagged `destructive` and requires
`PermissionFlag.DELETE`. It removes a slide, shape, or other page
object permanently. Filter it off the toolset with
`exclude_tags=["destructive"]` for read-only / safe-edit agents.
