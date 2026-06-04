# pyright: strict
from __future__ import annotations

import pytest

from maivn_tools.connectors.google_docs import GoogleDocsToolSet
from maivn_tools.connectors.google_sheets import GoogleSheetsToolSet
from maivn_tools.connectors.google_slides import GoogleSlidesToolSet
from maivn_tools.connectors.ms_excel import MicrosoftExcelToolSet
from maivn_tools.connectors.ms_powerpoint import MicrosoftPowerPointToolSet
from maivn_tools.connectors.ms_word import MicrosoftWordToolSet
from maivn_tools.testing import MockTransport, json_response, text_response


def _docs() -> tuple[GoogleDocsToolSet, MockTransport]:
    transport = MockTransport()
    return GoogleDocsToolSet(token="t", transport=transport), transport


def test_google_docs() -> None:
    connector, transport = _docs()
    for _ in range(6):
        transport.enqueue(json_response({"documentId": "d1"}))
    connector.get_document("d1")
    connector.create_document("New doc")
    connector.insert_text("d1", text="Hi", index=1)
    connector.replace_text("d1", find="old", replace="new", match_case=True)
    connector.delete_content_range("d1", start_index=1, end_index=5)
    connector.batch_update(
        "d1",
        [{"insertText": {"location": {"index": 1}, "text": "x"}}],
        write_control={"requiredRevisionId": "r"},
    )
    assert transport.requests[1].json_body == {"title": "New doc"}
    replace_request = transport.requests[3].json_body["requests"][0]
    assert replace_request["replaceAllText"]["containsText"]["text"] == "old"
    with pytest.raises(ValueError):
        connector.get_document("")
    with pytest.raises(ValueError):
        connector.create_document("")
    with pytest.raises(ValueError):
        connector.batch_update("d1", [])
    with pytest.raises(ValueError):
        connector.insert_text("d1", text="")
    with pytest.raises(ValueError):
        connector.replace_text("d1", find="", replace="x")
    with pytest.raises(ValueError):
        connector.delete_content_range("d1", start_index=5, end_index=5)


def _sheets() -> tuple[GoogleSheetsToolSet, MockTransport]:
    transport = MockTransport()
    return GoogleSheetsToolSet(token="t", transport=transport), transport


def test_google_sheets() -> None:
    connector, transport = _sheets()
    for _ in range(10):
        transport.enqueue(json_response({"spreadsheetId": "s1"}))
    connector.get_spreadsheet("s1", include_grid_data=True, ranges=["A1:B2"])
    connector.create_spreadsheet(title="t")
    connector.get_values("s1", "A1:B2", value_render_option="UNFORMATTED_VALUE")
    connector.batch_get_values("s1", ["A1", "B1"])
    connector.update_values("s1", "A1:B2", values=[[1, 2]])
    connector.append_values("s1", "A1", values=[[3]])
    connector.clear_values("s1", "A1:B2")
    connector.batch_update("s1", [{"addSheet": {"properties": {"title": "x"}}}])
    connector.add_sheet("s1", title="x", row_count=10, column_count=5)
    connector.delete_sheet("s1", sheet_id=42)
    assert transport.requests[4].params == {"valueInputOption": "USER_ENTERED"}
    assert transport.requests[6].url.endswith(":clear")
    with pytest.raises(ValueError):
        connector.get_spreadsheet("")
    with pytest.raises(ValueError):
        connector.create_spreadsheet(title="")
    with pytest.raises(ValueError):
        connector.get_values("", "A1")
    with pytest.raises(ValueError):
        connector.batch_get_values("s1", [])
    with pytest.raises(ValueError):
        connector.update_values("s1", "A1", values=[[1]], value_input_option="BOGUS")
    with pytest.raises(ValueError):
        connector.append_values("", "A1", values=[[1]])
    with pytest.raises(ValueError):
        connector.clear_values("", "")
    with pytest.raises(ValueError):
        connector.batch_update("s1", [])
    with pytest.raises(ValueError):
        connector.add_sheet("s1", title="")


def _slides() -> tuple[GoogleSlidesToolSet, MockTransport]:
    transport = MockTransport()
    return GoogleSlidesToolSet(token="t", transport=transport), transport


def test_google_slides() -> None:
    connector, transport = _slides()
    for _ in range(8):
        transport.enqueue(json_response({"presentationId": "p1"}))
    connector.get_presentation("p1")
    connector.get_page("p1", "page1")
    connector.get_page_thumbnail("p1", "page1", thumbnail_size="MEDIUM", mime_type="PNG")
    connector.create_presentation("New deck")
    connector.create_slide("p1", insertion_index=0, layout="BLANK", object_id="slideA")
    connector.insert_text("p1", object_id="shape1", text="hi")
    connector.replace_all_text("p1", find="old", replace="new")
    connector.delete_object("p1", "shape1")
    body = transport.requests[6].json_body
    assert body["requests"][0]["replaceAllText"]["containsText"]["text"] == "old"
    with pytest.raises(ValueError):
        connector.get_presentation("")
    with pytest.raises(ValueError):
        connector.get_page("p1", "")
    with pytest.raises(ValueError):
        connector.get_page_thumbnail("", "")
    with pytest.raises(ValueError):
        connector.create_presentation("")
    with pytest.raises(ValueError):
        connector.batch_update("p1", [])
    with pytest.raises(ValueError):
        connector.insert_text("p1", object_id="", text="x")
    with pytest.raises(ValueError):
        connector.replace_all_text("p1", find="", replace="x")
    with pytest.raises(ValueError):
        connector.delete_object("p1", "")


def _excel() -> tuple[MicrosoftExcelToolSet, MockTransport]:
    transport = MockTransport()
    return MicrosoftExcelToolSet(token="t", transport=transport), transport


def test_ms_excel() -> None:
    connector, transport = _excel()
    for _ in range(14):
        transport.enqueue(json_response({"id": "x"}))
    connector.list_worksheets("item-1")
    connector.get_worksheet("item-1", "Sheet1")
    connector.add_worksheet("item-1", name="New")
    connector.get_range("item-1", worksheet="Sheet1", address="A1:B2")
    connector.get_used_range("item-1", worksheet="Sheet1", values_only=True)
    connector.update_range(
        "item-1",
        worksheet="Sheet1",
        address="A1:B2",
        values=[[1, 2]],
        formulas=[[None, "=A1*2"]],
    )
    connector.clear_range("item-1", worksheet="Sheet1", address="A1:B2", apply_to="Contents")
    connector.list_tables("item-1", worksheet="Sheet1")
    connector.add_table("item-1", worksheet="Sheet1", address="A1:B2")
    connector.add_table_rows("item-1", table_name="T", values=[[1, 2]], index=0)
    connector.get_table_rows("item-1", "T")
    connector.delete_table("item-1", "T")
    connector.create_session("item-1")
    connector.close_session("item-1", workbook_session_id="s1")
    delete_req = next(r for r in transport.requests if r.method == "DELETE")
    assert "/tables/T" in delete_req.url
    close_req = transport.requests[-1]
    assert close_req.headers["Workbook-Session-Id"] == "s1"
    with pytest.raises(ValueError):
        connector.list_worksheets("")
    with pytest.raises(ValueError):
        connector.get_worksheet("item-1", "")
    with pytest.raises(ValueError):
        connector.delete_worksheet("item-1", "")
    with pytest.raises(ValueError):
        connector.get_range("item-1", worksheet="", address="A1")
    with pytest.raises(ValueError):
        connector.update_range("item-1", worksheet="", address="A1", values=[[1]])
    with pytest.raises(ValueError):
        connector.clear_range("item-1", worksheet="S", address="A1", apply_to="Bogus")
    with pytest.raises(ValueError):
        connector.add_table("item-1", worksheet="", address="A1")
    with pytest.raises(ValueError):
        connector.add_table_rows("item-1", table_name="", values=[[1]])
    with pytest.raises(ValueError):
        connector.get_table_rows("item-1", "")
    with pytest.raises(ValueError):
        connector.delete_table("item-1", "")
    with pytest.raises(ValueError):
        connector.close_session("item-1", workbook_session_id="")


def test_ms_word() -> None:
    transport = MockTransport()
    connector = MicrosoftWordToolSet(token="t", transport=transport)
    transport.enqueue(json_response({"id": "x"}))
    transport.enqueue(text_response("docx-bytes"))
    transport.enqueue(text_response("pdf-bytes"))
    transport.enqueue(json_response({"id": "x"}))
    transport.enqueue(json_response({"id": "y"}))
    connector.get_metadata("item-1")
    connector.download_content("item-1")
    connector.convert_to("item-1", format="pdf")
    connector.replace_content("item-1", content_bytes=b"NEW")
    connector.upload_new(path="folder/new.docx", content_bytes=b"NEW")
    assert transport.requests[2].params == {"format": "pdf"}
    assert transport.requests[3].headers["Content-Type"].startswith("application/vnd.openxml")
    with pytest.raises(ValueError):
        connector.get_metadata("")
    with pytest.raises(ValueError):
        connector.download_content("")
    with pytest.raises(ValueError):
        connector.convert_to("item-1", format="bogus")
    with pytest.raises(ValueError):
        connector.replace_content("", content_bytes=b"x")
    with pytest.raises(ValueError):
        connector.replace_content("item-1", content_bytes=b"")
    with pytest.raises(ValueError):
        connector.upload_new(path="", content_bytes=b"x")
    with pytest.raises(ValueError):
        connector.upload_new(path="x", content_bytes=b"")


def test_ms_powerpoint() -> None:
    transport = MockTransport()
    connector = MicrosoftPowerPointToolSet(token="t", transport=transport)
    transport.enqueue(json_response({"id": "x"}))
    transport.enqueue(text_response("pptx-bytes"))
    transport.enqueue(text_response("pdf-bytes"))
    transport.enqueue(json_response({"value": []}))
    transport.enqueue(json_response({"id": "x"}))
    transport.enqueue(json_response({"id": "y"}))
    connector.get_metadata("item-1")
    connector.download_content("item-1")
    connector.convert_to("item-1", format="pdf")
    connector.list_thumbnails("item-1")
    connector.replace_content("item-1", content_bytes=b"NEW")
    connector.upload_new(path="folder/new.pptx", content_bytes=b"NEW")
    assert transport.requests[5].headers["Content-Type"] == MicrosoftPowerPointToolSet.PPTX_MIME
    with pytest.raises(ValueError):
        connector.convert_to("item-1", format="bogus")
    with pytest.raises(ValueError):
        connector.list_thumbnails("")


def test_google_docs_get_document_accepts_dict_input() -> None:
    connector, transport = _docs()
    transport.enqueue(json_response({"documentId": "d1"}))
    connector.get_document({"file_id": "d1", "name": "x"})
    assert "/v1/documents/d1" in transport.requests[0].url


def test_google_docs_insert_text_accepts_dict_input() -> None:
    connector, transport = _docs()
    transport.enqueue(json_response({"documentId": "d1"}))
    connector.insert_text({"file_id": "d1"}, text="hi")
    assert "/v1/documents/d1:batchUpdate" in transport.requests[0].url


def test_google_docs_delete_content_range_is_destructive() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector, _ = _docs()
    opts = get_toolify_options(connector.delete_content_range)
    assert opts is not None and opts.destructive is True


def test_google_sheets_get_spreadsheet_accepts_dict_input() -> None:
    connector, transport = _sheets()
    transport.enqueue(json_response({"spreadsheetId": "s1"}))
    connector.get_spreadsheet({"file_id": "s1"})
    assert "/v4/spreadsheets/s1" in transport.requests[0].url


def test_google_sheets_update_values_accepts_dict_input() -> None:
    connector, transport = _sheets()
    transport.enqueue(json_response({"spreadsheetId": "s1"}))
    connector.update_values({"file_id": "s1"}, "A1:B2", values=[[1, 2]])
    assert "/v4/spreadsheets/s1/values/A1:B2" in transport.requests[0].url


def test_google_sheets_destructive_markers() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector, _ = _sheets()
    clear_opts = get_toolify_options(connector.clear_values)
    delete_opts = get_toolify_options(connector.delete_sheet)
    assert clear_opts is not None and clear_opts.destructive is True
    assert delete_opts is not None and delete_opts.destructive is True


def test_google_slides_get_presentation_accepts_dict_input() -> None:
    connector, transport = _slides()
    transport.enqueue(json_response({"presentationId": "p1"}))
    connector.get_presentation({"file_id": "p1"})
    assert "/v1/presentations/p1" in transport.requests[0].url


def test_google_slides_insert_text_accepts_dict_input() -> None:
    connector, transport = _slides()
    transport.enqueue(json_response({"presentationId": "p1"}))
    connector.insert_text({"file_id": "p1"}, object_id="shape1", text="hi")
    assert "/v1/presentations/p1:batchUpdate" in transport.requests[0].url


def test_google_slides_delete_object_is_destructive() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector, _ = _slides()
    opts = get_toolify_options(connector.delete_object)
    assert opts is not None and opts.destructive is True


def test_ms_word_accepts_dict_input() -> None:
    transport = MockTransport()
    connector = MicrosoftWordToolSet(token="t", transport=transport)
    transport.enqueue(json_response({"id": "i-1"}))
    connector.get_metadata({"item_id": "i-1", "name": "x.docx"})
    assert "/me/drive/items/i-1" in transport.requests[0].url


def test_ms_excel_accepts_dict_input() -> None:
    transport = MockTransport()
    connector = MicrosoftExcelToolSet(token="t", transport=transport)
    transport.enqueue(json_response({"value": []}))
    connector.list_worksheets({"item_id": "i-1"})
    assert "/me/drive/items/i-1/workbook/worksheets" in transport.requests[0].url


def test_ms_excel_destructive_markers() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    transport = MockTransport()
    connector = MicrosoftExcelToolSet(token="t", transport=transport)
    delete_ws = get_toolify_options(connector.delete_worksheet)
    clear_range = get_toolify_options(connector.clear_range)
    delete_table = get_toolify_options(connector.delete_table)
    assert delete_ws is not None and delete_ws.destructive is True
    assert clear_range is not None and clear_range.destructive is True
    assert delete_table is not None and delete_table.destructive is True


def test_ms_powerpoint_accepts_dict_input() -> None:
    transport = MockTransport()
    connector = MicrosoftPowerPointToolSet(token="t", transport=transport)
    transport.enqueue(json_response({"id": "i-1"}))
    connector.get_metadata({"item_id": "i-1", "name": "x.pptx"})
    assert "/me/drive/items/i-1" in transport.requests[0].url
