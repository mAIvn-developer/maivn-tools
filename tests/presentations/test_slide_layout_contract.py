"""The model-visible slide layout choices must match the renderer."""

from pathlib import Path

from maivn import Agent

from maivn_tools import PresentationsToolSet


def test_slide_layout_schema_exposes_only_the_supported_blank_layout(tmp_path: Path) -> None:
    tools = Agent(name='layout-contract', api_key='test-key').add_toolset(
        PresentationsToolSet(tmp_path),
    )
    slide = next(tool for tool in tools if tool.name == 'PRESENTATIONS_put_slide')
    schema = slide.input_schema
    assert schema is not None
    layout = schema['properties']['layout']
    assert layout.get('const') == 'blank' or layout.get('enum') == ['blank']
