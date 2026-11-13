"""Subprocess execution; stdout is reserved for the phase result, so child output goes to stderr."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import BinaryIO


class Runner:
    def run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        input_data: bytes | str | None = None,
        capture: bool = True,
        check: bool = True,
        text: bool = True,
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            command,
            cwd=cwd,
            env=env,
            input=input_data,
            stdin=subprocess.DEVNULL if input_data is None else None,
            stdout=subprocess.PIPE if capture else sys.stderr,
            stderr=subprocess.PIPE if capture else None,
            check=check,
            text=text,
        )

    def to_file(
        self,
        command: list[str],
        destination: BinaryIO,
        *,
        cwd: Path | None = None,
    ) -> None:
        subprocess.run(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=destination,
            check=True,
        )

    def from_file(
        self,
        command: list[str],
        source: BinaryIO,
        *,
        cwd: Path | None = None,
        discard_stdout: bool = False,
    ) -> None:
        subprocess.run(
            command,
            cwd=cwd,
            stdin=source,
            stdout=subprocess.DEVNULL if discard_stdout else sys.stderr,
            check=True,
        )
