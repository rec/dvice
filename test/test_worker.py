import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from dvice import poller


def test_one_shot_worker_exits_normally_with_lifeline_still_open() -> None:
    process = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).parent / 'helpers/parent_worker.py'),
            '--watch-parent',
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.wait(5) == 0
        assert process.stdout is not None
        assert process.stdout.read() == '[]\n'
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(3)
        if process.stdin is not None:
            process.stdin.close()
        if process.stdout is not None:
            process.stdout.close()


@pytest.mark.parametrize('parent_exit', ['terminate', 'kill'])
def test_blocked_worker_exits_after_abrupt_parent_exit(parent_exit: str) -> None:
    host = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).parent / 'helpers/parent_worker.py'),
            'host',
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        # EOF on the inherited stdout requires both host and worker to exit.
        assert host.stdout is not None
        descriptor = host.stdout.fileno()
        os.set_blocking(descriptor, False)
        ready = bytearray()
        deadline = time.monotonic() + 5
        while b'[]\n' not in ready and time.monotonic() < deadline:
            try:
                ready.extend(os.read(descriptor, 1024))
            except BlockingIOError:
                time.sleep(0.01)
        assert ready == b'[]\n'
        os.set_blocking(descriptor, True)
        getattr(host, parent_exit)()
        output, _ = host.communicate(timeout=3)
        assert output == ''
    finally:
        if host.poll() is None:
            host.kill()
        host.communicate(timeout=3)


def test_builtin_stream_passes_lifeline_and_exits_when_it_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    popen = subprocess.Popen
    seen: dict[str, object] = {}

    def remember(command: list[str], **kwargs: object) -> subprocess.Popen[str]:
        seen['command'] = command
        seen.update(kwargs)
        return popen(
            [
                sys.executable,
                str(Path(__file__).parent / 'helpers/parent_worker.py'),
                *command[3:],
            ],
            **kwargs,
        )

    monkeypatch.setattr(poller.subprocess, 'Popen', remember)
    stream = poller.DeviceQueryStream()
    try:
        stream.start()
        assert stream.process is not None and stream.process.stdin is not None
        assert '--watch-parent' in str(seen['command'])
        assert seen['stdin'] == subprocess.PIPE
        deadline = time.monotonic() + 5
        while stream.updates.empty() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not stream.updates.empty()
        stream.process.stdin.close()
        assert stream.process.wait(3) == 0
    finally:
        stream.stop()


def test_builtin_queries_hold_parent_lifeline(monkeypatch: pytest.MonkeyPatch) -> None:
    from dvice import discovery

    seen: dict[str, object] = {}
    popen = subprocess.Popen

    def remember(command: list[str], **kwargs: object) -> subprocess.Popen[str]:
        seen['command'] = command
        seen.update(kwargs)
        return popen(
            [
                sys.executable,
                str(Path(__file__).parent / 'helpers/query_worker.py'),
                'output',
                '[]',
            ],
            **kwargs,
        )

    monkeypatch.setattr(discovery.subprocess, 'Popen', remember)
    assert discovery.query_devices() == []
    assert '--watch-parent' in str(seen['command'])
    assert seen['stdin'] == subprocess.PIPE
