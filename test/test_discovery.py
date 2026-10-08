import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import NoReturn

import pytest

from dvice import discovery


def test_query_failure_is_not_an_empty_device_list() -> None:
    with pytest.raises(subprocess.CalledProcessError):
        discovery.query_devices(helper_command('fail'))


def test_query_preserves_successful_empty_enumeration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}
    popen = subprocess.Popen

    def remember(*args: object, **kwargs: object) -> subprocess.Popen[str]:
        seen.update(kwargs)
        return popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, 'Popen', remember)
    assert discovery.query_devices(helper_command('output', '[]')) == []
    assert seen['start_new_session'] is True
    assert seen['stdin'] == subprocess.DEVNULL


def test_query_timeout_does_not_imply_absence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery, 'DEVICE_QUERY_TIMEOUT', 0.15)
    children: list[subprocess.Popen[str]] = []
    popen = subprocess.Popen

    def remember(*args: object, **kwargs: object) -> subprocess.Popen[str]:
        process = popen(*args, **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(subprocess, 'Popen', remember)
    with pytest.raises(subprocess.TimeoutExpired):
        discovery.query_devices(helper_command('idle'))
    assert children[0].poll() is not None
    assert children[0].stdout is not None and children[0].stdout.closed


def test_backend_failure_does_not_imply_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BackendError(RuntimeError):
        pass

    def fail() -> NoReturn:
        raise BackendError('audio service unavailable')

    monkeypatch.setitem(sys.modules, 'sounddevice', SimpleNamespace(query_devices=fail))
    with pytest.raises(BackendError):
        discovery.devices_json()


@pytest.mark.parametrize(
    'output',
    [
        '{}',
        'null',
        '[{"name":"Mic"}]',
        '[{"name":" ","max_input_channels":1}]',
        '[{"name":"Mic","max_input_channels":true}]',
        '[{"name":"Mic","max_input_channels":-1}]',
    ],
)
def test_query_rejects_invalid_device_protocol(output: str) -> None:
    with pytest.raises(ValueError, match='Malformed device-query snapshot'):
        discovery.query_devices(helper_command('output', output))


def test_query_accepts_multiline_json() -> None:
    output = '[\n  {"name":"Mic", "max_input_channels":1}\n]'
    assert discovery.query_devices(helper_command('output', output)) == [
        {'name': 'Mic', 'max_input_channels': 1},
    ]


def test_query_rejects_oversized_output_and_reaps_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    children: list[subprocess.Popen[str]] = []
    popen = subprocess.Popen

    def remember(*args: object, **kwargs: object) -> subprocess.Popen[str]:
        process = popen(*args, **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(subprocess, 'Popen', remember)
    with pytest.raises(ValueError, match='exceeds byte limit'):
        discovery.query_devices(helper_command('oversized'))
    assert children[0].poll() is not None
    assert children[0].stdout is not None and children[0].stdout.closed


def test_query_interrupt_cleans_up_before_propagating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    children: list[subprocess.Popen[str]] = []
    popen = subprocess.Popen

    def remember(*args: object, **kwargs: object) -> subprocess.Popen[str]:
        process = popen(*args, **kwargs)
        children.append(process)
        monkeypatch.setattr(discovery.os, 'read', interrupt)
        return process

    def interrupt(*args: object, **kwargs: object) -> NoReturn:
        raise KeyboardInterrupt

    monkeypatch.setattr(subprocess, 'Popen', remember)
    with pytest.raises(KeyboardInterrupt):
        discovery.query_devices(helper_command('idle'))
    assert children[0].poll() is not None
    assert children[0].stdout is not None and children[0].stdout.closed


def helper_command(mode: str, *args: str) -> list[str]:
    return [
        sys.executable,
        str(Path(__file__).parent / 'helpers/query_worker.py'),
        mode,
        *args,
    ]
