import hashlib
import logging
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_cache_dir

_logger = logging.getLogger(__name__)

_CACHE_APP_NAME = "dataset-registry"


@dataclass(frozen=True)
class Registry:
    """A registry's local path, and the commit it's checked out at, if known."""

    path: Path
    """Local path to use as `registry_root` for `load_specimen`/`load_representation`."""

    commit: str | None
    """The full commit SHA this path is checked out at, for recording provenance.

    `None` when `path` isn't inside a git repository -- e.g. a local
    directory passed to `open_registry` directly, with no git history of
    its own.
    """


def _cache_dir_for(git_url: str) -> Path:
    # Keyed by a hash of the URL rather than the URL itself, so the cache
    # directory name is always filesystem-safe regardless of what characters
    # the URL contains.
    digest = hashlib.sha256(git_url.encode()).hexdigest()[:16]
    return Path(user_cache_dir(_CACHE_APP_NAME)) / digest


def _run_git(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
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


@contextmanager
def open_registry(location: str | Path) -> Iterator[Registry]:
    """Resolve a registry to a local path, whether it's a git URL or an existing local directory.

    If `location` is an existing local directory, yields it directly -- no
    cloning, no cache, no network -- which is both the simple common case
    (a registry already checked out locally, e.g. on a shared fileshare) and
    what keeps tests fast and network-free.

    Otherwise, treats `location` as a git URL: clones (or reuses a cached
    clone of) it under a per-user cache directory, keyed by `location`, as a
    shallow (`--depth=1`) clone. Always fetches and resets to the remote's
    default branch tip before yielding -- one network round-trip per `with`
    block, not per `load_specimen`/`load_representation` call inside it, so
    a caller that loads several representations from the same registry only
    pays for one fetch.

    If the fetch fails (e.g. no network) and a cached clone already exists,
    falls back to it with a warning rather than failing the whole block --
    better to segment against a possibly-stale registry than not run at all.
    If no cache exists yet and the clone fails, there's nothing to fall back
    to, so this raises.

    Args:
        location: Either an existing local directory, or a git URL
            cloneable with `git clone` (e.g.
            `"https://github.com/<owner>/<repo>.git"`).

    Yields:
        The registry's local path, and the commit it's checked out at (or
        `None` if `location` was a local directory with no git history).

    Raises:
        subprocess.CalledProcessError: If `location` is a git URL, no cache
            exists yet, and the initial clone fails.
    """
    local_path = Path(location)
    if local_path.is_dir():
        yield Registry(path=local_path, commit=_current_commit(local_path))
        return

    git_url = str(location)
    cache_dir = _cache_dir_for(git_url)

    if not cache_dir.is_dir():
        _clone(git_url, cache_dir)
    else:
        try:
            _fetch_latest(cache_dir)
        except (OSError, subprocess.SubprocessError) as e:
            _logger.warning(
                "could not fetch latest for %s (%s); using cached clone at %s, which may be stale",
                git_url,
                e,
                cache_dir,
            )

    yield Registry(path=cache_dir, commit=_current_commit(cache_dir))
