"""Offline environment inspection without logging endpoints or credentials."""
import argparse
import importlib.util
import json
import pathlib
import shutil
import subprocess
from .config import read_config
from .contracts import ProviderError

def doctor():
    gpu = False
    if shutil.which('nvidia-smi'):
        result = subprocess.run(['nvidia-smi','--query-gpu=name,memory.total',
                                 '--format=csv,noheader'],capture_output=True,text=True,timeout=10)
        gpu = result.returncode == 0
    # A timer/control node alone does not provide PCM capture or playback.
    sound_nodes = pathlib.Path('/dev/snd')
    capture = any(sound_nodes.glob('pcm*C*D*c'))
    playback = any(sound_nodes.glob('pcm*C*D*p'))
    return {'gpu_accessible':gpu,'alsa_devices':capture or playback,
            'alsa_pcm_capture':capture, 'alsa_pcm_playback':playback,
            'modules':{name:importlib.util.find_spec(name) is not None
                       for name in ['httpx','websockets','sherpa_onnx','sounddevice']}}

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command',required=True)
    sub.add_parser('doctor')
    api = sub.add_parser('api')
    api.add_argument('path')
    api.add_argument('--host', default='127.0.0.1')
    api.add_argument('--port', type=int, default=18484)
    api.add_argument('--origin', action='append', default=[])
    check = sub.add_parser('check-config')
    check.add_argument('path')
    check.add_argument('--profile', choices=['worker', 'api', 'robot'], default='worker')
    worker = sub.add_parser('worker')
    worker.add_argument('path')
    worker.add_argument('--host',default='127.0.0.1')
    worker.add_argument('--port',type=int,default=18282)
    worker.add_argument('--token-env',default='REAL_PA_WORKER_TOKEN')
    robot = sub.add_parser('robot')
    robot.add_argument('path')
    robot.add_argument('--host',default='127.0.0.1')
    robot.add_argument('--port',type=int,default=18383)
    robot.add_argument('--token-env',default='REAL_PA_ROBOT_TOKEN')
    args = parser.parse_args()
    if args.command == 'doctor':
        print(json.dumps(doctor(),ensure_ascii=False,indent=2))
    elif args.command == 'api':
        import asyncio
        from .api import serve_api
        try:
            asyncio.run(serve_api(args.path, args.host, args.port, args.origin))
        except KeyboardInterrupt:
            pass
    elif args.command == 'robot':
        import asyncio
        from .worker import serve_robot
        try:
            asyncio.run(serve_robot(args.path,args.host,args.port,args.token_env))
        except KeyboardInterrupt:
            pass
    elif args.command == 'worker':
        import asyncio
        from .worker import serve_worker
        try:
            asyncio.run(serve_worker(args.path,args.host,args.port,args.token_env))
        except KeyboardInterrupt:
            pass
    else:
        try:
            configs = read_config(args.path)
            from .composition import registry
            from .api import REQUIREMENTS
            registry().validate(configs, REQUIREMENTS if args.profile in {'api', 'robot'} else None)
            print(json.dumps({'roles':sorted(configs),'validated':True,
                              'profile':args.profile,'model_load_performed':False}))
        except ProviderError as exc:
            parser.exit(2,exc.code+'\n')

if __name__ == '__main__':
    main()
