"""Load and edit a registry's specimens and representations, stored as TOML on disk."""

import tomllib
from datetime import date
from pathlib import Path
from typing import Any

import tomli_w
from coolname import generate_slug
from pydantic import TypeAdapter

from dataset_registry._schema import (
    ImageRepresentation,
    PointsRepresentation,
    RegistryInfo,
    Representation,
    SegmentationRepresentation,
    Specimen,
)

SPECIMEN_FILENAME = "specimen.toml"
REPRESENTATIONS_DIRNAME = "representations"
REGISTRY_INFO_FILENAME = "registry.toml"

_ID_GENERATION_ATTEMPTS = 100

_representation_adapter: TypeAdapter[
    ImageRepresentation | SegmentationRepresentation | PointsRepresentation
] = TypeAdapter(Representation)

# Sentinel distinguishing "leave this field unchanged" from "set it to None".
_UNSET = object()


def _specimen_dirs(registry_root: Path) -> list[Path]:
    return sorted(p.parent for p in registry_root.glob(f"*/{SPECIMEN_FILENAME}"))


def _find_specimen_dir(registry_root: Path, specimen_id: str) -> Path:
    """Find the directory whose specimen has `specimen_id`, scanning if necessary.

    A specimen's `id` equals its directory name until the specimen is
    renamed for the first time (see `Specimen.id`'s docstring), so this
    first checks the directory of the same name as `specimen_id` -- the
    common case, and the only case for a registry with no renamed
    specimens -- before falling back to a linear scan for a specimen
    whose `id` no longer matches its directory name.

    Raises:
        FileNotFoundError: If no specimen with this id exists.
    """
    fast_path = registry_root / specimen_id
    if (fast_path / SPECIMEN_FILENAME).is_file():
        with (fast_path / SPECIMEN_FILENAME).open("rb") as f:
            raw = tomllib.load(f)
        if raw.get("id", specimen_id) == specimen_id:
            return fast_path

    for specimen_dir in _specimen_dirs(registry_root):
        with (specimen_dir / SPECIMEN_FILENAME).open("rb") as f:
            raw = tomllib.load(f)
        if raw.get("id", specimen_dir.name) == specimen_id:
            return specimen_dir

    raise FileNotFoundError(f"no specimen with id {specimen_id!r} found under {registry_root}")


def _find_representation_path(
    registry_root: Path, specimen_id: str, representation_id: str
) -> Path:
    """Find the file whose representation has `representation_id`, scanning if necessary.

    Same fast-path-then-scan strategy as `_find_specimen_dir`, applied to a
    representation's file (minus `.toml`) instead of a specimen's directory.

    Raises:
        FileNotFoundError: If no such specimen, or no representation with
            this id under it, exists.
    """
    specimen_dir = _find_specimen_dir(registry_root, specimen_id)
    representations_dir = specimen_dir / REPRESENTATIONS_DIRNAME

    fast_path = representations_dir / f"{representation_id}.toml"
    if fast_path.is_file():
        with fast_path.open("rb") as f:
            raw = tomllib.load(f)
        if raw.get("id", representation_id) == representation_id:
            return fast_path

    for representation_path in sorted(representations_dir.glob("*.toml")):
        with representation_path.open("rb") as f:
            raw = tomllib.load(f)
        if raw.get("id", representation_path.stem) == representation_id:
            return representation_path

    raise FileNotFoundError(
        f"no representation with id {representation_id!r} found for specimen "
        f"{specimen_id!r} under {registry_root}"
    )


def _generate_id(existing_ids: set[str]) -> str:
    """A two-word coolname slug (e.g. `"happy-falcon"`) not already in `existing_ids`.

    Raises:
        RuntimeError: If every attempt collided -- vanishingly unlikely for
            any registry that isn't enormous, but a silent infinite loop
            would be worse than a loud, rare failure.
    """
    for _ in range(_ID_GENERATION_ATTEMPTS):
        slug: str = generate_slug(2)
        if slug not in existing_ids:
            return slug
    raise RuntimeError(f"could not generate a unique id after {_ID_GENERATION_ATTEMPTS} attempts")


def generate_specimen_id(registry_root: Path) -> str:
    """A two-word coolname slug not already used as a specimen id in this registry.

    Args:
        registry_root: Directory containing one subdirectory per specimen.

    Returns:
        A newly generated, unique specimen id.
    """
    existing_ids = {
        _specimen_id_from_dir(specimen_dir) for specimen_dir in _specimen_dirs(registry_root)
    }
    return _generate_id(existing_ids)


def generate_representation_id(registry_root: Path, specimen_id: str) -> str:
    """A two-word coolname slug not already used as a representation id for this specimen.

    Args:
        registry_root: Directory containing one subdirectory per specimen.
        specimen_id: The owning specimen's id.

    Returns:
        A newly generated, unique representation id.
    """
    specimen_dir = _find_specimen_dir(registry_root, specimen_id)
    representations_dir = specimen_dir / REPRESENTATIONS_DIRNAME
    existing_ids = {
        _representation_id_from_path(path) for path in sorted(representations_dir.glob("*.toml"))
    }
    return _generate_id(existing_ids)


def _specimen_id_from_dir(specimen_dir: Path) -> str:
    with (specimen_dir / SPECIMEN_FILENAME).open("rb") as f:
        raw = tomllib.load(f)
    return str(raw.get("id", specimen_dir.name))


def _representation_id_from_path(representation_path: Path) -> str:
    with representation_path.open("rb") as f:
        raw = tomllib.load(f)
    return str(raw.get("id", representation_path.stem))


def load_specimen(registry_root: Path, specimen_id: str) -> Specimen:
    """Load one specimen by id.

    `registry_root` contains one directory per specimen:

        <registry_root>/
          <specimen directory>/
            specimen.toml
            representations/
              <representation file>.toml
              ...

    A specimen's `id` defaults to its directory name when `specimen.toml`
    doesn't set `id` explicitly (a registry predating stable ids, or a
    specimen never renamed) -- see `Specimen.id`. The returned `Specimen`
    always has `id` populated, even when it was unset on disk.

    Args:
        registry_root: Directory containing one subdirectory per specimen.
        specimen_id: The specimen's stable id.

    Returns:
        The loaded specimen.

    Raises:
        FileNotFoundError: If no specimen with this id exists.
        ValueError: If `specimen.toml` has no explicit `id` and its `name`
            field doesn't match its directory name -- the legacy
            name-is-the-identity invariant this predates stable ids.
    """
    specimen_dir = _find_specimen_dir(registry_root, specimen_id)
    specimen_path = specimen_dir / SPECIMEN_FILENAME

    with specimen_path.open("rb") as f:
        raw = tomllib.load(f)

    if "id" not in raw and raw.get("name") != specimen_dir.name:
        raise ValueError(
            f"{specimen_path}'s name field ({raw.get('name')!r}) does not match its "
            f"directory name ({specimen_dir.name!r})"
        )
    raw.setdefault("id", specimen_dir.name)

    specimen: Specimen = Specimen.model_validate(raw)
    return specimen


def load_representation(
    registry_root: Path, specimen_id: str, representation_id: str
) -> Representation:
    """Load one representation, resolving axes/acquisition_date from the specimen's defaults.

    If the representation's own TOML doesn't set `axes`/`acquisition_date`,
    they're filled in from the specimen's `default_axes`/
    `default_acquisition_date`. This inheritance can't live in a pydantic
    validator on `Representation` itself, since it requires reading a second
    file (the specimen).

    A representation's `id`/`name` default to its filename (minus `.toml`)
    when unset on disk -- see `_RepresentationBase.id`. The returned model
    always has both populated.

    Args:
        registry_root: Directory containing one subdirectory per specimen.
        specimen_id: The owning specimen's id.
        representation_id: The representation's stable id.

    Returns:
        The loaded representation, an `ImageRepresentation`,
        `SegmentationRepresentation`, or `PointsRepresentation` depending on
        its recorded `kind`.

    Raises:
        FileNotFoundError: If no such specimen or representation exists.
    """
    representation_path = _find_representation_path(registry_root, specimen_id, representation_id)

    with representation_path.open("rb") as f:
        raw = tomllib.load(f)
    raw.setdefault("id", representation_path.stem)
    raw.setdefault("name", representation_path.stem)

    specimen = load_specimen(registry_root, specimen_id)
    if "axes" not in raw and specimen.default_axes is not None and raw.get("kind") != "points":
        raw["axes"] = [axis.model_dump() for axis in specimen.default_axes]
    if "acquisition_date" not in raw and specimen.default_acquisition_date is not None:
        raw["acquisition_date"] = specimen.default_acquisition_date

    representation: ImageRepresentation | SegmentationRepresentation | PointsRepresentation = (
        _representation_adapter.validate_python(raw)
    )
    return representation


def resolve_dependency(registry_root: Path, reference: str) -> Representation:
    """Load the representation referenced by a `depends_on` entry.

    Args:
        registry_root: Directory containing one subdirectory per specimen.
        reference: A `"<specimen id>.<representation id>"` string, as found
            in another representation's `depends_on` list.

    Returns:
        The referenced representation.

    Raises:
        ValueError: If `reference` isn't of the form `"<specimen id>.<representation id>"`.
        FileNotFoundError: If the referenced specimen or representation
            doesn't exist -- surfaces a typo'd `depends_on` immediately,
            rather than at some later, harder-to-trace point.
    """
    specimen_id, sep, representation_id = reference.partition(".")
    if not sep:
        raise ValueError(
            f"expected a '<specimen id>.<representation id>' reference, got {reference!r}"
        )
    return load_representation(registry_root, specimen_id, representation_id)


def load_registry_info(registry_root: Path) -> RegistryInfo:
    """Load registry-level settings from an optional `registry.toml` at `registry_root`.

    Args:
        registry_root: Directory containing one subdirectory per specimen.

    Returns:
        The registry's settings, or an all-defaults `RegistryInfo` if
        `registry.toml` doesn't exist -- this file is optional, unlike
        `specimen.toml`.
    """
    registry_info_path = registry_root / REGISTRY_INFO_FILENAME
    if not registry_info_path.is_file():
        return RegistryInfo()
    with registry_info_path.open("rb") as f:
        registry_info: RegistryInfo = RegistryInfo.model_validate(tomllib.load(f))
    return registry_info


def list_specimens(registry_root: Path) -> list[str]:
    """The ids of every specimen directly under `registry_root`.

    Args:
        registry_root: Directory containing one subdirectory per specimen.

    Returns:
        Specimen ids, sorted, for every subdirectory containing a
        `specimen.toml`.
    """
    return sorted(
        _specimen_id_from_dir(specimen_dir) for specimen_dir in _specimen_dirs(registry_root)
    )


def list_representations(registry_root: Path, specimen_id: str) -> list[str]:
    """The ids of every representation belonging to one specimen.

    Args:
        registry_root: Directory containing one subdirectory per specimen.
        specimen_id: The owning specimen's id.

    Returns:
        Representation ids, sorted.
    """
    specimen_dir = _find_specimen_dir(registry_root, specimen_id)
    representations_dir = specimen_dir / REPRESENTATIONS_DIRNAME
    return sorted(_representation_id_from_path(path) for path in representations_dir.glob("*.toml"))


def create_specimen(
    registry_root: Path,
    name: str,
    *,
    description: str | None = None,
    default_acquisition_date: date | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Create a new specimen with a freshly generated id.

    The generated id is used as both `specimen.toml`'s `id` field and the
    specimen's directory name -- for a specimen created this way, renaming
    it later never needs to move the directory (see `rename_specimen`).

    Args:
        registry_root: Directory containing one subdirectory per specimen.
        name: The specimen's initial display name.
        description: Initial description, if any.
        default_acquisition_date: Initial default acquisition date, if any.
        metadata: Initial metadata table, if any.

    Returns:
        The newly generated specimen id.
    """
    specimen_id = generate_specimen_id(registry_root)
    specimen_dir = registry_root / specimen_id
    specimen_dir.mkdir(parents=True)

    raw: dict[str, Any] = {"id": specimen_id, "name": name}
    if description is not None:
        raw["description"] = description
    if default_acquisition_date is not None:
        raw["default_acquisition_date"] = default_acquisition_date
    if metadata is not None:
        raw["metadata"] = metadata

    with (specimen_dir / SPECIMEN_FILENAME).open("wb") as f:
        tomli_w.dump(raw, f)
    load_specimen(registry_root, specimen_id)
    return specimen_id


def create_representation(
    registry_root: Path,
    specimen_id: str,
    name: str,
    *,
    kind: str,
    path: str,
    depends_on: list[str] | None = None,
    axes: list[dict[str, Any]] | None = None,
    channels: dict[int, str] | None = None,
    acquisition_date: date | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Create a new representation with a freshly generated id.

    The generated id is used as both the representation's `id` field and
    its filename (minus `.toml`) -- for a representation created this way,
    renaming it later never needs to move the file (see
    `rename_representation`).

    Args:
        registry_root: Directory containing one subdirectory per specimen.
        specimen_id: The owning specimen's id.
        name: The representation's initial display name.
        kind: `"image"`, `"segmentation"`, or `"points"`.
        path: Filesystem path to the representation's data.
        depends_on: Other representations this one was produced from, each
            a `"<specimen id>.<representation id>"` reference.
        axes: Initial `axes`, or omitted to inherit the specimen's
            `default_axes` at load time.
        channels: Initial `channels` (only meaningful for `kind="image"`).
        acquisition_date: Initial acquisition date, or omitted to inherit
            the specimen's `default_acquisition_date` at load time.
        metadata: Initial metadata table, if any.

    Returns:
        The newly generated representation id.
    """
    representation_id = generate_representation_id(registry_root, specimen_id)
    specimen_dir = _find_specimen_dir(registry_root, specimen_id)
    representations_dir = specimen_dir / REPRESENTATIONS_DIRNAME
    representations_dir.mkdir(exist_ok=True)

    raw: dict[str, Any] = {
        "id": representation_id,
        "name": name,
        "kind": kind,
        "path": path,
    }
    if depends_on is not None:
        raw["depends_on"] = depends_on
    if axes is not None:
        raw["axes"] = axes
    if channels is not None:
        raw["channels"] = channels
    if acquisition_date is not None:
        raw["acquisition_date"] = acquisition_date
    if metadata is not None:
        raw["metadata"] = metadata

    representation_path = representations_dir / f"{representation_id}.toml"
    with representation_path.open("wb") as f:
        tomli_w.dump(raw, f)
    load_representation(registry_root, specimen_id, representation_id)
    return representation_id


def rename_specimen(registry_root: Path, specimen_id: str, new_name: str) -> None:
    """Change a specimen's display `name`, without moving its directory.

    If `specimen.toml` has no explicit `id` yet (a registry predating
    stable ids), this backfills `id` to the specimen's current directory
    name before changing `name` -- from this point on, its directory name
    no longer needs to match `name`.

    Args:
        registry_root: Directory containing one subdirectory per specimen.
        specimen_id: The specimen's stable id.
        new_name: The new display name.
    """
    specimen_dir = _find_specimen_dir(registry_root, specimen_id)
    specimen_path = specimen_dir / SPECIMEN_FILENAME
    with specimen_path.open("rb") as f:
        raw = tomllib.load(f)

    raw.setdefault("id", specimen_dir.name)
    raw["name"] = new_name

    with specimen_path.open("wb") as f:
        tomli_w.dump(raw, f)
    load_specimen(registry_root, raw["id"])


def rename_representation(
    registry_root: Path, specimen_id: str, representation_id: str, new_name: str
) -> None:
    """Change a representation's display `name`, without moving its file.

    If the representation's TOML has no explicit `id` yet (a registry
    predating stable ids), this backfills `id` to its current filename
    (minus `.toml`) before changing `name` -- from this point on, its
    filename no longer needs to match `name`.

    Args:
        registry_root: Directory containing one subdirectory per specimen.
        specimen_id: The owning specimen's id.
        representation_id: The representation's stable id.
        new_name: The new display name.
    """
    representation_path = _find_representation_path(registry_root, specimen_id, representation_id)
    with representation_path.open("rb") as f:
        raw = tomllib.load(f)

    raw.setdefault("id", representation_path.stem)
    raw["name"] = new_name

    with representation_path.open("wb") as f:
        tomli_w.dump(raw, f)
    load_representation(registry_root, specimen_id, raw["id"])


def set_specimen_fields(
    registry_root: Path,
    specimen_id: str,
    *,
    description: str | None = _UNSET,  # type: ignore[assignment]
    default_acquisition_date: date | None = _UNSET,  # type: ignore[assignment]
    metadata: dict[str, Any] | None = _UNSET,  # type: ignore[assignment]
) -> None:
    """Update one or more of a specimen's own fields in place, in a single write.

    Only the fields actually passed are changed -- `name`, `default_axes`,
    and every other field not accepted by this function is left untouched
    (use `rename_specimen` to change `name`). Passing `None` for
    `description`/`default_acquisition_date` clears that field (distinct
    from not passing it at all, which leaves it as-is). `metadata`, when
    passed, replaces the entire `[metadata]` table rather than merging into
    it -- callers that want to change one key should read the specimen's
    current `metadata` first.

    Loads and re-validates the specimen afterwards, so a call that would
    leave `specimen.toml` invalid (e.g. writing to a specimen that doesn't
    exist) fails loudly rather than silently corrupting the file.

    Args:
        registry_root: Directory containing one subdirectory per specimen.
        specimen_id: The specimen's stable id.
        description: The new description text, `None` to clear it, or
            omitted to leave it unchanged.
        default_acquisition_date: The new default acquisition date, `None`
            to clear it, or omitted to leave it unchanged.
        metadata: The new `metadata` table, replacing it wholesale, or
            omitted to leave it unchanged.
    """
    specimen_path = _find_specimen_dir(registry_root, specimen_id) / SPECIMEN_FILENAME
    with specimen_path.open("rb") as f:
        raw = tomllib.load(f)

    if description is not _UNSET:
        if description is None:
            raw.pop("description", None)
        else:
            raw["description"] = description
    if default_acquisition_date is not _UNSET:
        if default_acquisition_date is None:
            raw.pop("default_acquisition_date", None)
        else:
            raw["default_acquisition_date"] = default_acquisition_date
    if metadata is not _UNSET:
        raw["metadata"] = metadata

    with specimen_path.open("wb") as f:
        tomli_w.dump(raw, f)
    load_specimen(registry_root, specimen_id)


def set_specimen_description(registry_root: Path, specimen_id: str, description: str) -> None:
    """Update one specimen's `description` field in place, leaving every other field untouched.

    Args:
        registry_root: Directory containing one subdirectory per specimen.
        specimen_id: The specimen's stable id.
        description: The new description text.
    """
    set_specimen_fields(registry_root, specimen_id, description=description)
