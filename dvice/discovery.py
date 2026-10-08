"""Isolated PortAudio device discovery for long-running applications."""

import json
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from typing import cast

from .device import DeviceDict

STREAM_INTERVAL = 0.1
DEVICE_QUERY_TIMEOUT = 5.0
MAX_SNAPSHOT_BYTES = 1024 * 1024


def query_devices(command: Sequence[str] | None = None) -> list[DeviceDict]:
    """Query in isolation; failures raise rather than implying device absence."""
    command = command or [sys.executable, '-m', 'dvice.worker']
    process = subprocess.Popen(
        command,
        text=True,
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
    )
    output = bytearray()
    deadline = time.monotonic() + DEVICE_QUERY_TIMEOUT
    try:
        assert process.stdout is not None
        descriptor = process.stdout.fileno()
        os.set_blocking(descriptor, False)
        while True:
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(
                    command, DEVICE_QUERY_TIMEOUT, bytes(output)
                )
            try:
                chunk = os.read(descriptor, 65536)
            except BlockingIOError:
                time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
                continue
            if not chunk:
                break
            output.extend(chunk)
            if len(output) > MAX_SNAPSHOT_BYTES:
                raise ValueError('Device-query snapshot exceeds byte limit')
        returncode = process.wait(max(0.0, deadline - time.monotonic()))
        if returncode:
            raise subprocess.CalledProcessError(returncode, command, output.decode())
        return _validate_devices(json.loads(output))
    finally:
        try:
            if process.poll() is None:
                process.kill()
                process.wait(DEVICE_QUERY_TIMEOUT)
        finally:
            if process.stdout is not None:
                process.stdout.close()


def devices_json() -> str:
    return json.dumps(_query_devices(), indent=4)


def stream_devices() -> None:
    while True:
        print(json.dumps(_query_devices()), flush=True)
        time.sleep(STREAM_INTERVAL)


def _query_devices() -> list[DeviceDict]:
    import sounddevice

    return _validate_devices(list(sounddevice.query_devices()))


def _validate_devices(value: object) -> list[DeviceDict]:
    if not isinstance(value, list) or any(
        not isinstance(i, dict)
        or not isinstance(i.get('name'), str)
        or not i['name'].strip()
        or type(i.get('max_input_channels')) is not int
        or i['max_input_channels'] < 0
        or any(not isinstance(v, (str, int, float)) for v in i.values())
        for i in value
    ):
        raise ValueError('Malformed device-query snapshot')
    return cast(list[DeviceDict], value)
