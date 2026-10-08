"""Internal child entry point for isolated PortAudio queries."""

import os
import sys
import threading

import tyro
from pydantic import BaseModel

from .discovery import devices_json, stream_devices


class QueryWorker(BaseModel, frozen=True):
    stream: bool = False
    watch_parent: bool = False


def main() -> None:
    args = tyro.cli(QueryWorker)
    if args.watch_parent:
        threading.Thread(
            target=_exit_when_parent_closes, daemon=True, name='ParentLifeline'
        ).start()
    if args.stream:
        stream_devices()
    else:
        print(devices_json())


def _exit_when_parent_closes() -> None:
    try:
        while os.read(sys.stdin.fileno(), 1):
            pass
    finally:
        # Native enumeration may be blocked; normal Python shutdown could wait on it.
        os._exit(0)


if __name__ == '__main__':
    main()
