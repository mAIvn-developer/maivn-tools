"""Deterministic local document generation tools."""

from __future__ import annotations

from maivn_contracts.artifacts import GeneratedFile

from .dependencies import CompositionDependencyError, requires_composition
from .models import (
    BlockPosition,
    CompositionContent,
    CompositionReference,
    DocumentBlock,
    DocumentHandle,
    DocumentState,
    OneShotBlock,
    OneShotDocument,
)
from .toolset import DocumentsToolSet

__all__ = [
    'BlockPosition',
    'CompositionContent',
    'CompositionDependencyError',
    'CompositionReference',
    'DocumentBlock',
    'DocumentHandle',
    'DocumentState',
    'DocumentsToolSet',
    'GeneratedFile',
    'OneShotBlock',
    'OneShotDocument',
    'requires_composition',
]
