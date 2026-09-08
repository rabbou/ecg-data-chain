"""One heavy pass at a time, and a witness anyone can read.

The corpora are 53 GB on a box with 15 GiB of memory, so the rule is one heavy
job at a time under a capped scope.  Enforcing it by looking for the job in the
process table does not work: a search for the script's name matches the very
shell that is doing the searching, so the watcher waits for itself forever.

A lock file says the same thing without the ambiguity.  It holds the process
id and what the job is, it is removed when the job ends however it ends, and a
lock left behind by a process that is gone is taken over rather than obeyed.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

__all__ = ["Held", "LOCKS", "held_by", "holding"]

LOCKS = Path(__file__).resolve().parents[2] / "results" / "cache" / "locks"


@dataclass(frozen=True)
class Held:
    """What a lock file says."""

    name: str
    pid: int
    command: str

    @property
    def alive(self) -> bool:
        """Whether the process that wrote this lock still exists."""
        try:
            os.kill(self.pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # someone else's process, so it is running
        return True


def held_by(name: str, locks: Path | None = None) -> Held | None:
    """Who holds this lock, or None when nobody does.

    A lock whose process is gone is not held: a job killed mid-pass must not
    block the next one for ever.
    """
    path = (locks or LOCKS) / f"{name}.lock"
    try:
        payload = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    held = Held(str(payload["name"]), int(payload["pid"]), str(payload["command"]))
    return held if held.alive else None


@contextmanager
def holding(name: str, command: str = "", locks: Path | None = None) -> Iterator[Path]:
    """Hold the named lock for the duration, or refuse to start.

    Raises when another live process holds it, so a second heavy pass says so
    instead of running beside the first.
    """
    directory = locks or LOCKS
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.lock"
    other = held_by(name, directory)
    if other is not None:
        raise RuntimeError(
            f"{name} is already held by pid {other.pid} ({other.command or 'no command'})"
        )
    path.write_text(json.dumps({"name": name, "pid": os.getpid(), "command": command}))
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)
