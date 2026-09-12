"""A registry of samples and representations, stored as TOML on disk."""

import hashlib
import logging
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import tomli_w
from coolname import generate_slug
from platformdirs import user_cache_dir

from dataset_registry._schema import RegistryInfo, Representation, Sample

SAMPLE_FILENAME = "sample.toml"
REPRESENTATIONS_DIRNAME = "representations"
REGISTRY_INFO_FILENAME = "registry.toml"

_ID_GENERATION_ATTEMPTS = 100
_CACHE_APP_NAME = "dataset-registry"

_logger = logging.getLogger(__name__)

# Sentinel distinguishing "leave this field unchanged" from "set it to None".
_UNSET = object()


def _load_raw(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        raw: dict[str, Any] = tomllib.load(f)
    return raw


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


def _cache_dir_for(git_url: str) -> Path:
    # Keyed by a hash of the URL rather than the URL itself, so the cache
    # directory name is always filesystem-safe regardless of what characters
    # the URL contains.
    digest = hashlib.sha256(git_url.encode()).hexdigest()[:16]
    return Path(user_cache_dir(_CACHE_APP_NAME)) / digest


def _run_git(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60, check=True
    )


def _clone(git_url: str, cache_dir: Path) -> None:
    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    _run_git(["clone", "--depth=1", git_url, str(cache_dir)])


def _fetch_latest(cache_dir: Path) -> None:
    _run_git(["fetch", "--depth=1", "origin"], cwd=cache_dir)
    remote_head = _run_git(["rev-parse", "origin/HEAD"], cwd=cache_dir).stdout.strip()
    _run_git(["reset", "--hard", remote_head], cwd=cache_dir)


def _current_commit(path: Path) -> str | None:
    try:
        return _run_git(["rev-parse", "HEAD"], cwd=path).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _resolve_local_path(location: str | Path, *, fetch: bool) -> Path:
    """Resolve `location` to a local directory, cloning it first if it's a git URL.

    If `location` is an existing local directory, returns it directly -- no
    cloning, no cache, no network -- which is both the simple common case
    (a registry already checked out locally, e.g. on a shared fileshare) and
    what keeps tests fast and network-free.

    Otherwise, treats `location` as a git URL: clones (or reuses a cached
    clone of) it under a per-user cache directory, keyed by `location`, as a
    shallow (`--depth=1`) clone. If a cache already exists and `fetch` is
    true, fetches and resets it to the remote's default branch tip first;
    if `fetch` is false, the existing cache is used as-is, however stale.

    If the fetch fails (e.g. no network), falls back to the existing cache
    with a warning rather than failing outright -- better to work against a
    possibly-stale registry than not run at all. If no cache exists yet, a
    clone always happens regardless of `fetch` -- there's nothing to fall
    back to otherwise.
    """
    local_path = Path(location)
    if local_path.is_dir():
        return local_path

    git_url = str(location)
    cache_dir = _cache_dir_for(git_url)

    if not cache_dir.is_dir():
        _clone(git_url, cache_dir)
    elif fetch:
        try:
            _fetch_latest(cache_dir)
        except (OSError, subprocess.SubprocessError) as e:
            _logger.warning(
                "could not fetch latest for %s (%s); using cached clone at %s, which may be stale",
                git_url,
                e,
                cache_dir,
            )
    return cache_dir


class Registry:
    """A registry of samples and representations: a local or git-hosted directory of TOML files.

    `location` is either an existing local directory (used directly, no
    cloning) or a git URL (shallow-cloned, or reused from a per-user cache).
    Every load/create/rename/set call below is scoped to this one resolved
    directory.

        <path>/
          <sample directory>/
            sample.toml
            representations/
              <representation file>.toml
              ...

    Directory and file names carry no meaning of their own -- `id`/`name`
    are always read from a `sample.toml`/representation TOML's own fields,
    never inferred from where it lives on disk.
    """

    path: Path
    """Local path this registry resolved to."""

    commit: str | None
    """The full commit SHA `path` is checked out at, or `None` if `path`
    isn't inside a git repository -- e.g. a local directory passed directly,
    with no git history of its own."""

    def __init__(self, location: str | Path, *, fetch: bool = True) -> None:
        """Resolve `location` to a local registry directory.

        Args:
            location: An existing local directory, or a git URL cloneable
                with `git clone` (e.g. `"https://github.com/<owner>/<repo>"`).
            fetch: If `location` is a git URL and a cached clone from a
                previous `Registry(location)` call already exists, whether
                to fetch and reset it to the remote's default branch tip
                before use. Defaults to `True`, matching the historical
                behavior of always pulling on open. Pass `False` to reuse
                the existing cache as-is, however stale -- e.g. to avoid a
                network round-trip on every call, or to pin to whatever was
                last fetched until an explicit `Registry(location, fetch=True)`.
                Ignored for a local-directory `location`, and for a git URL
                with no existing cache -- both always use the freshest data
                available (the directory itself, or a fresh clone).
        """
        path = _resolve_local_path(location, fetch=fetch)
        if not path.is_dir():
            raise NotADirectoryError(f"{path} is not a directory")
        self.path = path
        self.commit = _current_commit(path)

    def _sample_dirs(self) -> list[Path]:
        return sorted(p.parent for p in self.path.glob(f"*/{SAMPLE_FILENAME}"))

    def _find_sample_dir(self, sample_id: str) -> Path:
        """Find the directory whose sample has `sample_id`.

        A sample's directory name carries no meaning of its own -- `id` is
        only ever read from `sample.toml`'s own `id` field -- so this always
        scans every sample in the registry.

        Raises:
            FileNotFoundError: If no sample with this id exists.
        """
        for sample_dir in self._sample_dirs():
            raw = _load_raw(sample_dir / SAMPLE_FILENAME)
            if raw.get("id") == sample_id:
                return sample_dir
        raise FileNotFoundError(f"no sample with id {sample_id!r} found under {self.path}")

    def _find_representation_path(self, sample_id: str, representation_id: str) -> Path:
        """Find the file whose representation has `representation_id`.

        Same reasoning as `_find_sample_dir`: a representation's filename
        carries no meaning of its own, so this always scans every
        representation belonging to the sample.

        Raises:
            FileNotFoundError: If no such sample, or no representation with
                this id under it, exists.
        """
        sample_dir = self._find_sample_dir(sample_id)
        representations_dir = sample_dir / REPRESENTATIONS_DIRNAME

        for representation_path in sorted(representations_dir.glob("*.toml")):
            raw = _load_raw(representation_path)
            if raw.get("id") == representation_id:
                return representation_path

        raise FileNotFoundError(
            f"no representation with id {representation_id!r} found for sample "
            f"{sample_id!r} under {self.path}"
        )

    def generate_sample_id(self) -> str:
        """A two-word coolname slug not already used as a sample id in this registry."""
        existing_ids = {
            _load_raw(sample_dir / SAMPLE_FILENAME)["id"] for sample_dir in self._sample_dirs()
        }
        return _generate_id(existing_ids)

    def generate_representation_id(self, sample_id: str) -> str:
        """A two-word coolname slug not already used as a representation id for this sample."""
        sample_dir = self._find_sample_dir(sample_id)
        representations_dir = sample_dir / REPRESENTATIONS_DIRNAME
        existing_ids = {
            _load_raw(path)["id"] for path in sorted(representations_dir.glob("*.toml"))
        }
        return _generate_id(existing_ids)

    def load_sample(self, sample_id: str) -> Sample:
        """Load one sample by id.

        Args:
            sample_id: The sample's stable id.

        Returns:
            The loaded sample.

        Raises:
            FileNotFoundError: If no sample with this id exists.
        """
        sample_dir = self._find_sample_dir(sample_id)
        raw = _load_raw(sample_dir / SAMPLE_FILENAME)
        sample = Sample.model_validate(raw)
        return sample

    def load_representation(self, sample_id: str, representation_id: str) -> Representation:
        """Load one representation.

        Args:
            sample_id: The owning sample's id.
            representation_id: The representation's stable id.

        Returns:
            The loaded representation.

        Raises:
            FileNotFoundError: If no such sample or representation exists.
        """
        representation_path = self._find_representation_path(sample_id, representation_id)
        raw = _load_raw(representation_path)
        representation = Representation.model_validate(raw)
        return representation

    def load_registry_info(self) -> RegistryInfo:
        """Load registry-level settings from an optional `registry.toml` at this registry's root.

        Returns:
            The registry's settings, or an all-defaults `RegistryInfo` if
            `registry.toml` doesn't exist -- this file is optional, unlike
            `sample.toml`.
        """
        registry_info_path = self.path / REGISTRY_INFO_FILENAME
        if not registry_info_path.is_file():
            return RegistryInfo()
        registry_info = RegistryInfo.model_validate(_load_raw(registry_info_path))
        return registry_info

    def list_samples(self) -> list[str]:
        """The ids of every sample in this registry.

        Returns:
            Sample ids, sorted, for every subdirectory containing a `sample.toml`.
        """
        return sorted(
            _load_raw(sample_dir / SAMPLE_FILENAME)["id"] for sample_dir in self._sample_dirs()
        )

    def list_representations(self, sample_id: str) -> list[str]:
        """The ids of every representation belonging to one sample.

        Args:
            sample_id: The owning sample's id.

        Returns:
            Representation ids, sorted.
        """
        sample_dir = self._find_sample_dir(sample_id)
        representations_dir = sample_dir / REPRESENTATIONS_DIRNAME
        return sorted(_load_raw(path)["id"] for path in representations_dir.glob("*.toml"))

    def create_sample(
        self, name: str, *, description: str | None = None, metadata: dict[str, Any] | None = None
    ) -> str:
        """Create a new sample with a freshly generated id.

        Args:
            name: The sample's initial display name.
            description: Initial description, if any.
            metadata: Initial metadata table, if any.

        Returns:
            The newly generated sample id.
        """
        sample_id = self.generate_sample_id()
        sample_dir = self.path / sample_id
        sample_dir.mkdir(parents=True)

        raw: dict[str, Any] = {"id": sample_id, "name": name}
        if description is not None:
            raw["description"] = description
        if metadata is not None:
            raw["metadata"] = metadata

        with (sample_dir / SAMPLE_FILENAME).open("wb") as f:
            tomli_w.dump(raw, f)
        self.load_sample(sample_id)
        return sample_id

    def create_representation(
        self,
        sample_id: str,
        name: str,
        *,
        path: str,
        depends_on: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Create a new representation with a freshly generated id.

        Args:
            sample_id: The owning sample's id.
            name: The representation's initial display name.
            path: Filesystem path to the representation's data.
            depends_on: Ids of other representations of the same sample that
                this one was produced from.
            metadata: Initial metadata table, if any.

        Returns:
            The newly generated representation id.
        """
        representation_id = self.generate_representation_id(sample_id)
        sample_dir = self._find_sample_dir(sample_id)
        representations_dir = sample_dir / REPRESENTATIONS_DIRNAME
        representations_dir.mkdir(exist_ok=True)

        raw: dict[str, Any] = {"id": representation_id, "name": name, "path": path}
        if depends_on is not None:
            raw["depends_on"] = depends_on
        if metadata is not None:
            raw["metadata"] = metadata

        representation_path = representations_dir / f"{representation_id}.toml"
        with representation_path.open("wb") as f:
            tomli_w.dump(raw, f)
        self.load_representation(sample_id, representation_id)
        return representation_id

    def rename_sample(self, sample_id: str, new_name: str) -> None:
        """Change a sample's display `name`.

        Args:
            sample_id: The sample's stable id.
            new_name: The new display name.
        """
        sample_path = self._find_sample_dir(sample_id) / SAMPLE_FILENAME
        raw = _load_raw(sample_path)
        raw["name"] = new_name

        with sample_path.open("wb") as f:
            tomli_w.dump(raw, f)
        self.load_sample(sample_id)

    def rename_representation(self, sample_id: str, representation_id: str, new_name: str) -> None:
        """Change a representation's display `name`.

        Args:
            sample_id: The owning sample's id.
            representation_id: The representation's stable id.
            new_name: The new display name.
        """
        representation_path = self._find_representation_path(sample_id, representation_id)
        raw = _load_raw(representation_path)
        raw["name"] = new_name

        with representation_path.open("wb") as f:
            tomli_w.dump(raw, f)
        self.load_representation(sample_id, representation_id)

    def set_sample_fields(
        self,
        sample_id: str,
        *,
        description: str | None = _UNSET,  # type: ignore[assignment]
        metadata: dict[str, Any] | None = _UNSET,  # type: ignore[assignment]
    ) -> None:
        """Update one or more of a sample's own fields in place, in a single write.

        Only the fields actually passed are changed -- `name` and every
        other field not accepted by this method is left untouched (use
        `rename_sample` to change `name`). Passing `None` for `description`
        clears that field (distinct from not passing it at all, which
        leaves it as-is). `metadata`, when passed, replaces the entire
        `[metadata]` table rather than merging into it -- callers that want
        to change one key should read the sample's current `metadata` first.

        Loads and re-validates the sample afterwards, so a call that would
        leave `sample.toml` invalid (e.g. writing to a sample that doesn't
        exist) fails loudly rather than silently corrupting the file.

        Args:
            sample_id: The sample's stable id.
            description: The new description text, `None` to clear it, or
                omitted to leave it unchanged.
            metadata: The new `metadata` table, replacing it wholesale, or
                omitted to leave it unchanged.
        """
        sample_path = self._find_sample_dir(sample_id) / SAMPLE_FILENAME
        raw = _load_raw(sample_path)

        if description is not _UNSET:
            if description is None:
                raw.pop("description", None)
            else:
                raw["description"] = description
        if metadata is not _UNSET:
            raw["metadata"] = metadata

        with sample_path.open("wb") as f:
            tomli_w.dump(raw, f)
        self.load_sample(sample_id)

    def set_representation_fields(
        self,
        sample_id: str,
        representation_id: str,
        *,
        path: str | None = _UNSET,  # type: ignore[assignment]
        metadata: dict[str, Any] | None = _UNSET,  # type: ignore[assignment]
    ) -> None:
        """Update one or more of a representation's own fields in place, in a single write.

        Only the fields actually passed are changed -- `name`, `depends_on`,
        and every other field not accepted by this method is left untouched
        (use `rename_representation` to change `name`). `path` has no
        "clear" option since it's required. `metadata`, when passed,
        replaces the entire `[metadata]` table rather than merging into it
        -- callers that want to change one key should read the
        representation's current `metadata` first.

        Loads and re-validates the representation afterwards, so a call
        that would leave its TOML invalid fails loudly rather than silently
        corrupting the file.

        Args:
            sample_id: The owning sample's id.
            representation_id: The representation's stable id.
            path: The new filesystem path, or omitted to leave it unchanged.
            metadata: The new `metadata` table, replacing it wholesale, or
                omitted to leave it unchanged.
        """
        representation_path = self._find_representation_path(sample_id, representation_id)
        raw = _load_raw(representation_path)

        if path is not _UNSET:
            raw["path"] = path
        if metadata is not _UNSET:
            raw["metadata"] = metadata

        with representation_path.open("wb") as f:
            tomli_w.dump(raw, f)
        self.load_representation(sample_id, representation_id)
