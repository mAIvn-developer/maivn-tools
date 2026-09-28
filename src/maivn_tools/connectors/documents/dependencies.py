"""Fail-closed composition-reference dependencies for document tools."""

# pyright: strict

from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import wraps
from inspect import signature
from typing import ClassVar, ParamSpec, Protocol, TypeVar, cast

from maivn import toolify
from maivn import toolify_options as get_toolify_options

P = ParamSpec('P')
R = TypeVar('R')


class CompositionDependencyError(ValueError):
    """Raised when a required composition reference is absent or invalid."""

    sdk_error_code: ClassVar[str] = 'sdk_composition_reference_error'


class _CompositionReferenceResolver(Protocol):
    def validate_composition_reference(
        self,
        doc: object,
        reference: object,
        argument_name: str,
    ) -> None: ...


def requires_composition(
    arg_name: str,
    *,
    reference_key: str | None = None,
    allow_missing_for: tuple[str, ...] = (),
    upstream_tool: str = 'DOCUMENTS_compose_artifact',
    document_arg: str = 'doc',
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Require one argument (or nested key) to reference composed content.

    Apply this outside ``@toolify``. The wrapper preserves the authored
    signature and asks the owning workspace to validate the exact reference
    before invoking the method. A valid reference may come from image composition
    or a restored earlier revision, with no producer call in the current turn.
    """
    argument_path = f'{arg_name}.{reference_key}' if reference_key else arg_name

    def decorate(func: Callable[P, R]) -> Callable[P, R]:
        func_signature = signature(func)

        @wraps(func)
        def checked(*args: P.args, **kwargs: P.kwargs) -> R:
            bound = func_signature.bind(*args, **kwargs)
            owner = cast('_CompositionReferenceResolver', bound.arguments.get('self'))
            doc = bound.arguments.get(document_arg)
            candidate = bound.arguments.get(arg_name)
            if reference_key is not None:
                if not isinstance(candidate, Mapping) or reference_key not in candidate:
                    mapping = (
                        cast('Mapping[object, object]', candidate)
                        if isinstance(candidate, Mapping)
                        else None
                    )
                    if mapping is not None and mapping.get('type') in allow_missing_for:
                        return func(*args, **kwargs)
                    raise CompositionDependencyError(
                        f"argument '{argument_path}' requires a reference returned by "
                        f'{upstream_tool}'
                    )
                candidate = cast('Mapping[object, object]', candidate)[reference_key]
            owner.validate_composition_reference(doc, candidate, argument_path)
            return func(*args, **kwargs)

        options = get_toolify_options(func)
        if options is None:
            raise TypeError('requires_composition must be applied outside @toolify')
        decorated = toolify(
            name=options.name,
            description=options.description,
            permissions=options.permissions,
            destructive=options.destructive,
            always_execute=options.always_execute,
            final_tool=options.final_tool,
            metadata=options.metadata,
            tags=options.tags,
            before_execute=options.before_execute,
            after_execute=options.after_execute,
        )(checked)
        return cast('Callable[P, R]', decorated)

    return decorate
