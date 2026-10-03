import subprocess
from typing import Any, NoReturn

import pytest

from dvice import discovery


def test_query_failure_is_not_an_empty_device_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = subprocess.CalledProcessError(1, ['dvice'])

    def fail(*args: Any, **kwargs: Any) -> NoReturn:
        raise error

    monkeypatch.setattr(subprocess, 'run', fail)

    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        discovery.query_devices()

    assert exc_info.value is error


def test_query_does_not_receive_terminal_interrupts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kwargs: dict[str, Any] = {}

    def run(*args: Any, **run_kwargs: Any) -> subprocess.CompletedProcess[str]:
        kwargs.update(run_kwargs)
        return subprocess.CompletedProcess(args, 0, stdout='[]')

    monkeypatch.setattr(subprocess, 'run', run)

    assert discovery.query_devices() == []
    assert kwargs['start_new_session'] is True
    assert kwargs['timeout'] == discovery.DEVICE_QUERY_TIMEOUT


def test_query_timeout_is_empty_device_list(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(*args: Any, **kwargs: Any) -> NoReturn:
        raise subprocess.TimeoutExpired(['dvice'], timeout=5)

    monkeypatch.setattr(subprocess, 'run', timeout)

    assert discovery.query_devices() == []
