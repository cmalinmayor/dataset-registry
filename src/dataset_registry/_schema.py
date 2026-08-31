from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Axis(BaseModel):
    """One axis of a pixel array.

    Adapted from GEFF's ``Axis`` (https://liveimagetrackingtools.org/geff/latest/reference/geff_spec/#geff_spec.Axis)
    and trimmed for pixel data: no ``min``/``max`` (GEFF caches those because
    a graph's spatial extent needs a full node scan to compute; a pixel
    array's extent is just ``shape * scale``, nothing to cache). No
    ``scaled_unit``/``offset`` (GEFF needs those to disambiguate whether a
    scale is already applied to graph coordinates; a pixel array's
    convention is unambiguous -- indices are always in pixel units, and
    ``scale`` always converts to physical units, never pre-applied).
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    """Axis name, e.g. ``"z"``, ``"y"``, ``"x"``, ``"t"``, ``"c"``."""

    type: Literal["space", "time", "channel"] | None = None
    """What kind of data this axis indexes, if known."""

    unit: str | None = None
    """Physical unit of `scale`, e.g. ``"micrometer"``, ``"second"``."""

    scale: float | None = None
    """Physical size of one pixel/step along this axis, in `unit`."""


class RegistryInfo(BaseModel):
    """Registry-level settings, read from an optional `registry.toml` at the registry root.

    Entirely optional: a registry with no `registry.toml` still works with
    every other function in this package -- see `load_registry_info`'s
    fallback behavior.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    """Human-readable display title, e.g. for the `browse` UI. Falls back to
    a title derived from the registry root's directory name when unset."""


class Specimen(BaseModel):
    """The imaged subject, shared across all its representations.

    `default_axes` / `default_acquisition_date` are explicitly fallback
    defaults, not intrinsic specimen facts: a specimen imaged over multiple
    rounds (e.g. a multi-round FISH sample) may have representations with
    entirely different axes or acquisition dates. A representation only
    inherits these when it doesn't specify its own -- see
    `load_representation`.
    """

    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    """Stable identity, immutable once set -- unaffected by renaming `name`.

    `None` on disk means this specimen predates stable IDs: its directory
    name under `registry_root` doubles as its `id` until it's renamed for
    the first time, at which point `id` is written explicitly. See
    `load_specimen` for how this default is resolved, and `rename_specimen`
    for how it's backfilled.
    """

    name: str
    """Display name. Free to differ from the specimen's directory name once
    `id` is set explicitly; must match the directory name while `id` is
    still unset (the legacy convention), checked by `load_specimen`."""

    description: str | None = None
    default_axes: list[Axis] | None = None
    default_acquisition_date: date | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class _RepresentationBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    """Stable identity, immutable once set -- unaffected by renaming `name`.

    `None` on disk means this representation predates stable IDs: its
    filename (minus `.toml`) doubles as its `id` until it's renamed for the
    first time. Same convention as `Specimen.id`; see `load_representation`.
    """

    name: str | None = None
    """Display name. `None` on disk means this representation predates
    stable IDs: its filename (minus `.toml`) doubles as its `name`, same as
    today's convention, until it's renamed via `rename_representation`."""

    path: str
    """Filesystem path to this representation's data."""

    depends_on: list[str] | None = None
    """Other representations this one was produced from, each a
    ``"<specimen id>.<representation id>"`` reference. See
    `resolve_dependency`. IDs, not display names -- stable across renames.
    """

    acquisition_date: date | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImageRepresentation(_RepresentationBase):
    """A pixel image: raw acquisition, or a hand-processed variant of one.

    Both raw and processed images share this same `kind` -- what
    distinguishes them is `depends_on` (a processed image points back at the
    raw one it was produced from; raw data has no `depends_on`), not a
    separate `kind` value.
    """

    kind: Literal["image"] = "image"
    axes: list[Axis]
    """Required: a pixel array can't be loaded or displayed without knowing
    what its axes mean."""

    channels: dict[int, str] | None = None
    """Channel index -> label, e.g. ``{1: "nuclear"}``."""


class SegmentationRepresentation(_RepresentationBase):
    """A label image, typically promoted from an experimental run's output.

    See CONTRIBUTING.md / project scratch notes on "promotion": this
    registry only ever records a *deliberately promoted* segmentation (a
    human decided "this one is the current best"), never a live pointer
    into an experiment-tracking system's run directory.
    """

    kind: Literal["segmentation"] = "segmentation"
    axes: list[Axis]
    """Required, same reasoning as `ImageRepresentation.axes`."""


Representation = Annotated[
    ImageRepresentation | SegmentationRepresentation, Field(discriminator="kind")
]
