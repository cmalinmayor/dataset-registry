from typing import TYPE_CHECKING, Any

from dataset_registry._registry import Registry

if TYPE_CHECKING:
    from collections.abc import Callable

    import pandas
    import panel

_SAMPLE_LEADING_COLUMNS = ("name", "id")
_REPRESENTATION_LEADING_COLUMNS = ("sample", "representation")
_ACCENT_COLOR = "#8B3FE0"
_SAMPLE_ROUTE = "sample"
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


def _sample_row(registry: Registry, sample_id: str) -> dict[str, Any]:
    sample = registry.load_sample(sample_id)
    return {
        "name": sample.name,
        "id": sample.id,
        "description": sample.description,
        "n_representations": len(registry.list_representations(sample_id)),
        **sample.metadata,
    }


def _depends_on_names(registry: Registry, sample_id: str, depends_on: list[str]) -> str:
    names = [registry.load_representation(sample_id, dep_id).name for dep_id in depends_on]
    return ", ".join(names)


def _representation_row(
    registry: Registry, sample_id: str, representation_id: str
) -> dict[str, Any]:
    sample = registry.load_sample(sample_id)
    representation = registry.load_representation(sample_id, representation_id)
    return {
        "sample": sample.name,
        "representation": representation.name,
        "sample_id": sample_id,
        "id": representation.id,
        "path": representation.path,
        "depends_on": _depends_on_names(registry, sample_id, representation.depends_on or []),
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


def _registry_title(registry: Registry) -> str:
    """A human-readable title for a registry.

    Uses `registry.toml`'s `title` field when set; otherwise falls back to
    a title derived from the registry root's directory name (which mangles
    acronyms, e.g. "SEM-tracking" -> "Sem Tracking" -- set `title` in
    `registry.toml` to avoid that).
    """
    title = registry.load_registry_info().title
    if title is not None:
        return title
    return registry.path.name.replace("-", " ").replace("_", " ").title()


def _page(subtitle: str, registry: Registry, *body: Any) -> "panel.template.FastListTemplate":
    import panel

    title = f"{_registry_title(registry)} Data Registry: {subtitle}"
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


def _samples_page(registry: Registry, sample_ids: list[str]) -> "panel.template.FastListTemplate":
    import panel

    rows = [_sample_row(registry, sample_id) for sample_id in sample_ids]
    table = _table(_dataframe(rows, _SAMPLE_LEADING_COLUMNS))

    def _on_click(event: Any) -> None:
        sample_id = table.value.iloc[event.row]["id"]
        panel.state.location.pathname = f"/{_SAMPLE_ROUTE}-{sample_id}"
        panel.state.location.reload = True

    table.on_click(_on_click)

    return _page("Samples", registry, table)


def _sample_view(registry: Registry, sample_id: str) -> "panel.Column":
    """The read-only rendering of a sample's fields: plain text, no form widgets."""
    import panel

    sample = registry.load_sample(sample_id)

    lines = [
        f"**Name:** {sample.name}",
        f"**Description:** {sample.description or '*unset*'}",
    ]
    lines.append("**Metadata**")
    metadata_lines = [f"- **{k}:** {v}" for k, v in sample.metadata.items()]
    lines.extend(metadata_lines or ["*No metadata.*"])

    return panel.Column(
        panel.pane.Markdown("\n\n".join(lines), margin=(5, 10)),
        sizing_mode="stretch_width",
    )


def _sample_edit_form(
    registry: Registry,
    sample_id: str,
    on_saved: "Callable[[], None]",
    on_cancelled: "Callable[[], None]",
) -> "panel.Column":
    """The editable form for a sample's fields, with Save/Cancel."""
    import panel

    sample = registry.load_sample(sample_id)

    name_input = panel.widgets.TextInput(
        name="Name", value=sample.name, sizing_mode="stretch_width"
    )

    description_input = panel.widgets.TextAreaInput(
        name="Description",
        value=sample.description or "",
        placeholder="Add a description for this sample...",
        sizing_mode="stretch_width",
        auto_grow=True,
        rows=2,
        max_rows=8,
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

    for key, value in sample.metadata.items():
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
        if name_input.value != sample.name:
            registry.rename_sample(sample_id, name_input.value)
        registry.set_sample_fields(
            sample_id,
            description=description_input.value or None,
            metadata=metadata,
        )
        on_saved()

    save_button.on_click(_on_save)
    cancel_button.on_click(lambda event: on_cancelled())

    return panel.Column(
        name_input,
        description_input,
        panel.pane.Markdown("**Metadata**", margin=(10, 10, 0, 10)),
        metadata_rows,
        add_row_button,
        panel.Row(save_button, cancel_button, status),
        sizing_mode="stretch_width",
    )


def _representations_table(registry: Registry, sample_ids: list[str]) -> "panel.widgets.Tabulator":
    """A representations table whose rows navigate to that representation's detail page on click."""
    import panel

    rows = [
        _representation_row(registry, sample_id, representation_id)
        for sample_id in sample_ids
        for representation_id in registry.list_representations(sample_id)
    ]
    table = _table(
        _dataframe(rows, _REPRESENTATION_LEADING_COLUMNS),
        hidden_columns=("sample_id", "id"),
    )

    def _on_click(event: Any) -> None:
        row = table.value.iloc[event.row]
        panel.state.location.pathname = f"/{_REPRESENTATION_ROUTE}-{row['sample_id']}-{row['id']}"
        panel.state.location.reload = True

    table.on_click(_on_click)

    return table


def _sample_page(registry: Registry, sample_id: str) -> "panel.template.FastListTemplate":
    import panel

    edit_button = panel.widgets.Button(
        name="Edit", button_type="primary", width=100, margin=(5, 10)
    )
    content = panel.Column(
        _sample_view(registry, sample_id), sizing_mode="stretch_width", max_width=700
    )

    def _show_view() -> None:
        content[:] = [_sample_view(registry, sample_id)]
        edit_button.visible = True

    def _show_edit(event: Any) -> None:
        edit_button.visible = False
        content[:] = [
            _sample_edit_form(registry, sample_id, on_saved=_show_view, on_cancelled=_show_view)
        ]

    edit_button.on_click(_show_edit)

    form = panel.Column(panel.Row(edit_button), content, sizing_mode="stretch_width", max_width=700)
    nav = _nav_bar(left=("all samples", "samples"), right=None)
    representations_heading = panel.pane.Markdown("## Representations", margin=(15, 10, 0, 10))
    representations_table = _representations_table(registry, [sample_id])
    sample = registry.load_sample(sample_id)
    return _page(sample.name, registry, form, nav, representations_heading, representations_table)


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
    registry: Registry, sample_id: str, representation_id: str
) -> "panel.Column":
    """The read-only rendering of a representation's fields: plain text, no form widgets."""
    import panel

    representation = registry.load_representation(sample_id, representation_id)
    depends_on = _depends_on_names(registry, sample_id, representation.depends_on or [])

    lines = [
        f"**Name:** {representation.name}",
        f"**Path:** {representation.path}",
        f"**Depends on:** {depends_on or '*none*'}",
    ]
    lines.append("**Metadata**")
    metadata_lines = [f"- **{k}:** {v}" for k, v in representation.metadata.items()]
    lines.extend(metadata_lines or ["*No metadata.*"])

    return panel.Column(
        panel.pane.Markdown("\n\n".join(lines), margin=(5, 10)),
        sizing_mode="stretch_width",
    )


def _representation_edit_form(
    registry: Registry,
    sample_id: str,
    representation_id: str,
    on_saved: "Callable[[], None]",
    on_cancelled: "Callable[[], None]",
) -> "panel.Column":
    """The editable form for a representation's fields, with Save/Cancel.

    Only `name`, `path`, and `metadata` are editable -- `depends_on` is
    structural and left read-only here, same spirit as the sample form
    leaving structural fields untouched.
    """
    import panel

    representation = registry.load_representation(sample_id, representation_id)

    name_input = panel.widgets.TextInput(
        name="Name", value=representation.name, sizing_mode="stretch_width"
    )
    path_input = panel.widgets.TextInput(
        name="Path", value=representation.path, sizing_mode="stretch_width"
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
            registry.rename_representation(sample_id, representation_id, name_input.value)
        registry.set_representation_fields(
            sample_id,
            representation_id,
            path=path_input.value,
            metadata=metadata,
        )
        on_saved()

    save_button.on_click(_on_save)
    cancel_button.on_click(lambda event: on_cancelled())

    return panel.Column(
        name_input,
        path_input,
        panel.pane.Markdown("**Metadata**", margin=(10, 10, 0, 10)),
        metadata_rows,
        add_row_button,
        panel.Row(save_button, cancel_button, status),
        sizing_mode="stretch_width",
    )


def _representation_page(
    registry: Registry, sample_id: str, representation_id: str
) -> "panel.template.FastListTemplate":
    import panel

    edit_button = panel.widgets.Button(
        name="Edit", button_type="primary", width=100, margin=(5, 10)
    )
    content = panel.Column(
        _representation_view(registry, sample_id, representation_id),
        sizing_mode="stretch_width",
        max_width=700,
    )

    def _show_view() -> None:
        content[:] = [_representation_view(registry, sample_id, representation_id)]
        edit_button.visible = True

    def _show_edit(event: Any) -> None:
        edit_button.visible = False
        content[:] = [
            _representation_edit_form(
                registry,
                sample_id,
                representation_id,
                on_saved=_show_view,
                on_cancelled=_show_view,
            )
        ]

    edit_button.on_click(_show_edit)

    form = panel.Column(panel.Row(edit_button), content, sizing_mode="stretch_width", max_width=700)
    sample = registry.load_sample(sample_id)
    nav = _nav_bar(left=(sample.name, f"{_SAMPLE_ROUTE}-{sample_id}"), right=None)
    representation = registry.load_representation(sample_id, representation_id)
    subtitle = f"{sample.name} / {representation.name}"
    return _page(subtitle, registry, form, nav)


def browse(registry: Registry) -> dict[str, "panel.template.FastListTemplate"]:
    """A live, sortable/filterable view of every sample and representation in a registry.

    One page listing every sample; one detail page per sample (with an
    editable name/description, saved back to its `sample.toml`, and an
    embedded table of its representations); and one detail page per
    representation (with an editable name/path/metadata, saved back to its
    own TOML). Clicking a sample's name on the samples page navigates to
    that sample's detail page; clicking a representation's name on a
    sample's embedded table navigates to that representation's detail page.

    Each sample gets its own static route (`/sample-<id>`), and each
    representation its own (`/representation-<sample id>-<representation
    id>`), keyed by stable ids rather than display names so a route keeps
    working after a rename. Static routes (rather than a query-string
    parameter) are used because Bokeh's `session_args` truncates query
    values to a short fixed length -- too short for some ids -- while path
    segments aren't truncated.

    Requires the `browse` extra (`pandas`, `panel`).

    Args:
        registry: The registry to browse.

    Returns:
        A mapping of route -> servable Panel template, suitable for
        `panel.serve(browse(registry))`.

    Raises:
        ValueError: If `registry` has no samples in it -- serving an empty
            table would just look like a blank/broken page.
    """
    import panel

    panel.extension("tabulator", raw_css=[_COMPACT_CSS])

    sample_ids = registry.list_samples()
    if not sample_ids:
        raise ValueError(f"No samples found under {registry.path}.")

    pages: dict[str, Any] = {
        "samples": lambda: _samples_page(registry, sample_ids),
    }
    for sample_id in sample_ids:
        pages[f"{_SAMPLE_ROUTE}-{sample_id}"] = lambda sample_id=sample_id: _sample_page(
            registry, sample_id
        )
        for representation_id in registry.list_representations(sample_id):
            route = f"{_REPRESENTATION_ROUTE}-{sample_id}-{representation_id}"
            pages[route] = lambda sample_id=sample_id, representation_id=representation_id: (
                _representation_page(registry, sample_id, representation_id)
            )
    return pages
