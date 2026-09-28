"""Model-facing presentation geometry states its units and canvas constraints."""

from pathlib import Path

import pytest
from pydantic import TypeAdapter

from maivn_tools import PresentationsToolSet
from maivn_tools.connectors.presentations.models import OneShotElement, PresentationElement


@pytest.mark.parametrize('model', [PresentationElement, OneShotElement])
def test_both_authoring_contracts_explain_geometry_units(model: type) -> None:
    properties = TypeAdapter(model).json_schema()['properties']
    for field in ('x', 'y', 'width', 'height'):
        description = properties[field].get('description', '')
        assert 'inches' in description
        assert ('13.333' if field in {'x', 'width'} else '7.5') in description
    assert 'points' in properties['font_size'].get('description', '')


def test_canvas_error_explains_units_and_does_not_place_invalid_element(tmp_path: Path) -> None:
    tools = PresentationsToolSet(tmp_path)
    deck = tools.create_presentation('units.pptx')
    tools.put_slide(deck, 'overview', {'anchor': 'end'})
    content = tools.compose_artifact(deck, 'title', {'kind': 'text', 'text': 'Overview'})
    before = tools.read_presentation(deck)
    with pytest.raises(ValueError, match=r'inches.*13\.333.*7\.5'):
        tools.put_element(
            deck,
            'overview',
            'title',
            {
                'type': 'title',
                'composition': content,
                'x': 60,
                'y': 55,
                'width': 840,
                'height': 80,
            },
        )
    assert tools.read_presentation(deck) == before
