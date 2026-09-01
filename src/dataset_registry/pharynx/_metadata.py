from pydantic import BaseModel, ConfigDict

from dataset_registry._schema import Representation, Specimen


class PharynxSpecimenMetadata(BaseModel):
    """The pharynx registry's specimen-level `metadata` fields, typed.

    Parses ``Specimen.metadata`` (a free-form dict) into a validated shape,
    without changing how specimens are stored -- every field here is still
    just a key inside `specimen.toml`'s ``[metadata]`` table.
    """

    model_config = ConfigDict(extra="forbid")

    strain: str | None = None
    """The imaged strain's genotype/cross, e.g. ``"SLS267xOH15257"``."""


class PharynxRepresentationMetadata(BaseModel):
    """The pharynx registry's representation-level `metadata` fields, typed.

    Parses ``Representation.metadata`` (a free-form dict) into a validated
    shape. A single-timepoint representation (e.g. one promoted frame from
    a longer acquisition) is just the `num_timepoints=1` case of the same
    per-timepoint-file-series fields -- there's no separate `timepoint`
    field for it.
    """

    model_config = ConfigDict(extra="forbid")

    timepoint_pattern: str | None = None
    """Filename pattern for the timepoint file series, with ``{n}`` where
    the timepoint index appears, e.g. ``"t{n}.tif"``, ``"Decon_reg_{n}.tif"``.
    Still templated even when `num_timepoints` is `1` -- a single-timepoint
    representation is just the one-file case of this same pattern, kept
    generic in case more timepoints are added later."""

    start_timepoint: int | None = None
    """The first (and, when `num_timepoints` is `1`, only) timepoint index
    present under `timepoint_pattern`, when it isn't the conventional `0`/`1`
    index -- e.g. a representation that's a crop starting partway through a
    longer acquisition. Unset means the series starts at the conventional
    `0`/`1` index."""

    num_timepoints: int | None = None
    """How many timepoints `timepoint_pattern` expands to, starting from
    `start_timepoint` (or the conventional `0`/`1` index when unset). `1`
    for a representation holding a single timepoint."""

    channel_label: str | None = None
    """A single-channel representation's channel label, e.g. ``"nuclear"``.
    For a multi-channel representation, use `ImageRepresentation.channels`
    instead."""


def specimen_metadata(specimen: Specimen) -> PharynxSpecimenMetadata:
    """Parse a loaded `Specimen`'s `metadata` dict into `PharynxSpecimenMetadata`.

    Args:
        specimen: A specimen loaded via `dataset_registry.load_specimen`.

    Returns:
        The specimen's metadata, validated against the pharynx registry's
        specimen-level metadata fields.
    """
    metadata: PharynxSpecimenMetadata = PharynxSpecimenMetadata.model_validate(specimen.metadata)
    return metadata


def representation_metadata(representation: Representation) -> PharynxRepresentationMetadata:
    """Parse a loaded `Representation`'s `metadata` dict into `PharynxRepresentationMetadata`.

    Args:
        representation: A representation loaded via
            `dataset_registry.load_representation`.

    Returns:
        The representation's metadata, validated against the pharynx
        registry's representation-level metadata fields.
    """
    metadata: PharynxRepresentationMetadata = PharynxRepresentationMetadata.model_validate(
        representation.metadata
    )
    return metadata
