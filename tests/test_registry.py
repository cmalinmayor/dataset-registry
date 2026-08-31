import tomllib
from pathlib import Path

import pytest
import tomli_w
from pydantic import ValidationError

from dataset_registry import (
    Axis,
    ImageRepresentation,
    SegmentationRepresentation,
    create_representation,
    create_specimen,
    generate_specimen_id,
    list_representations,
    list_specimens,
    load_representation,
    load_specimen,
    rename_representation,
    rename_specimen,
    resolve_dependency,
)


def _write_toml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        tomli_w.dump(data, f)


def _write_specimen(registry_root: Path, name: str, **fields) -> Path:
    specimen_dir = registry_root / name
    _write_toml(specimen_dir / "specimen.toml", {"name": name, **fields})
    return specimen_dir


def _write_representation(
    registry_root: Path, specimen_name: str, representation_name: str, **fields
) -> Path:
    path = registry_root / specimen_name / "representations" / f"{representation_name}.toml"
    _write_toml(path, fields)
    return path


def test_load_specimen_reads_its_fields(tmp_path):
    _write_specimen(
        tmp_path,
        "SLS161",
        description="a lightsheet embryo",
        default_axes=[{"name": "z", "type": "space", "unit": "micrometer", "scale": 0.5}],
    )

    specimen = load_specimen(tmp_path, "SLS161")

    assert specimen.name == "SLS161"
    assert specimen.description == "a lightsheet embryo"
    assert specimen.default_axes == [Axis(name="z", type="space", unit="micrometer", scale=0.5)]


def test_load_specimen_raises_when_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="no specimen with id"):
        load_specimen(tmp_path, "does-not-exist")


def test_load_specimen_raises_when_name_field_mismatches_directory(tmp_path):
    _write_toml(tmp_path / "SLS161" / "specimen.toml", {"name": "wrong-name"})

    with pytest.raises(ValueError, match="does not match"):
        load_specimen(tmp_path, "SLS161")


def test_load_representation_uses_its_own_axes_over_specimen_defaults(tmp_path):
    _write_specimen(
        tmp_path,
        "SLS161",
        default_axes=[{"name": "z", "type": "space", "scale": 0.5}],
    )
    _write_representation(
        tmp_path,
        "SLS161",
        "raw",
        kind="image",
        path="/groups/shroff/raw.tif",
        axes=[{"name": "y", "type": "space", "scale": 0.1}],
    )

    representation = load_representation(tmp_path, "SLS161", "raw")

    assert isinstance(representation, ImageRepresentation)
    assert representation.axes == [Axis(name="y", type="space", scale=0.1)]


def test_load_representation_inherits_axes_from_specimen_defaults(tmp_path):
    _write_specimen(
        tmp_path,
        "SLS161",
        default_axes=[{"name": "z", "type": "space", "unit": "micrometer", "scale": 0.5}],
    )
    _write_representation(tmp_path, "SLS161", "raw", kind="image", path="/groups/shroff/raw.tif")

    representation = load_representation(tmp_path, "SLS161", "raw")

    assert representation.axes == [Axis(name="z", type="space", unit="micrometer", scale=0.5)]


def test_load_representation_inherits_acquisition_date_from_specimen_default(tmp_path):
    _write_specimen(
        tmp_path,
        "SLS161",
        default_axes=[{"name": "z"}],
        default_acquisition_date="2026-01-15",
    )
    _write_representation(tmp_path, "SLS161", "raw", kind="image", path="/groups/shroff/raw.tif")

    representation = load_representation(tmp_path, "SLS161", "raw")

    assert representation.acquisition_date.isoformat() == "2026-01-15"


def test_load_representation_raises_when_missing(tmp_path):
    _write_specimen(tmp_path, "SLS161")

    with pytest.raises(FileNotFoundError, match="no representation"):
        load_representation(tmp_path, "SLS161", "does-not-exist")


def test_load_representation_parses_segmentation_kind(tmp_path):
    _write_specimen(tmp_path, "SLS161")
    _write_representation(
        tmp_path,
        "SLS161",
        "cellpose_v3",
        kind="segmentation",
        path="/nrs/shroff/masks.zarr",
        axes=[{"name": "z"}, {"name": "y"}, {"name": "x"}],
        depends_on=["SLS161.raw"],
    )

    representation = load_representation(tmp_path, "SLS161", "cellpose_v3")

    assert isinstance(representation, SegmentationRepresentation)
    assert representation.depends_on == ["SLS161.raw"]


def test_image_representation_requires_axes(tmp_path):
    _write_specimen(tmp_path, "SLS161")
    _write_representation(tmp_path, "SLS161", "raw", kind="image", path="/groups/shroff/raw.tif")

    with pytest.raises(Exception, match="axes"):
        load_representation(tmp_path, "SLS161", "raw")


def test_load_representation_rejects_unknown_kind(tmp_path):
    _write_specimen(tmp_path, "SLS161")
    _write_representation(
        tmp_path, "SLS161", "weird", kind="tracking", path="/nrs/shroff/tracks.geff"
    )

    with pytest.raises(Exception, match="kind"):
        load_representation(tmp_path, "SLS161", "weird")


def test_channels_only_valid_on_image_representation(tmp_path):
    _write_specimen(tmp_path, "SLS161")
    _write_representation(
        tmp_path,
        "SLS161",
        "cellpose_v3",
        kind="segmentation",
        path="/nrs/shroff/masks.zarr",
        axes=[{"name": "z"}],
        channels={"1": "nuclear"},
    )

    with pytest.raises(ValidationError):
        load_representation(tmp_path, "SLS161", "cellpose_v3")


def test_resolve_dependency_loads_the_referenced_representation(tmp_path):
    _write_specimen(tmp_path, "SLS161")
    _write_representation(
        tmp_path, "SLS161", "raw", kind="image", path="/groups/shroff/raw.tif", axes=[{"name": "z"}]
    )
    _write_representation(
        tmp_path,
        "SLS161",
        "cellpose_v3",
        kind="segmentation",
        path="/nrs/shroff/masks.zarr",
        axes=[{"name": "z"}],
        depends_on=["SLS161.raw"],
    )

    segmentation = load_representation(tmp_path, "SLS161", "cellpose_v3")
    (dependency_ref,) = segmentation.depends_on
    dependency = resolve_dependency(tmp_path, dependency_ref)

    assert isinstance(dependency, ImageRepresentation)
    assert dependency.path == "/groups/shroff/raw.tif"


def test_resolve_dependency_rejects_malformed_reference(tmp_path):
    with pytest.raises(ValueError, match=r"specimen.*representation"):
        resolve_dependency(tmp_path, "not-a-valid-reference")


def test_resolve_dependency_raises_for_nonexistent_specimen(tmp_path):
    with pytest.raises(FileNotFoundError):
        resolve_dependency(tmp_path, "no-such-specimen.raw")


def test_resolve_dependency_raises_for_nonexistent_representation(tmp_path):
    _write_specimen(tmp_path, "SLS161")

    with pytest.raises(FileNotFoundError):
        resolve_dependency(tmp_path, "SLS161.no-such-representation")


def test_list_specimens_finds_only_directories_with_a_specimen_toml(tmp_path):
    _write_specimen(tmp_path, "SLS161")
    _write_specimen(tmp_path, "SLS042")
    (tmp_path / "not_a_specimen").mkdir()

    assert list_specimens(tmp_path) == ["SLS042", "SLS161"]


def test_list_representations_finds_every_representation_for_a_specimen(tmp_path):
    _write_specimen(tmp_path, "SLS161")
    _write_representation(tmp_path, "SLS161", "raw", kind="image", path="a", axes=[{"name": "z"}])
    _write_representation(
        tmp_path, "SLS161", "cellpose_v3", kind="segmentation", path="b", axes=[{"name": "z"}]
    )

    assert list_representations(tmp_path, "SLS161") == ["cellpose_v3", "raw"]


def test_load_specimen_defaults_id_to_directory_name_when_unset(tmp_path):
    _write_specimen(tmp_path, "SLS161")

    specimen = load_specimen(tmp_path, "SLS161")

    assert specimen.id == "SLS161"


def test_load_specimen_allows_name_to_differ_from_directory_once_id_is_set(tmp_path):
    _write_toml(tmp_path / "SLS161" / "specimen.toml", {"id": "SLS161", "name": "Embryo A"})

    specimen = load_specimen(tmp_path, "SLS161")

    assert specimen.id == "SLS161"
    assert specimen.name == "Embryo A"


def test_load_representation_defaults_id_and_name_to_filename_when_unset(tmp_path):
    _write_specimen(tmp_path, "SLS161")
    _write_representation(tmp_path, "SLS161", "raw", kind="image", path="a", axes=[{"name": "z"}])

    representation = load_representation(tmp_path, "SLS161", "raw")

    assert representation.id == "raw"
    assert representation.name == "raw"


def test_rename_specimen_changes_name_without_moving_directory(tmp_path):
    _write_specimen(tmp_path, "SLS161")

    rename_specimen(tmp_path, "SLS161", "Embryo A")

    assert (tmp_path / "SLS161").is_dir()
    specimen = load_specimen(tmp_path, "SLS161")
    assert specimen.id == "SLS161"
    assert specimen.name == "Embryo A"


def test_rename_specimen_backfills_id_on_first_rename_of_a_legacy_entry(tmp_path):
    _write_specimen(tmp_path, "SLS161")

    rename_specimen(tmp_path, "SLS161", "Embryo A")

    with (tmp_path / "SLS161" / "specimen.toml").open("rb") as f:
        raw = tomllib.load(f)
    assert raw["id"] == "SLS161"
    assert raw["name"] == "Embryo A"


def test_rename_representation_changes_name_without_moving_file(tmp_path):
    _write_specimen(tmp_path, "SLS161")
    _write_representation(tmp_path, "SLS161", "raw", kind="image", path="a", axes=[{"name": "z"}])

    rename_representation(tmp_path, "SLS161", "raw", "Raw scan")

    representation_path = tmp_path / "SLS161" / "representations" / "raw.toml"
    assert representation_path.is_file()
    representation = load_representation(tmp_path, "SLS161", "raw")
    assert representation.id == "raw"
    assert representation.name == "Raw scan"


def test_create_specimen_generates_a_unique_id_and_is_loadable(tmp_path):
    specimen_id = create_specimen(tmp_path, "Embryo A", description="a lightsheet embryo")

    specimen = load_specimen(tmp_path, specimen_id)
    assert specimen.id == specimen_id
    assert specimen.name == "Embryo A"
    assert specimen.description == "a lightsheet embryo"


def test_create_representation_generates_a_unique_id_and_is_loadable(tmp_path):
    specimen_id = create_specimen(tmp_path, "Embryo A")

    representation_id = create_representation(
        tmp_path,
        specimen_id,
        "Raw scan",
        kind="image",
        path="/groups/shroff/raw.tif",
        axes=[{"name": "z"}],
    )

    representation = load_representation(tmp_path, specimen_id, representation_id)
    assert representation.id == representation_id
    assert representation.name == "Raw scan"
    assert isinstance(representation, ImageRepresentation)


def test_generate_specimen_id_retries_on_a_forced_collision(tmp_path, monkeypatch):
    slugs = iter(["taken", "taken", "fresh"])
    monkeypatch.setattr("dataset_registry._registry.generate_slug", lambda _n: next(slugs))
    create_specimen(tmp_path, "First")  # takes the "taken" slug

    specimen_id = generate_specimen_id(tmp_path)

    assert specimen_id == "fresh"


def test_load_specimen_finds_a_renamed_specimen_whose_id_no_longer_matches_its_directory(tmp_path):
    # Simulates a specimen created directly on disk with a directory name
    # that differs from its own `id` -- the state a specimen reaches after
    # `rename_specimen` renames it a second time to something whose
    # directory no longer matches, exercising the linear-scan fallback in
    # `_find_specimen_dir` rather than its directory-name fast path.
    _write_toml(
        tmp_path / "some-directory" / "specimen.toml", {"id": "elsewhere", "name": "Embryo A"}
    )

    specimen = load_specimen(tmp_path, "elsewhere")

    assert specimen.name == "Embryo A"


def test_load_representation_finds_a_renamed_representation_whose_id_no_longer_matches_its_filename(
    tmp_path,
):
    _write_specimen(tmp_path, "SLS161")
    _write_toml(
        tmp_path / "SLS161" / "representations" / "some-file.toml",
        {
            "id": "elsewhere",
            "name": "Raw scan",
            "kind": "image",
            "path": "a",
            "axes": [{"name": "z"}],
        },
    )

    representation = load_representation(tmp_path, "SLS161", "elsewhere")

    assert representation.name == "Raw scan"


def test_depends_on_resolves_by_id_after_the_referenced_representation_is_renamed(tmp_path):
    specimen_id = create_specimen(tmp_path, "Embryo A")
    raw_id = create_representation(
        tmp_path, specimen_id, "Raw scan", kind="image", path="a", axes=[{"name": "z"}]
    )
    seg_id = create_representation(
        tmp_path,
        specimen_id,
        "Cellpose v3",
        kind="segmentation",
        path="b",
        axes=[{"name": "z"}],
        depends_on=[f"{specimen_id}.{raw_id}"],
    )

    rename_representation(tmp_path, specimen_id, raw_id, "Renamed raw scan")

    segmentation = load_representation(tmp_path, specimen_id, seg_id)
    (dependency_ref,) = segmentation.depends_on
    dependency = resolve_dependency(tmp_path, dependency_ref)

    assert dependency.id == raw_id
    assert dependency.name == "Renamed raw scan"
