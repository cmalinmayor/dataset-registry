"""Registry for imaging dataset metadata and provenance."""

from importlib.metadata import PackageNotFoundError, version

from ._clone import Registry, open_registry
from ._registry import (
    create_representation,
    create_specimen,
    generate_representation_id,
    generate_specimen_id,
    list_representations,
    list_specimens,
    load_registry_info,
    load_representation,
    load_specimen,
    rename_representation,
    rename_specimen,
    resolve_dependency,
    set_specimen_description,
    set_specimen_fields,
)
from ._schema import (
    Axis,
    ImageRepresentation,
    PointsRepresentation,
    RegistryInfo,
    Representation,
    SegmentationRepresentation,
    Specimen,
)

try:
    __version__ = version("dataset-registry")
except PackageNotFoundError:  # package is not installed
    __version__ = "uninstalled"

# Everything listed here becomes the public API and gets an API docs page.
# Implementation lives in underscore-prefixed modules; see CONTRIBUTING.md.
__all__ = [
    "Axis",
    "ImageRepresentation",
    "PointsRepresentation",
    "Registry",
    "RegistryInfo",
    "Representation",
    "SegmentationRepresentation",
    "Specimen",
    "__version__",
    "create_representation",
    "create_specimen",
    "generate_representation_id",
    "generate_specimen_id",
    "list_representations",
    "list_specimens",
    "load_registry_info",
    "load_representation",
    "load_specimen",
    "open_registry",
    "rename_representation",
    "rename_specimen",
    "resolve_dependency",
    "set_specimen_description",
    "set_specimen_fields",
]
