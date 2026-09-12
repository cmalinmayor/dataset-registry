"""Generate a dataset-registry instance from Sgro lab SEM_tracking datasets.

Scans a `datasets_dir` of the form used by `sgro_lab_utils.Dataset` --
one subdirectory per dataset, each holding a `data_pyramid.zarr` with one
zarr group per channel (`channel_N[_masked]`) and per segmentation
(`seg_*`) -- and writes one dataset-registry specimen (`specimen.toml` +
`representations/*.toml`) into `registry_root`.

Reads zarr group attributes directly (no `sgro_lab_utils` import) so this
script only needs the lightweight `zarr` dependency, not that project's
full pixi environment:

    uv run --with zarr scripts/generate_sem_tracking_registry.py \\
        /Volumes/sgrolab/Jose/TrackingData examples/sem_tracking

`channel_*_masked_masked` groups are skipped: a known export-script bug
produced a second, redundant masking pass on some datasets, and those
groups aren't a real representation of anything.

Many dataset directories are the same underlying acquisition exported at
several time crops, differing only by a trailing frame-count suffix (e.g.
`..._SEM_10frames`, `..._SEM_50frames`, `..._SEM_50frames_test`). Those are
grouped into a single specimen named after the shared base, with each
crop's channels/segmentations kept as separate representations (suffixed
by the crop's own directory name) rather than collapsed away, since each
crop is a distinct zarr store.
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import tomli_w
import zarr

SPECIMEN_FILENAME = "specimen.toml"
REPRESENTATIONS_DIRNAME = "representations"
ZARR_NAME = "data_pyramid.zarr"
DOUBLE_MASKED_SUFFIX = "_masked_masked"

# Matches a trailing frame-count crop suffix, e.g. "_10frames", "_50frames_",
# "_50frames_test", "45frames" (no leading underscore, as in "...SEM2t3_allchannels_45frames").
_FRAMES_SUFFIX_RE = re.compile(r"_?\d+frames(?:_test)?_?$")


def _base_name(dataset_name: str) -> str:
    """Strip a trailing frame-count crop suffix, grouping crops of one acquisition."""
    return _FRAMES_SUFFIX_RE.sub("", dataset_name)


def _axes_from_multiscales(group: zarr.Group) -> list[dict[str, Any]]:
    """Read level-0 axes (name/type/unit/scale) from an SOME-NGFF multiscale group."""
    multiscales = group.attrs["multiscales"]
    some_axes = multiscales[0]["axes"]
    level_0 = multiscales[0]["datasets"][0]
    scale_transform = next(
        (t for t in level_0["coordinateTransformations"] if t["type"] == "scale"), None
    )
    scales = scale_transform["scale"] if scale_transform else [None] * len(some_axes)

    axes = []
    for axis, scale in zip(some_axes, scales, strict=True):
        entry = {"name": axis["name"]}
        if axis.get("type") is not None:
            entry["type"] = axis["type"]
        if axis.get("unit") is not None:
            entry["unit"] = axis["unit"]
        if scale is not None:
            entry["scale"] = scale
        axes.append(entry)
    return axes


def _channel_label(group: zarr.Group) -> str | None:
    """A nuclear/membrane label from a channel group's own attrs, only when explicit.

    Some datasets' export script never recorded `nuclear`/`membrane` on the
    channel group -- in that case this returns None rather than guessing.
    Written to `metadata.label` rather than `ImageRepresentation.channels`
    (a `dict[int, str]` meant for *multi*-channel arrays, keyed by channel
    index) since every channel group here is single-channel: a `channels =
    {0: "nuclear"}` dict for a 1-channel array is technically correct but
    reads as confusing boilerplate repeated on every representation.
    """
    attrs = group.attrs
    labels = [key for key in ("nuclear", "membrane") if attrs.get(key)]
    if not labels:
        return None
    return "/".join(labels)


def _channel_groups(root: zarr.Group) -> list[str]:
    keys = set(root.group_keys())
    return sorted(
        key
        for key in keys
        if (key.startswith("channel") or key in ("nuclear", "membrane"))
        and not key.endswith(DOUBLE_MASKED_SUFFIX)
    )


def _seg_groups(root: zarr.Group) -> list[str]:
    return sorted(key for key in root.group_keys() if key.startswith("seg"))


def _seg_depends_on(
    specimen_name: str, seg_name: str, channel_groups: list[str]
) -> list[str] | None:
    """Guess which channel a segmentation was derived from, from its nuclear/membrane suffix."""
    if seg_name.endswith(("nuclear", "membrane")):
        candidates = [c for c in channel_groups if not c.endswith("_masked")]
    else:
        return None
    if len(candidates) != 1:
        return None
    return [f"{specimen_name}.{candidates[0]}"]


def _write_toml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        tomli_w.dump(data, f)


def _representation_stem(group_name: str, dataset_dir: Path, multi_crop: bool) -> str:
    """The representation's filename stem, disambiguated by crop when a specimen has several."""
    if not multi_crop:
        return group_name
    return f"{group_name}__{dataset_dir.name}"


def generate_specimen(name: str, dataset_dirs: list[Path], registry_root: Path) -> None:
    """Write one specimen's `specimen.toml` and `representations/*.toml`.

    `dataset_dirs` holds every crop (differently-named directory sharing this
    specimen's base name) contributing representations to this specimen.
    """
    representations_dir = registry_root / name / REPRESENTATIONS_DIRNAME
    multi_crop = len(dataset_dirs) > 1
    written_channels = 0
    written_segs = 0

    for dataset_dir in dataset_dirs:
        zarr_path = dataset_dir / ZARR_NAME
        root = zarr.open_group(str(zarr_path), mode="r")
        channel_groups = _channel_groups(root)
        seg_groups = _seg_groups(root)

        for channel_name in channel_groups:
            group = root[channel_name]
            if "multiscales" not in group.attrs:
                print(
                    f"skipping {dataset_dir.name!r} channel {channel_name!r}: "
                    "no multiscales metadata (incompletely written?)",
                    file=sys.stderr,
                )
                continue
            stem = _representation_stem(channel_name, dataset_dir, multi_crop)
            representation: dict[str, Any] = {
                "kind": "image",
                "path": str(zarr_path / channel_name),
                "axes": _axes_from_multiscales(group),
            }
            label = _channel_label(group)
            if label is not None:
                representation["metadata"] = {"label": label}
            if channel_name.endswith("_masked"):
                base_channel = channel_name.removesuffix("_masked")
                base_stem = _representation_stem(base_channel, dataset_dir, multi_crop)
                representation["depends_on"] = [f"{name}.{base_stem}"]
            _write_toml(representations_dir / f"{stem}.toml", representation)
            written_channels += 1

        for seg_name in seg_groups:
            group = root[seg_name]
            if "multiscales" not in group.attrs:
                print(
                    f"skipping {dataset_dir.name!r} segmentation {seg_name!r}: "
                    "no multiscales metadata (incompletely written?)",
                    file=sys.stderr,
                )
                continue
            stem = _representation_stem(seg_name, dataset_dir, multi_crop)
            representation = {
                "kind": "segmentation",
                "path": str(zarr_path / seg_name),
                "axes": _axes_from_multiscales(group),
            }
            depends_on = _seg_depends_on(name, seg_name, channel_groups)
            if depends_on is not None:
                (base_channel,) = (ref.rpartition(".")[2] for ref in depends_on)
                base_stem = _representation_stem(base_channel, dataset_dir, multi_crop)
                representation["depends_on"] = [f"{name}.{base_stem}"]
            _write_toml(representations_dir / f"{stem}.toml", representation)
            written_segs += 1

    if written_channels == 0:
        print(
            f"skipping {name!r}: no channel groups with multiscales metadata found", file=sys.stderr
        )
        return

    _write_toml(registry_root / name / SPECIMEN_FILENAME, {"name": name})
    print(f"wrote {name!r}: {written_channels} channel(s), {written_segs} segmentation(s)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "datasets_dir", type=Path, help="Directory of SEM_tracking dataset subdirectories."
    )
    parser.add_argument("registry_root", type=Path, help="Output registry root directory.")
    args = parser.parse_args()

    specimens: dict[str, list[Path]] = {}
    for dataset_dir in sorted(args.datasets_dir.iterdir()):
        if not (dataset_dir / ZARR_NAME).is_dir():
            continue
        specimens.setdefault(_base_name(dataset_dir.name), []).append(dataset_dir)

    for name, dataset_dirs in sorted(specimens.items()):
        generate_specimen(name, dataset_dirs, args.registry_root)


if __name__ == "__main__":
    main()
