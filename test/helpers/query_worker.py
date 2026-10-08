"""Deterministic subprocess fixture; never loads an audio backend."""

import sys
import time


def main() -> None:
    match sys.argv[1]:
        case 'invalid':
            while True:
                print('{"error": "not a device list"}', flush=True)
                time.sleep(0.01)
        case 'healthy':
            while True:
                print('[{"name":"Mic","max_input_channels":1}]', flush=True)
                time.sleep(0.01)
        case 'idle':
            time.sleep(60)
        case 'once_idle':
            print('[{"name":"Mic","max_input_channels":1}]', flush=True)
            time.sleep(60)
        case 'oversized':
            sys.stdout.write('x' * (2 * 1024 * 1024))
            sys.stdout.flush()
            time.sleep(60)


if __name__ == '__main__':
    main()
