# pyright: strict
from __future__ import annotations

from typing import cast

import pytest
from maivn import Agent
from maivn import toolify_options as get_toolify_options

from maivn_tools.connectors.salesforce import SalesforceToolSet
from maivn_tools.testing import MockTransport, json_response


def _connector() -> tuple[SalesforceToolSet, MockTransport]:
    transport = MockTransport()
    connector = SalesforceToolSet(
        instance_url='https://acme.my.salesforce.com',
        token='at-sf',
        transport=transport,
    )
    return connector, transport


def _make_agent() -> Agent:
    return Agent(name='t', api_key='key')


@pytest.mark.parametrize(
    'path',
    [
        'https://attacker.invalid/collect',
        'http://acme.my.salesforce.com/services/data/v66.0/query/01g00',
        '//attacker.invalid/collect',
        'https://acme.my.salesforce.com@attacker.invalid/collect',
        '/services/data/v66.0/query/../../sobjects/Account',
        '/services/data/v66.0/query/%2e%2e%2fAccount',
        '/services/data/v66.0/query/01g00?redirect=https://attacker.invalid',
        '/services/data/v66.0/query/01g00#fragment',
        '/services/data/v66.0/sobjects/Account',
        '/services/data/v66.0/query/01g00\\other',
    ],
)
def test_query_more_rejects_untrusted_paths_before_sending_credentials(path: str) -> None:
    connector, transport = _connector()
    transport.enqueue(json_response({'records': []}))
    with pytest.raises(ValueError, match='query locator'):
        connector.query_more(path)
    assert not transport.requests


@pytest.mark.parametrize('endpoint', ['query', 'queryAll'])
def test_query_more_accepts_relative_salesforce_locator(endpoint: str) -> None:
    connector, transport = _connector()
    transport.enqueue(json_response({'records': [{'Id': '001'}], 'done': True}))
    path = f'/services/data/v66.0/{endpoint}/01g000000000ABC-2000'
    result = connector.query_more(path)
    assert result == {'records': [{'Id': '001'}], 'done': True}
    assert transport.requests[0].url == f'https://acme.my.salesforce.com{path}'


def test_salesforce_list_tools_register_first_class_output_schemas() -> None:
    connector, _ = _connector()
    agent = _make_agent()
    tools = agent.add_toolset(connector)

    schemas_by_name = {tool.name: tool.output_schema for tool in tools}
    # (tool name, expected array property key)
    expected: dict[str, str] = {
        'SALESFORCE_soql_query': 'records',
    }
    for name, array_key in expected.items():
        schema = schemas_by_name.get(name)
        assert isinstance(schema, dict), f'{name} missing first-class output_schema'
        properties = cast('dict[str, object]', schema['properties'])
        array_prop = cast('dict[str, object]', properties[array_key])
        assert array_prop['type'] == 'array', f'{name}.{array_key} should be an array'

    # The connector-built acknowledgement dicts are also published as
    # first-class object schemas (no array key, so checked separately).
    for name in ('SALESFORCE_update_record', 'SALESFORCE_delete_record'):
        schema = schemas_by_name.get(name)
        assert isinstance(schema, dict), f'{name} missing first-class output_schema'
        assert schema['type'] == 'object'


def test_salesforce_output_schemas_not_published_through_metadata() -> None:
    connector, _ = _connector()
    for method in (
        connector.soql_query,
        connector.update_record,
        connector.delete_record,
    ):
        opts = get_toolify_options(method)
        assert opts is not None
        assert 'output_schema' not in opts.metadata
