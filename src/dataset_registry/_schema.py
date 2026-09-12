from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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


class Sample(BaseModel):
    """A named, version-controlled entity that groups one or more representations of data."""

    model_config = ConfigDict(extra="forbid")

    id: str
    """Stable identity, immutable once set -- unaffected by renaming `name`."""

    name: str
    """Display name. Free to change without affecting `id`."""

    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    """Free-form, project-defined fields. Projects that want a validated
    shape can parse this dict into their own pydantic model without any
    change to the registry itself."""


class Representation(BaseModel):
    """A named path to a specific piece of data belonging to a `Sample`."""

    model_config = ConfigDict(extra="forbid")

    id: str
    """Stable identity, immutable once set -- unaffected by renaming `name`."""

    name: str
    """Display name. Free to change without affecting `id`."""

    path: str
    """Filesystem path to this representation's data. The whole point of
    this registry: code refers to a representation by `id`, so `path` can
    change (the data gets moved) without any change to downstream code."""

    depends_on: list[str] | None = None
    """Ids of other representations of the same sample that this one was
    produced from. IDs, not display names -- stable across renames. Load a
    dependency with ``registry.load_representation(sample_id, dependency_id)``,
    reusing this representation's own `sample_id`."""

    metadata: dict[str, Any] = Field(default_factory=dict)
    """Free-form, project-defined fields. Projects that want a validated
    shape can parse this dict into their own pydantic model without any
    change to the registry itself."""
