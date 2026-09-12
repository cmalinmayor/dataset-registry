"""Registry for versioned dataset paths and metadata."""

from importlib.metadata import PackageNotFoundError, version

from ._browser import browse
from ._registry import Registry
from ._schema import RegistryInfo, Representation, Sample

try:
    __version__ = version("dataset-registry")
except PackageNotFoundError:  # package is not installed
    __version__ = "uninstalled"

# Everything listed here becomes the public API and gets an API docs page.
# Implementation lives in underscore-prefixed modules; see CONTRIBUTING.md.
__all__ = [
    "Registry",
    "RegistryInfo",
    "Representation",
    "Sample",
    "__version__",
    "browse",
]
