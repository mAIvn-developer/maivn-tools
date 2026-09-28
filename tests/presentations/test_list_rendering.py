"""Presentation lists retain editable native bullets and hanging indents."""

from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from maivn_tools import PresentationsToolSet


def test_list_items_have_native_bullets_without_altering_authored_text(tmp_path: Path) -> None:
    tools = PresentationsToolSet(tmp_path)
    deck = tools.create_presentation('bullets.pptx')
    tools.put_slide(deck, 'evidence', {'anchor': 'end'})
    items = ['Confirm owners', 'Verify readiness', 'Schedule the review']
    reference = tools.compose_artifact(deck, 'proofs', {'kind': 'list', 'items': items})
    tools.put_element(
        deck,
        'evidence',
        'proofs',
        {
            'type': 'list',
            'composition': reference,
            'x': 1,
            'y': 1,
            'width': 10,
            'height': 4,
        },
    )
    rendered = tools.render_presentation(deck)
    with ZipFile(rendered.path) as archive:
        root = ET.fromstring(archive.read('ppt/slides/slide1.xml'))  # noqa: S314 - locally generated.
    ns = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
    paragraphs = root.findall('.//a:p', ns)
    assert [paragraph.findtext('.//a:t', namespaces=ns) for paragraph in paragraphs] == items
    for paragraph in paragraphs:
        properties = paragraph.find('a:pPr', ns)
        assert properties is not None
        bullet = properties.find('a:buChar', ns)
        assert bullet is not None
        assert bullet.attrib['char'] == '•'
        assert int(properties.attrib['marL']) > 0
        assert int(properties.attrib['indent']) < 0
