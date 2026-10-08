"""Isolated PortAudio device discovery for long-running applications."""

import json
import subprocess
import sys
import time
from collections.abc import Sequence
from typing import cast

from reccy.device import DeviceDict

STREAM_INTERVAL = 0.1
DEVICE_QUERY_TIMEOUT = 5.0


def query_devices(command: Sequence[str] | None = None) -> list[DeviceDict]:
    """Query in isolation; failures raise rather than implying device absence."""
    command = command or [sys.executable, '-m', 'dvice.worker']
    result = subprocess.run(
        command,
        text=True,
        check=True,
        start_new_session=True,
        stdout=subprocess.PIPE,
        timeout=DEVICE_QUERY_TIMEOUT,
    )
    return _validate_devices(json.loads(result.stdout))


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
