"""Audio-free host and blocked built-in-worker fixture."""

import subprocess
import sys
import threading
import time
from pathlib import Path

from dvice import worker


def blocked_query() -> None:
    print('[]', flush=True)
    threading.Event().wait()


def empty_query() -> str:
    return '[]'


def main() -> None:
    if sys.argv[1] == 'host':
        process = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                '--watch-parent',
                '--stream',
            ],
            stdin=subprocess.PIPE,
        )
        try:
            time.sleep(60)
        finally:
            if process.stdin is not None:
                process.stdin.close()
            process.wait(3)
    else:
        worker.stream_devices = blocked_query
        worker.devices_json = empty_query
        worker.main()


if __name__ == '__main__':
    main()
