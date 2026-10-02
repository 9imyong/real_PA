"""Operator-owned GPT-SoVITS raw PCM HTTP endpoint, independent of dialogue."""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
import os
import re
import time
from urllib.parse import urlsplit

from ..contracts import Capabilities, ConfigurationError, Event, InvalidOutput, ProviderUnavailable


class GptSovitsHttp:
    def __init__(self, config):
        self.config = config
        self.client = None
        options = config.options
        if config.role != 'tts' or options.keys() - {
                'url', 'sample_rate', 'ref_audio_path', 'prompt_text', 'prompt_lang', 'token_env'}:
            raise ConfigurationError('invalid GPT-SoVITS options')
        self.url = options.get('url', '')
        try:
            parsed = urlsplit(self.url)
            parsed.port
        except (TypeError, ValueError, AttributeError) as exc:
            raise ConfigurationError('invalid TTS endpoint') from exc
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ConfigurationError('invalid TTS endpoint')
        self.rate = options.get('sample_rate')
        if type(self.rate) is not int or self.rate not in {16000, 24000, 32000, 48000}:
            raise ConfigurationError('explicit TTS PCM sample rate required')
        reference = options.get('ref_audio_path')
        if not isinstance(reference, str) or not reference.strip() or '://' in reference:
            raise ConfigurationError('server-local reference audio path required')
        if not isinstance(options.get('prompt_text', ''), str) or options.get('prompt_lang', 'ko') != 'ko':
            raise ConfigurationError('invalid Korean reference prompt')
        name = options.get('token_env')
        if name is not None and (not isinstance(name, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name)):
            raise ConfigurationError('invalid credential variable')
        declared = config.capabilities
        if self.rate not in declared.sample_rates:
            raise ConfigurationError('TTS sample rate missing from model manifest')
        self.capabilities = Capabilities('tts', declared.features & {'phrase', 'chunks', 'cancel'},
                                        declared.languages & {'ko'}, declared.sample_rates & {self.rate})

    async def load(self):
        import httpx
        headers = {}
        name = self.config.options.get('token_env')
        if name:
            token = os.environ.get(name)
            if not token:
                raise ConfigurationError('missing TTS server credential')
            headers['X-API-Key'] = token
        self.client = httpx.AsyncClient(timeout=self.config.timeout, headers=headers,
                                       trust_env=False, follow_redirects=False)

    async def stream(self, request, context):
        if self.client is None or request.role != 'tts':
            raise ConfigurationError('TTS adapter is not ready')
        text = request.data.get('text')
        if not isinstance(text, str) or not text.strip():
            raise InvalidOutput('nonempty synthesis text required')
        self.capabilities.require({'phrase', 'chunks', 'cancel'})
        context.check()
        body = {'text': text, 'text_lang': 'ko', 'media_type': 'raw', 'streaming_mode': True,
                'ref_audio_path': self.config.options['ref_audio_path'],
                'prompt_text': self.config.options.get('prompt_text', ''), 'prompt_lang': 'ko'}
        size = self.rate * 2 * 40 // 1000
        pending = bytearray()
        sequence = 0
        try:
            import httpx
            async with asyncio.timeout(max(0.001, context.deadline - time.monotonic())):
                async with self._response(body, context) as response:
                    response.raise_for_status()
                    content_type = response.headers.get('content-type', '').split(';')[0].strip().lower()
                    if content_type not in {'audio/raw', 'application/octet-stream'}:
                        raise InvalidOutput('expected raw PCM TTS response')
                    # Chunk boundaries may split a PCM sample; keep at most one audio frame.
                    chunks = response.aiter_bytes(chunk_size=size).__aiter__()
                    while True:
                        try:
                            chunk = await self._read_next(chunks, context)
                        except StopAsyncIteration:
                            break
                        context.check()
                        pending.extend(chunk)
                        while len(pending) >= size:
                            context.check()
                            pcm = bytes(pending[:size])
                            del pending[:size]
                            yield Event('audio_chunk', {'pcm': pcm, 'sample_rate': self.rate, 'sequence': sequence})
                            sequence += 1
                    if len(pending) % 2:
                        raise InvalidOutput('truncated PCM sample')
                    if pending:
                        context.check()
                        yield Event('audio_chunk', {'pcm': bytes(pending), 'sample_rate': self.rate, 'sequence': sequence})
                        sequence += 1
                    if not sequence:
                        raise InvalidOutput('empty TTS audio')
            context.check()
            yield Event('completed')
        except httpx.HTTPError as exc:
            raise ProviderUnavailable('self-hosted TTS request failed') from exc

    @staticmethod
    async def _read_next(chunks, context):
        return await GptSovitsHttp._await_result(anext(chunks), context)

    @staticmethod
    async def _await_result(operation, context, cleanup=None):
        read = asyncio.create_task(operation)
        cancelled = asyncio.create_task(context.cancelled.wait())
        accepted = False
        try:
            context.check()
            await asyncio.wait({read, cancelled}, return_when=asyncio.FIRST_COMPLETED)
            # Cancellation wins even when an audio chunk becomes ready together.
            context.check()
            result = read.result()
            accepted = True
            return result
        finally:
            for task in (read, cancelled):
                if not task.done():
                    task.cancel()
            try:
                await asyncio.gather(read, cancelled, return_exceptions=True)
            except BaseException:
                if cleanup is not None and read.done() and not read.cancelled() and read.exception() is None:
                    await cleanup(read.result())
                raise
            if cleanup is not None and not accepted and not read.cancelled() and read.exception() is None:
                await cleanup(read.result())

    @asynccontextmanager
    async def _response(self, body, context):
        request = self.client.build_request('POST', self.url, json=body)
        response = await self._await_result(self.client.send(request, stream=True), context,
                                           cleanup=lambda response: response.aclose())
        try:
            yield response
        finally:
            await response.aclose()

    async def reset(self, session_id):
        return None

    async def close(self):
        if self.client is not None:
            await self.client.aclose()
            self.client = None
