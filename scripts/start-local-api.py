"""Launch the loopback browser with a reusable, unlogged local credential."""
import argparse
import os
from pathlib import Path
import secrets
import stat
import sys


def local_token(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError('local credential must be an owner-only regular file')
            token = handle.read(4097).strip()
            if not 16 <= len(token) <= 4096:
                raise ValueError('invalid local credential length')
            return token
    else:
        token = secrets.token_urlsafe(32)
        with os.fdopen(fd, 'w') as handle:
            handle.write(token + '\n')
        return token


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
    path = root / 'config/local/browser.token'
    try:
        token = os.environ.get('REAL_PA_API_TOKEN')
        if token is None:
            token = local_token(path)
            source = str(path)
        else:
            source = 'existing REAL_PA_API_TOKEN environment variable'
        if len(token) < 16:
            raise ValueError('credential must contain at least 16 characters')
    except (OSError, ValueError):
        parser.error('local credential unavailable; check its length, ownership and file permissions')
    os.environ['REAL_PA_API_TOKEN'] = token
    print(f'Browser: http://localhost:{args.port}\nCredential source: {source}', flush=True)
    command = [sys.executable, '-m', 'real_pa.cli', 'api',
               str(args.config.resolve()), '--host', '127.0.0.1', '--port', str(args.port)]
    for origin in args.origin:
        command.extend(['--origin', origin])
    os.execv(sys.executable, command)


if __name__ == '__main__':
    main()
