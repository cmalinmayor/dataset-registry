from pathlib import Path
from typing import TYPE_CHECKING, Any

from dataset_registry._registry import (
    list_representations,
    list_specimens,
    load_registry_info,
    load_representation,
    load_specimen,
    rename_representation,
    rename_specimen,
    resolve_dependency,
    set_representation_fields,
    set_specimen_fields,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    import pandas
    import panel

_SPECIMEN_LEADING_COLUMNS = ("name", "id")
_REPRESENTATION_LEADING_COLUMNS = ("specimen", "representation")
_ACCENT_COLOR = "#8B3FE0"
_SPECIMEN_ROUTE = "specimen"
_REPRESENTATION_ROUTE = "representation"

# Panel's default widget/card spacing is generous enough that a handful of
# fields need scrolling to see at once; this tightens margins and bumps the
# base font size a bit for a denser, more legible page.
_COMPACT_CSS = """
body, p, div, span, input, textarea, button, label, .markdown, .bk-clearfix {
    font-size: 15px !important;
}
.bk-panel-models-layout-Column, .bk-panel-models-layout-Row { gap: 4px; }
.card-margin { margin: 6px !important; padding: 10px !important; }
"""


def _specimen_row(registry_root: Path, specimen_id: str) -> dict[str, Any]:
    specimen = load_specimen(registry_root, specimen_id)
    return {
        "name": specimen.name,
        "id": specimen.id,
        "description": specimen.description,
        "default_acquisition_date": specimen.default_acquisition_date,
        "n_representations": len(list_representations(registry_root, specimen_id)),
        **specimen.metadata,
    }


def _depends_on_names(registry_root: Path, specimen_id: str, depends_on: list[str]) -> str:
    """The display `name` of each `depends_on` reference, not its raw id.

    A reference without a `.` is a same-specimen representation id (the only
    kind of dependency this registry format currently supports); one
    containing a `.` is the `resolve_dependency` cross-specimen form.
    """
    names: list[str] = []
    for reference in depends_on:
        if "." in reference:
            dependency = resolve_dependency(registry_root, reference)
        else:
            dependency = load_representation(registry_root, specimen_id, reference)
        assert dependency.name is not None  # always populated by load_representation
        names.append(dependency.name)
    return ", ".join(names)


def _representation_row(
    registry_root: Path, specimen_id: str, representation_id: str
) -> dict[str, Any]:
    specimen = load_specimen(registry_root, specimen_id)
    representation = load_representation(registry_root, specimen_id, representation_id)
    axes = ", ".join(a.name for a in representation.axes) if hasattr(representation, "axes") else ""
    return {
        "specimen": specimen.name,
        "representation": representation.name,
        "specimen_id": specimen_id,
        "id": representation.id,
        "kind": representation.kind,
        "path": representation.path,
        "axes": axes,
        "acquisition_date": representation.acquisition_date,
        "depends_on": _depends_on_names(
            registry_root, specimen_id, representation.depends_on or []
        ),
        **representation.metadata,
    }


def _dataframe(rows: list[dict[str, Any]], leading_columns: tuple[str, ...]) -> "pandas.DataFrame":
    import pandas as pd

    middle_columns = dict.fromkeys(key for row in rows for key in row if key not in leading_columns)
    columns = [*leading_columns, *middle_columns]
    return pd.DataFrame(rows, columns=columns)


def _table(
    df: "pandas.DataFrame", *, hidden_columns: tuple[str, ...] = ()
) -> "panel.widgets.Tabulator":
    import panel

    return panel.widgets.Tabulator(
        df,
        show_index=False,
        disabled=True,
        pagination=None,
        theme="materialize",
        sizing_mode="stretch_width",
        hidden_columns=list(hidden_columns),
    )


def _registry_title(registry_root: Path) -> str:
    """A human-readable title for a registry.

    Uses `registry.toml`'s `title` field when set; otherwise falls back to
    a title derived from the registry root's directory name (which mangles
    acronyms, e.g. "SEM-tracking" -> "Sem Tracking" -- set `title` in
    `registry.toml` to avoid that).
    """
    title = load_registry_info(registry_root).title
    if title is not None:
        return title
    return registry_root.name.replace("-", " ").replace("_", " ").title()


def _page(subtitle: str, registry_root: Path, *body: Any) -> "panel.template.FastListTemplate":
    import panel

    title = f"{_registry_title(registry_root)} Data Registry: {subtitle}"
    return panel.template.FastListTemplate(
        title=title,
        accent_base_color=_ACCENT_COLOR,
        header_background=_ACCENT_COLOR,
        main=[panel.Column(*body, margin=0)],
    )


def _nav_bar(*, left: tuple[str, str] | None, right: tuple[str, str] | None) -> "panel.Row":
    """A bottom navigation card: `left` label/link on the left, `right` on the right."""
    import panel

    left_link = panel.pane.Markdown(f"[< {left[0]}]({left[1]})" if left else "", margin=(2, 10))
    right_link = panel.pane.Markdown(f"[{right[0]} >]({right[1]})" if right else "", margin=(2, 10))
    return panel.Row(
        left_link,
        panel.HSpacer(),
        right_link,
        css_classes=["card-margin"],
        styles={"border": "1px solid #ddd", "border-radius": "6px"},
    )


def _specimens_page(
    registry_root: Path, specimen_ids: list[str]
) -> "panel.template.FastListTemplate":
    import panel

    rows = [_specimen_row(registry_root, specimen_id) for specimen_id in specimen_ids]
    table = _table(_dataframe(rows, _SPECIMEN_LEADING_COLUMNS))

    def _on_click(event: Any) -> None:
        specimen_id = table.value.iloc[event.row]["id"]
        panel.state.location.pathname = f"/{_SPECIMEN_ROUTE}-{specimen_id}"
        panel.state.location.reload = True

    table.on_click(_on_click)

    return _page("Specimens", registry_root, table)


def _specimen_view(registry_root: Path, specimen_id: str) -> "panel.Column":
    """The read-only rendering of a specimen's fields: plain text, no form widgets."""
    import panel

    specimen = load_specimen(registry_root, specimen_id)

    lines = [
        f"**Name:** {specimen.name}",
        f"**Description:** {specimen.description or '*unset*'}",
        f"**Default acquisition date:** {specimen.default_acquisition_date or '*unset*'}",
    ]
    lines.append("**Metadata**")
    metadata_lines = [f"- **{k}:** {v}" for k, v in specimen.metadata.items()]
    lines.extend(metadata_lines or ["*No metadata.*"])

    return panel.Column(
        panel.pane.Markdown("\n\n".join(lines), margin=(5, 10)),
        sizing_mode="stretch_width",
    )


def _specimen_edit_form(
    registry_root: Path,
    specimen_id: str,
    on_saved: "Callable[[], None]",
    on_cancelled: "Callable[[], None]",
) -> "panel.Column":
    """The editable form for a specimen's fields, with Save/Cancel."""
    import panel

    specimen = load_specimen(registry_root, specimen_id)

    name_input = panel.widgets.TextInput(
        name="Name", value=specimen.name, sizing_mode="stretch_width"
    )

    description_input = panel.widgets.TextAreaInput(
        name="Description",
        value=specimen.description or "",
        placeholder="Add a description for this specimen...",
        sizing_mode="stretch_width",
        auto_grow=True,
        rows=2,
        max_rows=8,
    )
    date_input = panel.widgets.DatePicker(
        name="Default acquisition date", value=specimen.default_acquisition_date, width=200
    )

    metadata_rows = panel.Column(margin=0)

    def _add_metadata_row(key: str = "", value: str = "") -> None:
        key_input = panel.widgets.TextInput(
            name="", placeholder="key", value=key, width=180, margin=(2, 5)
        )
        value_input = panel.widgets.TextInput(
            name="",
            placeholder="value",
            value=str(value),
            sizing_mode="stretch_width",
            margin=(2, 5),
        )
        remove_button = panel.widgets.Button(name="✕", width=35, margin=(2, 5))
        row = panel.Row(key_input, value_input, remove_button, margin=0)
        remove_button.on_click(lambda event: metadata_rows.remove(row))
        metadata_rows.append(row)

    for key, value in specimen.metadata.items():
        _add_metadata_row(key, value)

    add_row_button = panel.widgets.Button(name="+ Add field", width=120)
    add_row_button.on_click(lambda event: _add_metadata_row())

    save_button = panel.widgets.Button(name="Save", button_type="primary", width=100)
    cancel_button = panel.widgets.Button(name="Cancel", width=100)
    status = panel.pane.Markdown("", margin=(10, 10))

    def _on_save(event: Any) -> None:
        metadata = {}
        for row in metadata_rows:
            key_input, value_input, _remove_button = row
            key = key_input.value.strip()
            if key:
                metadata[key] = _coerce_metadata_value(value_input.value)
        if name_input.value != specimen.name:
            rename_specimen(registry_root, specimen_id, name_input.value)
        set_specimen_fields(
            registry_root,
            specimen_id,
            description=description_input.value or None,
            default_acquisition_date=date_input.value,
            metadata=metadata,
        )
        on_saved()

    save_button.on_click(_on_save)
    cancel_button.on_click(lambda event: on_cancelled())

    return panel.Column(
        name_input,
        description_input,
        date_input,
        panel.pane.Markdown("**Metadata**", margin=(10, 10, 0, 10)),
        metadata_rows,
        add_row_button,
        panel.Row(save_button, cancel_button, status),
        sizing_mode="stretch_width",
    )


def _representations_table(
    registry_root: Path, specimen_ids: list[str]
) -> "panel.widgets.Tabulator":
    """A representations table whose rows navigate to that representation's detail page on click."""
    import panel

    rows = [
        _representation_row(registry_root, specimen_id, representation_id)
        for specimen_id in specimen_ids
        for representation_id in list_representations(registry_root, specimen_id)
    ]
    table = _table(
        _dataframe(rows, _REPRESENTATION_LEADING_COLUMNS),
        hidden_columns=("specimen_id", "id"),
    )

    def _on_click(event: Any) -> None:
        row = table.value.iloc[event.row]
        panel.state.location.pathname = f"/{_REPRESENTATION_ROUTE}-{row['specimen_id']}-{row['id']}"
        panel.state.location.reload = True

    table.on_click(_on_click)

    return table


def _specimen_page(registry_root: Path, specimen_id: str) -> "panel.template.FastListTemplate":
    import panel

    edit_button = panel.widgets.Button(
        name="Edit", button_type="primary", width=100, margin=(5, 10)
    )
    content = panel.Column(
        _specimen_view(registry_root, specimen_id), sizing_mode="stretch_width", max_width=700
    )

    def _show_view() -> None:
        content[:] = [_specimen_view(registry_root, specimen_id)]
        edit_button.visible = True

    def _show_edit(event: Any) -> None:
        edit_button.visible = False
        content[:] = [
            _specimen_edit_form(
                registry_root, specimen_id, on_saved=_show_view, on_cancelled=_show_view
            )
        ]

    edit_button.on_click(_show_edit)

    form = panel.Column(panel.Row(edit_button), content, sizing_mode="stretch_width", max_width=700)
    nav = _nav_bar(left=("all specimens", "specimens"), right=None)
    representations_heading = panel.pane.Markdown("## Representations", margin=(15, 10, 0, 10))
    representations_table = _representations_table(registry_root, [specimen_id])
    specimen = load_specimen(registry_root, specimen_id)
    return _page(
        specimen.name, registry_root, form, nav, representations_heading, representations_table
    )


def _coerce_metadata_value(text: str) -> Any:
    """Parse a metadata value typed as plain text back into int/float/bool/str.

    The metadata row UI only has one text field per value (no per-field
    type picker), so a value typed as e.g. ``4`` or ``true`` should round-trip
    as an int/bool rather than becoming the string ``"4"``/``"true"`` --
    matching what hand-editing the TOML directly would produce.
    """
    if text.lower() in ("true", "false"):
        return text.lower() == "true"
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def _representation_view(
    registry_root: Path, specimen_id: str, representation_id: str
) -> "panel.Column":
    """The read-only rendering of a representation's fields: plain text, no form widgets."""
    import panel

    representation = load_representation(registry_root, specimen_id, representation_id)
    axes = (
        ", ".join(a.name for a in representation.axes) if hasattr(representation, "axes") else None
    )
    depends_on = _depends_on_names(registry_root, specimen_id, representation.depends_on or [])

    lines = [
        f"**Name:** {representation.name}",
        f"**Kind:** {representation.kind}",
        f"**Path:** {representation.path}",
        f"**Axes:** {axes or '*n/a*'}",
        f"**Depends on:** {depends_on or '*none*'}",
        f"**Acquisition date:** {representation.acquisition_date or '*unset*'}",
    ]
    lines.append("**Metadata**")
    metadata_lines = [f"- **{k}:** {v}" for k, v in representation.metadata.items()]
    lines.extend(metadata_lines or ["*No metadata.*"])

    return panel.Column(
        panel.pane.Markdown("\n\n".join(lines), margin=(5, 10)),
        sizing_mode="stretch_width",
    )


def _representation_edit_form(
    registry_root: Path,
    specimen_id: str,
    representation_id: str,
    on_saved: "Callable[[], None]",
    on_cancelled: "Callable[[], None]",
) -> "panel.Column":
    """The editable form for a representation's fields, with Save/Cancel.

    Only `name`, `path`, `acquisition_date`, and `metadata` are editable --
    `kind`, `axes`, `channels`, and `depends_on` are structural and left
    read-only here, same spirit as the specimen form leaving `default_axes`
    untouched.
    """
    import panel

    representation = load_representation(registry_root, specimen_id, representation_id)

    name_input = panel.widgets.TextInput(
        name="Name", value=representation.name or "", sizing_mode="stretch_width"
    )
    path_input = panel.widgets.TextInput(
        name="Path", value=representation.path, sizing_mode="stretch_width"
    )
    date_input = panel.widgets.DatePicker(
        name="Acquisition date", value=representation.acquisition_date, width=200
    )

    metadata_rows = panel.Column(margin=0)

    def _add_metadata_row(key: str = "", value: str = "") -> None:
        key_input = panel.widgets.TextInput(
            name="", placeholder="key", value=key, width=180, margin=(2, 5)
        )
        value_input = panel.widgets.TextInput(
            name="",
            placeholder="value",
            value=str(value),
            sizing_mode="stretch_width",
            margin=(2, 5),
        )
        remove_button = panel.widgets.Button(name="✕", width=35, margin=(2, 5))
        row = panel.Row(key_input, value_input, remove_button, margin=0)
        remove_button.on_click(lambda event: metadata_rows.remove(row))
        metadata_rows.append(row)

    for key, value in representation.metadata.items():
        _add_metadata_row(key, value)

    add_row_button = panel.widgets.Button(name="+ Add field", width=120)
    add_row_button.on_click(lambda event: _add_metadata_row())

    save_button = panel.widgets.Button(name="Save", button_type="primary", width=100)
    cancel_button = panel.widgets.Button(name="Cancel", width=100)
    status = panel.pane.Markdown("", margin=(10, 10))

    def _on_save(event: Any) -> None:
        metadata = {}
        for row in metadata_rows:
            key_input, value_input, _remove_button = row
            key = key_input.value.strip()
            if key:
                metadata[key] = _coerce_metadata_value(value_input.value)
        if name_input.value != representation.name:
            rename_representation(registry_root, specimen_id, representation_id, name_input.value)
        set_representation_fields(
            registry_root,
            specimen_id,
            representation_id,
            path=path_input.value,
            acquisition_date=date_input.value,
            metadata=metadata,
        )
        on_saved()

    save_button.on_click(_on_save)
    cancel_button.on_click(lambda event: on_cancelled())

    return panel.Column(
        name_input,
        path_input,
        date_input,
        panel.pane.Markdown("**Metadata**", margin=(10, 10, 0, 10)),
        metadata_rows,
        add_row_button,
        panel.Row(save_button, cancel_button, status),
        sizing_mode="stretch_width",
    )


def _representation_page(
    registry_root: Path, specimen_id: str, representation_id: str
) -> "panel.template.FastListTemplate":
    import panel

    edit_button = panel.widgets.Button(
        name="Edit", button_type="primary", width=100, margin=(5, 10)
    )
    content = panel.Column(
        _representation_view(registry_root, specimen_id, representation_id),
        sizing_mode="stretch_width",
        max_width=700,
    )

    def _show_view() -> None:
        content[:] = [_representation_view(registry_root, specimen_id, representation_id)]
        edit_button.visible = True

    def _show_edit(event: Any) -> None:
        edit_button.visible = False
        content[:] = [
            _representation_edit_form(
                registry_root,
                specimen_id,
                representation_id,
                on_saved=_show_view,
                on_cancelled=_show_view,
            )
        ]

    edit_button.on_click(_show_edit)

    form = panel.Column(panel.Row(edit_button), content, sizing_mode="stretch_width", max_width=700)
    specimen = load_specimen(registry_root, specimen_id)
    nav = _nav_bar(left=(specimen.name, f"{_SPECIMEN_ROUTE}-{specimen_id}"), right=None)
    representation = load_representation(registry_root, specimen_id, representation_id)
    subtitle = f"{specimen.name} / {representation.name}"
    return _page(subtitle, registry_root, form, nav)


def browse(registry_root: Path) -> dict[str, "panel.template.FastListTemplate"]:
    """A live, sortable/filterable view of every specimen and representation in a registry.

    One page listing every specimen; one detail page per specimen (with an
    editable name/description, saved back to its `specimen.toml`, and an
    embedded table of its representations); and one detail page per
    representation (with an editable name/path/acquisition date/metadata,
    saved back to its own TOML). Clicking a specimen's name on the specimens
    page navigates to that specimen's detail page; clicking a representation's
    name on a specimen's embedded table navigates to that representation's
    detail page.

    Each specimen gets its own static route (`/specimen-<id>`), and each
    representation its own (`/representation-<specimen id>-<representation
    id>`), keyed by stable ids rather than display names so a route keeps
    working after a rename. Static routes (rather than a query-string
    parameter) are used because Bokeh's `session_args` truncates query
    values to a short fixed length -- too short for some ids -- while path
    segments aren't truncated.

    Requires the `browse` extra (`pandas`, `panel`).

    Args:
        registry_root: Directory containing one subdirectory per specimen.

    Returns:
        A mapping of route -> servable Panel template, suitable for
        `panel.serve(browse(registry_root))`.

    Raises:
        ValueError: If `registry_root` has no specimens under it -- serving
            an empty table would just look like a blank/broken page.
    """
    import panel

    panel.extension("tabulator", raw_css=[_COMPACT_CSS])

    specimen_ids = list_specimens(registry_root)
    if not specimen_ids:
        raise ValueError(f"No specimens found under {registry_root}.")

    pages: dict[str, Any] = {
        "specimens": lambda: _specimens_page(registry_root, specimen_ids),
    }
    for specimen_id in specimen_ids:
        pages[f"{_SPECIMEN_ROUTE}-{specimen_id}"] = lambda specimen_id=specimen_id: _specimen_page(
            registry_root, specimen_id
        )
        for representation_id in list_representations(registry_root, specimen_id):
            route = f"{_REPRESENTATION_ROUTE}-{specimen_id}-{representation_id}"
            pages[route] = lambda specimen_id=specimen_id, representation_id=representation_id: (
                _representation_page(registry_root, specimen_id, representation_id)
            )
    return pages
