# pyright: strict
"""Input schemas published by the backend registration branch.

``register_connector`` has two branches. Hosts implementing ``add_toolset`` get
the SDK's own tool metadata; hosts implementing ``add_toolset_backend`` get
``toolset_contract_specs``, whose JSON schemas are derived here in
``maivn_tools.core.backends``. Nothing in this package asserted the second
branch's ``input_schema`` before this file existed, and the derivation matched
annotation *objects* while every connector module carries
``from __future__ import annotations`` -- so ``inspect.signature`` handed it
strings, every lookup missed, and all 5945 parameters across the 175 exported
toolsets published a schema with no type in it.

These tests cover the whole defect class -- string annotations, forward
references, optionals, unions and containers -- and then pin the two branches to
each other, because two independent derivations of the same thing drift exactly
where nothing compares them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from maivn import Agent, depends_on_tool, toolify, toolset
from maivn_contracts.tools import MCPToolSpec
from pydantic import BaseModel

from maivn_tools.connectors.files.local import LocalFilesToolSet
from maivn_tools.connectors.github import GitHubToolSet
from maivn_tools.connectors.slack import SlackToolSet
from maivn_tools.core import (
    AuthMode,
    ProviderCapability,
    ProviderMetadata,
    public_tool_members,
    toolset_contract_specs,
)

if TYPE_CHECKING:
    from pathlib import Path

# A schema says something about its instance only if it carries one of these.
# Anything else -- notably the old ``{'description': <parameter name>}`` -- is a
# schema that accepts every JSON value there is.
TYPE_DECLARING_KEYS = ('type', 'anyOf', 'oneOf', 'allOf', '$ref', 'enum', 'const')


@toolset(prefix='schema')
class AnnotationToolSet:
    """Every annotation shape a connector can put on a tool parameter."""

    metadata = ProviderMetadata(
        name='openai',
        display_name='Annotation Fixture',
        version='0.1.0',
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ}),
    )

    @toolify
    def search(  # noqa: PLR0913 - the breadth is the fixture: one tool, every shape.
        self,
        query: str,
        limit: int = 10,
        ratio: float = 1.0,
        verbose: bool = False,
        tags: list[str] | None = None,
        headers: dict[str, str] | None = None,
        window: tuple[int, int] = (0, 10),
        where: SearchFilter | None = None,
        anything: Any = None,
    ) -> dict[str, Any]:
        """Search everything."""
        return {}

    @toolify
    @depends_on_tool('helper', 'helper_result')
    def summarise(self, query: str, helper_result: str = '') -> dict[str, Any]:
        """Summarise what another tool already produced."""
        return {}


class SearchFilter(BaseModel):
    """Declared after the toolset, so its annotation is a real forward reference."""

    since: str
    limit: int = 5


def _backend_input_schemas(connector: object) -> dict[str, dict[str, Any]]:
    """Return ``tool name -> input schema`` from the ``add_toolset_backend`` branch."""
    return {member.tool_name: member.input_schema for member in public_tool_members(connector)}


def _sdk_input_schemas(connector: Any) -> dict[str, dict[str, Any]]:
    """Return ``tool name -> input schema`` from the SDK's live ``add_toolset`` builder."""
    agent = Agent(name='schema-agreement', api_key='key')
    return {tool.name: tool.input_schema for tool in agent.add_toolset(connector)}


def _declares_a_type(schema: dict[str, Any]) -> bool:
    return any(key in schema for key in TYPE_DECLARING_KEYS)


def _untyped_parameters(schemas: dict[str, dict[str, Any]]) -> set[str]:
    """Return ``tool.parameter`` for every published parameter with no type."""
    untyped: set[str] = set()
    for tool_name, schema in schemas.items():
        properties = cast('dict[str, dict[str, Any]]', schema.get('properties', {}))
        for parameter_name, parameter_schema in properties.items():
            if not _declares_a_type(parameter_schema):
                untyped.add(f'{tool_name}.{parameter_name}')
    return untyped


def _search_properties() -> dict[str, dict[str, Any]]:
    schema = _backend_input_schemas(AnnotationToolSet())['SCHEMA_search']
    return cast('dict[str, dict[str, Any]]', schema['properties'])


def test_string_annotations_publish_scalar_types() -> None:
    properties = _search_properties()

    assert properties['query'] == {'type': 'string'}
    assert properties['limit'] == {'type': 'integer'}
    assert properties['ratio'] == {'type': 'number'}
    assert properties['verbose'] == {'type': 'boolean'}


def test_optional_container_annotations_publish_both_union_members() -> None:
    properties = _search_properties()

    assert properties['tags'] == {
        'anyOf': [{'items': {'type': 'string'}, 'type': 'array'}, {'type': 'null'}]
    }
    assert properties['headers'] == {
        'anyOf': [
            {'additionalProperties': {'type': 'string'}, 'type': 'object'},
            {'type': 'null'},
        ]
    }


def test_fixed_length_tuple_annotation_publishes_a_bounded_array() -> None:
    window = _search_properties()['window']

    assert window['type'] == 'array'
    assert window['prefixItems'] == [{'type': 'integer'}, {'type': 'integer'}]
    assert window['minItems'] == 2
    assert window['maxItems'] == 2


def test_forward_reference_annotation_resolves_to_the_model_schema() -> None:
    where = _search_properties()['where']

    assert where['anyOf'] == [{'$ref': '#/$defs/SearchFilter'}, {'type': 'null'}]
    assert '$defs' not in where
    root = _backend_input_schemas(AnnotationToolSet())['SCHEMA_search']
    definition = cast('dict[str, Any]', root['$defs']['SearchFilter'])
    assert definition['properties']['since'] == {'title': 'Since', 'type': 'string'}
    assert definition['required'] == ['since']


def test_any_annotation_publishes_an_unconstrained_schema() -> None:
    # `Any` genuinely constrains nothing, so the empty schema is the correct
    # answer rather than a residual miss. 552 connector parameters are annotated
    # this way on purpose (see the WS-F9 report); both branches must agree that
    # they are unconstrained rather than one of them inventing a type.
    assert _search_properties()['anything'] == {}


def test_required_parameters_survive_the_typed_derivation() -> None:
    schema = _backend_input_schemas(AnnotationToolSet())['SCHEMA_search']

    assert schema['type'] == 'object'
    assert schema['additionalProperties'] is False
    assert schema['required'] == ['query']


def test_dependency_arguments_are_not_published_to_the_model() -> None:
    # A dependency argument is filled from outside the model. Publishing it asks
    # the model to invent a value only the host can supply.
    schema = _backend_input_schemas(AnnotationToolSet())['SCHEMA_summarise']

    assert set(cast('dict[str, Any]', schema['properties'])) == {'query'}


def test_backend_branch_matches_the_sdk_builder_for_every_annotation_shape() -> None:
    connector = AnnotationToolSet()

    assert _backend_input_schemas(connector) == _sdk_input_schemas(AnnotationToolSet())


def test_github_connector_parameters_publish_their_types() -> None:
    schemas = _backend_input_schemas(GitHubToolSet(token='token'))
    properties = cast('dict[str, dict[str, Any]]', schemas['GITHUB_list_issues']['properties'])

    assert properties['per_page'] == {'type': 'integer'}
    assert properties['state'] == {'type': 'string'}
    assert properties['include_ids'] == {'type': 'boolean'}
    assert properties['repo'] == {'anyOf': [{'type': 'string'}, {'type': 'null'}]}


def test_github_connector_leaves_untyped_only_what_the_sdk_leaves_untyped() -> None:
    backend_schemas = _backend_input_schemas(GitHubToolSet(token='token'))
    sdk_schemas = _sdk_input_schemas(GitHubToolSet(token='token'))

    assert _untyped_parameters(backend_schemas) == _untyped_parameters(sdk_schemas)


def test_backend_branch_matches_the_sdk_builder_across_the_github_connector() -> None:
    backend_schemas = _backend_input_schemas(GitHubToolSet(token='token'))
    sdk_schemas = _sdk_input_schemas(GitHubToolSet(token='token'))

    assert set(backend_schemas) == set(sdk_schemas)
    assert backend_schemas == sdk_schemas


def test_slack_channel_input_publishes_all_three_accepted_shapes() -> None:
    # `channel` accepts a name, a channel object from list_channels, or a list of
    # either. Under the old derivation the model was told none of that; the whole
    # union collapsed to `{'description': 'channel'}`.
    schemas = _backend_input_schemas(SlackToolSet(token='token'))
    properties = cast('dict[str, dict[str, Any]]', schemas['SLACK_channel_history']['properties'])
    variants = cast('list[dict[str, Any]]', properties['channel']['anyOf'])

    assert [variant.get('type') for variant in variants] == ['string', 'object', 'array']
    assert variants[0]['minLength'] == 1
    object_variant_keys = cast('dict[str, Any]', variants[1]['properties'])
    assert set(object_variant_keys) == {'channel', 'channel_id', 'id', 'name'}
    assert properties['limit'] == {'type': 'integer'}


def test_backend_branch_matches_the_sdk_builder_across_the_slack_connector() -> None:
    assert _backend_input_schemas(SlackToolSet(token='token')) == _sdk_input_schemas(
        SlackToolSet(token='token')
    )


def test_backend_branch_matches_the_sdk_builder_across_the_local_files_connector(
    tmp_path: Path,
) -> None:
    assert _backend_input_schemas(LocalFilesToolSet(root=tmp_path)) == _sdk_input_schemas(
        LocalFilesToolSet(root=tmp_path)
    )


def test_contract_specs_carry_the_typed_input_schema() -> None:
    # The schemas are not an internal detail: they are the `input_schema` field
    # of the contract specs a host publishes to models.
    registration = toolset_contract_specs(GitHubToolSet(token='token'))
    specs = {spec.tool_name: spec for spec in registration.specs if isinstance(spec, MCPToolSpec)}
    properties = cast(
        'dict[str, dict[str, Any]]', specs['GITHUB_list_issues'].input_schema['properties']
    )

    assert properties['owner'] == {'type': 'string'}
    assert properties['per_page'] == {'type': 'integer'}
