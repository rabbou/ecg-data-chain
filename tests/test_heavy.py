"""The lock that replaced searching the process table."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ecgchain.heavy import held_by, holding


class TestHolding:
    def test_the_lock_exists_while_held_and_not_after(self, tmp_path: Path) -> None:
        with holding("sweep", "scan_quality.py", tmp_path) as path:
            assert path.exists()
        assert not path.exists()

    def test_the_lock_names_the_process_and_the_job(self, tmp_path: Path) -> None:
        with holding("sweep", "scan_quality.py", tmp_path) as path:
            payload = json.loads(path.read_text())
        assert payload["pid"] == os.getpid()
        assert payload["command"] == "scan_quality.py"

    def test_a_second_holder_is_refused(self, tmp_path: Path) -> None:
        with (
            holding("sweep", "first", tmp_path),
            pytest.raises(RuntimeError, match="already held by pid"),
            holding("sweep", "second", tmp_path),
        ):
            pass

    def test_a_failing_job_still_lets_go(self, tmp_path: Path) -> None:
        with pytest.raises(ZeroDivisionError), holding("sweep", "first", tmp_path):
            raise ZeroDivisionError
        assert held_by("sweep", tmp_path) is None

    def test_two_names_do_not_block_each_other(self, tmp_path: Path) -> None:
        with holding("sweep", "one", tmp_path), holding("build", "two", tmp_path):
            assert held_by("sweep", tmp_path) is not None
            assert held_by("build", tmp_path) is not None


class TestHeldBy:
    def test_nobody_holds_an_absent_lock(self, tmp_path: Path) -> None:
        assert held_by("sweep", tmp_path) is None

    def test_a_lock_left_by_a_dead_process_is_not_held(self, tmp_path: Path) -> None:
        """A job killed mid-pass must not block the next one for ever."""
        dead = _a_pid_that_is_not_running()
        (tmp_path / "sweep.lock").write_text(
            json.dumps({"name": "sweep", "pid": dead, "command": "killed"})
        )
        assert held_by("sweep", tmp_path) is None

    def test_a_dead_holder_is_taken_over(self, tmp_path: Path) -> None:
        dead = _a_pid_that_is_not_running()
        (tmp_path / "sweep.lock").write_text(
            json.dumps({"name": "sweep", "pid": dead, "command": "killed"})
        )
        with holding("sweep", "next", tmp_path) as path:
            assert json.loads(path.read_text())["pid"] == os.getpid()

    def test_a_lock_this_process_holds_reads_back_as_held(self, tmp_path: Path) -> None:
        with holding("sweep", "mine", tmp_path):
            held = held_by("sweep", tmp_path)
        assert held is not None
        assert held.pid == os.getpid()
        assert held.alive

    def test_an_unreadable_lock_is_not_held(self, tmp_path: Path) -> None:
        (tmp_path / "sweep.lock").write_text("not json")
        assert held_by("sweep", tmp_path) is None

    def test_the_lock_never_matches_the_reader_itself(self, tmp_path: Path) -> None:
        """What searching the process table for the script's name got wrong."""
        assert held_by("scan_quality", tmp_path) is None


def _a_pid_that_is_not_running() -> int:
    for candidate in range(4_000_000, 4_000_100):
        try:
            os.kill(candidate, 0)
        except ProcessLookupError:
            return candidate
        except PermissionError:
            continue
    raise RuntimeError("no free pid to test with")
