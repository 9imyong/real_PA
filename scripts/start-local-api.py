"""Launch the loopback conversation API without a credential."""
import argparse
import os
from pathlib import Path
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=root / 'config/local/worker.toml')
    parser.add_argument('--port', type=int, default=18484)
    parser.add_argument('--origin', action='append', default=[],
                        help='Allowed browser Origin, including the SSH client port; repeatable')
    args = parser.parse_args()
    if not args.config.is_file() or not 1 <= args.port <= 65535:
        parser.error('an existing configuration and valid port are required')
    command = [sys.executable, '-m', 'real_pa.cli', 'api', str(args.config.resolve()),
               '--host', '127.0.0.1', '--port', str(args.port)]
    print(f'Browser: http://localhost:{args.port}', flush=True)
    for origin in args.origin:
        command.extend(['--origin', origin])
    os.execv(sys.executable, command)


if __name__ == '__main__':
    main()
