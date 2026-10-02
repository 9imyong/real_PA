"""Duplex transport; production identity is established by Lemmy."""
import asyncio
import contextlib
import json
import secrets
import re
import uuid
import math
from .adapters.rpc import encode
from .robot import RobotRuntime
from .session import DialogueSession
from .speech_controls import utterance_control


async def run_connection(ws, providers, session_id, *, ui_started=False, authorize=None,
                         idle_timeout=None):
    """Run an already authenticated connection with a server-owned session ID.

    ``authorize`` must revalidate the original user/binding, never a client field.
    Its failure terminates capture and generation, including an idle connection.
    The websocket facade supplies recv, send, close, and async iteration.
    """
    session = DialogueSession(session_id, providers['llm'], providers['tts'], timeout=60)
    runtime = RobotRuntime(session, providers)
    tasks = []
    if idle_timeout is not None and (not math.isfinite(idle_timeout) or idle_timeout <= 0):
        raise ValueError('idle timeout must be finite and positive')
    last_activity = asyncio.get_running_loop().time()

    async def check_identity():
        if authorize is not None and not await authorize():
            raise PermissionError('connection identity expired')

    async def receive():
        nonlocal last_activity
        async for message in ws:
            if len(message) > 65536:
                raise ValueError('robot message too large')
            await check_identity()
            last_activity = asyncio.get_running_loop().time()
            if isinstance(message, bytes):
                runtime.accept_audio(message)
                continue
            command = json.loads(message)
            if not isinstance(command, dict):
                raise ValueError('invalid robot command')
            kind = command.get('type')
            if kind == 'interrupt':
                await session.interrupt()
            elif kind == 'input_reset':
                input_id = command.get('input_id')
                if input_id is not None and (type(input_id) is not int or not 0 <= input_id <= 9007199254740991):
                    raise ValueError('invalid input identifier')
                await runtime.reset_input(input_id=input_id)
            elif kind == 'listen':
                await session.interrupt()
                runtime.awake = True
                runtime.pre_roll.clear()
            elif kind == 'playback_ack':
                generation, chunk = command.get('generation_id'), command.get('chunk_id')
                if type(generation) is not int or type(chunk) is not int:
                    raise ValueError('invalid playback acknowledgement')
                session.acknowledge(generation, chunk)
            elif kind == 'text_ack':
                generation = command.get('generation_id')
                if type(generation) is not int:
                    raise ValueError('invalid text acknowledgement')
                session.acknowledge_text(generation)
            elif kind == 'text':
                text = command.get('text', '')
                if not isinstance(text, str) or len(text) > 4000:
                    raise ValueError('invalid text')
                output_audio = command.get('output_audio', True)
                if type(output_audio) is not bool:
                    raise ValueError('invalid output mode')
                request_id = command.get('request_id', str(uuid.uuid4()))
                if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,64}', request_id):
                    raise ValueError('invalid request identifier')
                if utterance_control(text) == 'interrupt':
                    await session.interrupt()
                else:
                    await runtime.reset_input()
                    await session.submit(text, metadata={'request_id': request_id, 'source': 'text',
                                                         'output_audio': output_audio})
            elif kind == 'close':
                return
            else:
                raise ValueError('unsupported robot message')

    async def send():
        nonlocal last_activity
        while True:
            generation, event = await session.next_event()
            await ws.send(json.dumps({'type': event.kind, 'generation_id': generation,
                                      'data': encode(event.data)}))
            last_activity = asyncio.get_running_loop().time()

    async def watch_idle():
        while True:
            remaining = idle_timeout - (asyncio.get_running_loop().time() - last_activity)
            if remaining <= 0:
                await ws.close(4000, 'session idle timeout')
                return
            await asyncio.sleep(remaining)

    async def watch_identity():
        while True:
            await asyncio.sleep(1)
            await check_identity()

    try:
        await check_identity()
        await runtime.start(ui_started=ui_started)
        await ws.send(json.dumps({'type': 'session_started', 'session_id': session_id}))
        tasks = [asyncio.create_task(receive()), asyncio.create_task(send()), runtime.running]
        if authorize is not None:
            tasks.append(asyncio.create_task(watch_identity()))
        if idle_timeout is not None:
            tasks.append(asyncio.create_task(watch_idle()))
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            await task
    except PermissionError:
        await ws.close(4401, 'authentication required')
    except asyncio.CancelledError:
        raise
    except Exception:
        with contextlib.suppress(Exception):
            await ws.send(json.dumps({'type': 'error', 'data': {'code': 'robot_session_failed'}}))
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await runtime.close()


class RobotGateway:
    """Loopback development gateway; its token grants no Lemmy tool access."""
    def __init__(self, providers, token, *, idle_timeout=None):
        if not token or len(token) < 16:
            raise ValueError('robot credential must have at least 16 characters')
        self.providers = providers
        self.token = token
        self.idle_timeout = idle_timeout

    async def handle(self, ws):
        try:
            raw = await asyncio.wait_for(ws.recv(), 10)
            if not isinstance(raw, str) or len(raw) > 4096:
                raise ValueError('invalid start')
            hello = json.loads(raw)
            if not isinstance(hello, dict) or hello.get('type') != 'start':
                raise ValueError('invalid start')
            if not secrets.compare_digest(str(hello.get('token', '')), self.token):
                raise ValueError('invalid credential')
            if type(hello.get('ui_started', False)) is not bool:
                raise ValueError('invalid start mode')
        except asyncio.CancelledError:
            raise
        except Exception:
            await ws.close(1008, 'authentication required')
            return
        await run_connection(ws, self.providers, str(uuid.uuid4()),
                             ui_started=hello.get('ui_started', False), idle_timeout=self.idle_timeout)
