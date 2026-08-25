from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ai_container.paths import (
    HomeDirectoryWorkdirError,
    map_to_container_path,
    resolve_target_workdir,
)

HOST_HOME = Path("/home/alice")
CONTAINER_HOME = Path("/home/coder")


def test_maps_path_under_home() -> None:
    result = map_to_container_path(
        HOST_HOME / "external/ai-container", host_home=HOST_HOME, container_home=CONTAINER_HOME
    )
    assert result == CONTAINER_HOME / "external/ai-container"


def test_leaves_path_outside_home_untouched() -> None:
    outside = Path("/srv/repos/thing")
    assert (
        map_to_container_path(outside, host_home=HOST_HOME, container_home=CONTAINER_HOME)
        == outside
    )


def test_home_itself_maps_to_container_home() -> None:
    assert (
        map_to_container_path(HOST_HOME, host_home=HOST_HOME, container_home=CONTAINER_HOME)
        == CONTAINER_HOME
    )


def test_does_not_false_positive_on_sibling_with_shared_prefix() -> None:
    """`/home/alice2` must not be treated as being under `/home/alice`."""
    sibling = Path("/home/alice2/project")
    assert (
        map_to_container_path(sibling, host_home=HOST_HOME, container_home=CONTAINER_HOME)
        == sibling
    )


def test_resolve_target_workdir_refuses_home() -> None:
    with pytest.raises(HomeDirectoryWorkdirError):
        resolve_target_workdir(HOST_HOME, host_home=HOST_HOME, container_home=CONTAINER_HOME)


def test_resolve_target_workdir_maps_subdirectory() -> None:
    cwd = HOST_HOME / "code" / "proj"
    result = resolve_target_workdir(cwd, host_home=HOST_HOME, container_home=CONTAINER_HOME)
    assert result == CONTAINER_HOME / "code/proj"


@given(st.lists(st.sampled_from(["a", "b", "c", "d e"]), max_size=5))
def test_mapping_then_remapping_relative_part_round_trips(parts: list[str]) -> None:
    """Whatever the sub-path under host_home is, it reappears unchanged
    under container_home."""
    cwd = HOST_HOME.joinpath(*parts) if parts else HOST_HOME
    result = map_to_container_path(cwd, host_home=HOST_HOME, container_home=CONTAINER_HOME)
    assert result.relative_to(CONTAINER_HOME) == cwd.relative_to(HOST_HOME)
