"""Company inference worker, separate from robot-owned sessions and policy."""
import asyncio
import os
from .adapters.rpc import InferenceGateway
from .composition import registry
from .config import read_config
from .contracts import ConfigurationError


async def serve_worker(config_path, host, port, token_env):
    from websockets.asyncio.server import serve
    # Plain sockets are for loopback behind a TLS reverse proxy only.
    if host not in {'127.0.0.1','::1','localhost'}:
        raise ConfigurationError('worker binds loopback; use a TLS proxy for company access')
    token = os.environ.get(token_env)
    providers = await registry().build(read_config(config_path))
    try:
        gateway = InferenceGateway(providers,token)
        async with serve(gateway.handle,host,port,max_size=1024*1024,max_queue=8):
            await asyncio.Event().wait()
    finally:
        for provider in providers.values():
            await provider.close()


async def serve_robot(config_path, host, port, token_env):
    from websockets.asyncio.server import serve
    from .robot_gateway import RobotGateway
    if host not in {'127.0.0.1','::1','localhost'}:
        raise ConfigurationError('robot development endpoint binds loopback')
    requirements = {'llm':{'stream','cancel'},'stt':{'partial','final'},
                    'tts':{'chunks','cancel'},'kws':{'stream'},'vad':{'stream'}}
    providers = await registry().build(read_config(config_path),requirements)
    try:
        gateway = RobotGateway(providers,os.environ.get(token_env))
        async with serve(gateway.handle,host,port,max_size=65536,max_queue=8):
            await asyncio.Event().wait()
    finally:
        for provider in providers.values():
            await provider.close()
