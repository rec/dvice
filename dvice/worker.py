"""Internal child entry point for isolated PortAudio queries."""

import tyro
from pydantic import BaseModel

from .discovery import devices_json, stream_devices


class QueryWorker(BaseModel, frozen=True):
    stream: bool = False


def main() -> None:
    args = tyro.cli(QueryWorker)
    if args.stream:
        stream_devices()
    else:
        print(devices_json())


if __name__ == '__main__':
    main()
