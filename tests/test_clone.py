import subprocess
from pathlib import Path

import pytest

from dataset_registry import open_registry
from dataset_registry._clone import _cache_dir_for


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_remote(tmp_path: Path, filename: str = "specimen.toml") -> Path:
    remote = tmp_path / "remote"
    remote.mkdir()
    _git(["init", "-q"], cwd=remote)
    _git(["config", "user.email", "test@example.com"], cwd=remote)
    _git(["config", "user.name", "Test"], cwd=remote)
    (remote / filename).write_text('name = "SLS161"\n')
    _git(["add", "-A"], cwd=remote)
    _git(["commit", "-q", "-m", "initial"], cwd=remote)
    _git(["symbolic-ref", "HEAD", "refs/heads/main"], cwd=remote)
    return remote


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    # Every test gets its own cache dir, so runs never share (or pollute)
    # the real user cache directory or each other's clones.
    monkeypatch.setattr(
        "dataset_registry._clone.user_cache_dir", lambda _app: str(tmp_path / "cache")
    )


def test_open_registry_yields_a_local_directory_directly(tmp_path):
    local = tmp_path / "local-registry"
    local.mkdir()
    (local / "specimen.toml").write_text('name = "SLS161"\n')

    with open_registry(local) as registry:
        assert registry.path == local
        assert registry.commit is None  # not a git repo


def test_open_registry_reports_commit_for_a_local_git_directory(tmp_path):
    remote = _init_remote(tmp_path)

    with open_registry(remote) as registry:
        assert registry.path == remote
        expected = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=remote, capture_output=True, text=True, check=True
        ).stdout.strip()
        assert registry.commit == expected


def test_open_registry_clones_a_git_url_into_the_cache(tmp_path):
    remote = _init_remote(tmp_path)

    with open_registry(remote.as_uri()) as registry:
        assert registry.path != remote
        assert (registry.path / "specimen.toml").read_text() == 'name = "SLS161"\n'
        assert registry.commit is not None


def test_open_registry_reuses_the_cache_and_picks_up_new_commits(tmp_path):
    remote = _init_remote(tmp_path)

    with open_registry(remote.as_uri()) as first:
        first_commit = first.commit

    (remote / "specimen.toml").write_text('name = "SLS161-updated"\n')
    _git(["commit", "-aqm", "update"], cwd=remote)

    with open_registry(remote.as_uri()) as second:
        assert second.path == first.path  # same cache directory reused
        assert second.commit != first_commit
        assert (second.path / "specimen.toml").read_text() == 'name = "SLS161-updated"\n'


def test_open_registry_falls_back_to_cache_on_fetch_failure(tmp_path, monkeypatch):
    remote = _init_remote(tmp_path)

    with open_registry(remote.as_uri()) as first:
        cached_path = first.path
        cached_commit = first.commit

    def _boom(*args, **kwargs):
        raise subprocess.SubprocessError("simulated network failure")

    monkeypatch.setattr("dataset_registry._clone._fetch_latest", _boom)

    with open_registry(remote.as_uri()) as second:
        assert second.path == cached_path
        assert second.commit == cached_commit


def test_open_registry_raises_when_no_cache_and_clone_fails(tmp_path):
    with pytest.raises(subprocess.CalledProcessError):
        with open_registry((tmp_path / "no-such-remote").as_uri()):
            pass


def test_cache_dir_for_is_stable_and_filesystem_safe(tmp_path):
    url = "https://github.com/example/weird?name=repo.git"
    first = _cache_dir_for(url)
    second = _cache_dir_for(url)

    assert first == second
    assert "/" not in first.name and "?" not in first.name
