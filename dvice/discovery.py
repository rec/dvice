"""Isolated PortAudio device discovery for long-running applications."""

import json
import subprocess
import sys
import time
from collections.abc import Sequence
from typing import Any, cast

from reccy.device import DeviceDict

STREAM_INTERVAL = 0.1
DEVICE_QUERY_TIMEOUT = 5.0


def query_devices(command: Sequence[str] | None = None) -> list[DeviceDict]:
    command = command or [sys.executable, '-m', 'dvice.worker']
    try:
        result = subprocess.run(
            command,
            text=True,
            check=True,
            start_new_session=True,
            stdout=subprocess.PIPE,
            timeout=DEVICE_QUERY_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return []
    return cast(list[DeviceDict], json.loads(result.stdout))


def devices_json() -> str:
    return json.dumps(_query_devices(), indent=4)


def stream_devices() -> None:
    while True:
        print(json.dumps(_query_devices()), flush=True)
        time.sleep(STREAM_INTERVAL)


def _query_devices() -> Any:
    import sounddevice

    try:
        return sounddevice.query_devices()
    except sounddevice.PortAudioError:
        return []
