import json
import logging
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from queue import Empty, Queue
from typing import IO

from reccy.device import DeviceDict
from threa import HasThread

from .discovery import DEVICE_QUERY_TIMEOUT, _validate_devices

STREAM_TIMEOUT = DEVICE_QUERY_TIMEOUT
RESTART_BACKOFF_SECONDS = 1.0
MAX_RESTART_BACKOFF_SECONDS = 30.0
LOGGER = logging.getLogger(__name__)


class DevicePoller(HasThread):
    def __init__(self, interval: float, command: Sequence[str] | None = None) -> None:
        self.snapshots: Queue[dict[str, DeviceDict]] = Queue(maxsize=1)
        self.query_stream = DeviceQueryStream(command)
        super().__init__(
            self.poll,
            looping=True,
            name='DevicePoller',
            post_delay=interval,
        )

    def start(self) -> None:
        self.query_stream.start()
        super().start()

    def stop(self) -> None:
        self.query_stream.stop()
        super().stop()

    def join(self, timeout: float | None = None) -> None:
        super().join(timeout)
        self.query_stream.stop()

    def poll(self) -> None:
        if (devices := self.query_stream.devices()) is None:
            return
        try:
            devices = _validate_devices(devices)
        except ValueError as error:
            LOGGER.warning('Ignoring device-query snapshot: %s', error)
            return
        snapshot = {
            str(info['name']): info for info in devices if info['max_input_channels']
        }
        _put_latest(self.snapshots, snapshot)

    def latest(self) -> dict[str, DeviceDict] | None:
        latest = None
        try:
            while True:
                latest = self.snapshots.get_nowait()
        except Empty:
            return latest


class DeviceQueryStream:
    def __init__(self, command: Sequence[str] | None = None) -> None:
        self.command = list(
            command or [sys.executable, '-m', 'dvice.worker', '--stream']
        )
        self.updates: Queue[list[DeviceDict]] = Queue(maxsize=1)
        self.process: subprocess.Popen[str] | None = None
        self.reader: threading.Thread | None = None
        self.last_update = time.monotonic()
        self.last_exitcode: int | None = None
        self.next_start = 0.0
        self.restart_backoff = RESTART_BACKOFF_SECONDS

    def start(self) -> None:
        if self.process is not None:
            return
        if time.monotonic() < self.next_start:
            return
        try:
            self.process = subprocess.Popen(
                self.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                start_new_session=True,
            )
        except OSError as error:
            LOGGER.warning('Cannot start device-query helper: %s', error)
            self.next_start = time.monotonic() + self.restart_backoff
            self.restart_backoff = min(
                MAX_RESTART_BACKOFF_SECONDS, 2 * self.restart_backoff
            )
            return
        self.last_update = time.monotonic()
        self.reader = threading.Thread(
            target=self._read,
            args=(self.process.stdout,),
            daemon=True,
            name='QueryDevices',
        )
        self.reader.start()

    def stop(self) -> None:
        if self.process is None:
            return
        process = self.process
        reader = self.reader
        process.terminate()
        try:
            process.wait(STREAM_TIMEOUT)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(STREAM_TIMEOUT)
            except subprocess.TimeoutExpired:
                LOGGER.error('Device-query helper did not exit after kill')
        if process.stdout is not None:
            process.stdout.close()
        if reader is not None:
            reader.join(STREAM_TIMEOUT)
        self.last_exitcode = process.poll()
        self.process = None
        self.reader = None

    def devices(self) -> list[DeviceDict] | None:
        latest = None
        try:
            while True:
                latest = self.updates.get_nowait()
        except Empty:
            pass
        if latest is not None:
            self.last_update = time.monotonic()
            self.next_start = 0.0
            self.restart_backoff = RESTART_BACKOFF_SECONDS
            return latest
        self.start()
        if self.process is None:
            return None
        if self._needs_restart():
            self.restart()
        return None

    def restart(self) -> None:
        self.stop()
        self.next_start = time.monotonic() + self.restart_backoff
        self.restart_backoff = min(
            MAX_RESTART_BACKOFF_SECONDS,
            2 * self.restart_backoff,
        )
        self.start()

    def _needs_restart(self) -> bool:
        if self.process is None or self.process.poll() is not None:
            return True
        return time.monotonic() - self.last_update > STREAM_TIMEOUT

    def _read(self, stream: IO[str] | None = None) -> None:
        if stream is None:
            stream = self.process.stdout if self.process is not None else None
        if stream is None:
            return
        try:
            for line in stream:
                try:
                    devices = _validate_devices(json.loads(line))
                except ValueError as error:
                    LOGGER.warning('Ignoring device-query snapshot: %s', error)
                    continue
                _put_latest(self.updates, devices)
        except (OSError, ValueError):
            return


def _put_latest[T](queue: Queue[T], value: T) -> None:
    try:
        while True:
            queue.get_nowait()
    except Empty:
        pass
    queue.put_nowait(value)
