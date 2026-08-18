"""Registry for imaging dataset metadata and provenance."""

from importlib.metadata import PackageNotFoundError, version

from ._example import greet

try:
    __version__ = version("dataset-registry")
except PackageNotFoundError:  # package is not installed
    __version__ = "uninstalled"

# Everything listed here becomes the public API and gets an API docs page.
# Implementation lives in underscore-prefixed modules; see CONTRIBUTING.md.
__all__ = ["__version__", "greet"]
