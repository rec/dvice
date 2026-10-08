import json
import logging
import math
import os
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from queue import Empty, Queue
from typing import IO

from reccy.device import DeviceDict
from threa import HasThread

from .discovery import DEVICE_QUERY_TIMEOUT, MAX_SNAPSHOT_BYTES, _validate_devices

STREAM_TIMEOUT = DEVICE_QUERY_TIMEOUT
RESTART_BACKOFF_SECONDS = 1.0
MAX_RESTART_BACKOFF_SECONDS = 30.0
LOGGER = logging.getLogger(__name__)


class DevicePoller(HasThread):
    """Single-use polling thread; latest() consumes pending input-device data."""

    def __init__(self, interval: float, command: Sequence[str] | None = None) -> None:
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError('interval must be finite and positive')
        self.snapshots: Queue[dict[str, DeviceDict]] = Queue(maxsize=1)
        self.query_stream = DeviceQueryStream(command)
        self._interval = interval
        self._stop_requested = threading.Event()
        self._poll_lock = threading.RLock()
        super().__init__(self._poll_and_wait, looping=True, name='DevicePoller')

    def start(self) -> None:
        with self._poll_lock:
            if self.thread.ident is not None or self._stop_requested.is_set():
                raise RuntimeError('DevicePoller threads can only be started once')
            self.query_stream.start()
            try:
                super().start()
            except (RuntimeError, MemoryError):
                self.stop()
                raise

    def stop(self) -> None:
        self._stop_requested.set()
        super().stop()
        with self._poll_lock:
            self.query_stream.stop()
            _take_latest(self.snapshots)

    def join(self, timeout: float | None = None) -> None:
        """Wait only for the polling thread; call stop() before joining."""
        super().join(timeout)

    def poll(self) -> None:
        with self._poll_lock:
            if self._stop_requested.is_set():
                return
            if (devices := self.query_stream.devices()) is None:
                return
            try:
                devices = _validate_devices(devices)
            except ValueError as error:
                LOGGER.warning('Ignoring device-query snapshot: %s', error)
                return
            snapshot = {str(i['name']): i for i in devices if i['max_input_channels']}
            _put_latest(self.snapshots, snapshot)

    def latest(self) -> dict[str, DeviceDict] | None:
        with self._poll_lock:
            return _take_latest(self.snapshots)

    def _poll_and_wait(self) -> None:
        if self._stop_requested.is_set():
            super().stop()
            return
        self.poll()
        self._stop_requested.wait(self._interval)


class DeviceQueryStream:
    """Serialized helper lifecycle with latest-only, receipt-timed updates."""

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
        self._lock = threading.RLock()
        self._updates_lock = threading.Lock()
        self._reader_stop = threading.Event()
        self._stopped = False
        self._healthy_since: float | None = None

    def start(self) -> None:
        """Enable queries and start a helper if its backoff has elapsed."""
        with self._lock:
            self._stopped = False
            if self.process is not None or time.monotonic() < self.next_start:
                return
            try:
                process = subprocess.Popen(
                    self.command,
                    stdout=subprocess.PIPE,
                    stderr=None,
                    stdin=subprocess.DEVNULL,
                    text=True,
                    start_new_session=True,
                )
            except OSError as error:
                LOGGER.warning('Cannot start device-query helper: %s', error)
                self._backoff()
                return
            self.process = process
            with self._updates_lock:
                _take_latest(self.updates)
                self.last_update = time.monotonic()
                self._healthy_since = None
                self._reader_stop = threading.Event()
            try:
                self.reader = threading.Thread(
                    target=self._read,
                    args=(process.stdout, self._reader_stop),
                    daemon=True,
                    name='QueryDevices',
                )
                self.reader.start()
            except (RuntimeError, MemoryError):
                self._close()
                self._backoff()
                raise

    def stop(self) -> None:
        """Disable implicit starts; cleanup has a STREAM_TIMEOUT budget."""
        with self._lock:
            self._stopped = True
            self._close()

    def devices(self) -> list[DeviceDict] | None:
        with self._lock:
            if self._stopped:
                return None
            self.start()
            if self.process is None:
                return None
            if self._needs_restart():
                self.restart()
                return None
            with self._updates_lock:
                if (
                    self._healthy_since is not None
                    and self.last_update - self._healthy_since >= STREAM_TIMEOUT
                ):
                    self.next_start = 0.0
                    self.restart_backoff = RESTART_BACKOFF_SECONDS
                return _take_latest(self.updates)

    def restart(self) -> None:
        """Schedule replacement with backoff; stop() disables automatic retries."""
        with self._lock:
            if self._stopped:
                return
            self._close()
            self._backoff()

    def _close(self) -> None:
        deadline = time.monotonic() + STREAM_TIMEOUT
        with self._updates_lock:
            self._reader_stop.set()
            _take_latest(self.updates)
            self._healthy_since = None
        if (process := self.process) is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(max(0.0, (deadline - time.monotonic()) / 2))
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(max(0.0, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    LOGGER.error('Device-query helper did not exit after kill')
        if (reader := self.reader) is not None and reader.ident is not None:
            reader.join(max(0.0, deadline - time.monotonic()))
        elif process.stdout is not None:
            process.stdout.close()
        self.last_exitcode = process.poll()
        if self.last_exitcode is None or (reader is not None and reader.is_alive()):
            LOGGER.error('Retaining device-query helper until cleanup completes')
            return
        self.process = None
        self.reader = None

    def _backoff(self) -> None:
        self.next_start = time.monotonic() + self.restart_backoff
        self.restart_backoff = min(
            MAX_RESTART_BACKOFF_SECONDS, 2 * self.restart_backoff
        )

    def _needs_restart(self) -> bool:
        if self.process is None or self.process.poll() is not None:
            LOGGER.warning(
                'Device-query helper exited: %s',
                self.process.poll() if self.process is not None else self.last_exitcode,
            )
            return True
        with self._updates_lock:
            if time.monotonic() - self.last_update > STREAM_TIMEOUT:
                LOGGER.warning('Device-query helper stopped supplying valid updates')
                return True
        return False

    def _read(self, stream: IO[str] | None, stop: threading.Event) -> None:
        if stream is None:
            return
        pending = bytearray()
        try:
            descriptor = stream.fileno()
            os.set_blocking(descriptor, False)
            while not stop.is_set():
                try:
                    chunk = os.read(descriptor, 65536)
                except BlockingIOError:
                    stop.wait(0.01)
                    continue
                if not chunk:
                    return
                pending.extend(chunk)
                while (end := pending.find(b'\n')) >= 0:
                    if end > MAX_SNAPSHOT_BYTES:
                        raise ValueError('Device-query snapshot exceeds byte limit')
                    devices = _validate_devices(json.loads(pending[:end]))
                    del pending[: end + 1]
                    with self._updates_lock:
                        if stop.is_set():
                            return
                        now = time.monotonic()
                        if (
                            self._healthy_since is None
                            or now - self.last_update > STREAM_TIMEOUT
                        ):
                            self._healthy_since = now
                        self.last_update = now
                        _put_latest(self.updates, devices)
                if len(pending) > MAX_SNAPSHOT_BYTES:
                    raise ValueError('Device-query snapshot exceeds byte limit')
        except (OSError, ValueError) as error:
            LOGGER.warning('Device-query reader failed: %s', error)
        finally:
            stream.close()


def _put_latest[T](queue: Queue[T], value: T) -> None:
    """Replace a value; callers serialize producers and consumers."""
    _take_latest(queue)
    queue.put_nowait(value)


def _take_latest[T](queue: Queue[T]) -> T | None:
    latest = None
    try:
        while True:
            latest = queue.get_nowait()
    except Empty:
        return latest
