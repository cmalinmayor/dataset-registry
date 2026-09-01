"""Typed metadata models for the pharynx_cell_id registry's `[metadata]` conventions.

Standalone for now (see CONTRIBUTING.md); intended to move into its own
package once the pharynx registry has its own repo.
"""

from ._metadata import (
    PharynxRepresentationMetadata,
    PharynxSpecimenMetadata,
    representation_metadata,
    specimen_metadata,
)

__all__ = [
    "PharynxRepresentationMetadata",
    "PharynxSpecimenMetadata",
    "representation_metadata",
    "specimen_metadata",
]
