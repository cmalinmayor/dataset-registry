"""Serve a live, sortable/filterable view of a registry's specimens and representations.

Interactive Tabulator sort/filter needs a live Python process, so this is
served, not saved to a static file. Runs its own Panel server directly
(rather than `panel serve <script>`) since it serves multiple routes
(specimens, representations) from one registry:

    uv run --extra browse python scripts/open_browser.py <registry_root>
"""

import sys
import webbrowser
from pathlib import Path

import panel

from dataset_registry.browse import browse

PORT = 5006


def main() -> None:
    registry_root = Path(sys.argv[1])
    pages = browse(registry_root)
    webbrowser.open(f"http://localhost:{PORT}/specimens")
    panel.serve(pages, port=PORT, show=False)


if __name__ == "__main__":
    main()
