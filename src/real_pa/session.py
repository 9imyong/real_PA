"""Robot-owned conversation control with concurrent capture and generation."""
from __future__ import annotations
import asyncio
import contextlib
import json
import uuid
from .contracts import Context, Event, Request, ProviderError, ResourceExhausted, ContextCapacityExceeded

class DialogueSession:
    def __init__(self, session_id, llm, tts, *, timeout=30.0, max_output=32,
                 max_history=40):
        self.session_id = session_id
        self.llm, self.tts = llm, tts
        self.timeout = timeout
        self.output = asyncio.Queue(maxsize=max_output)
        self.generation = 0
        self.turn = 0
        self.task = None
        self.retired_tasks = set()
        self.context = None
        self.closed = False
        self.history = []
        self.max_history = max_history
        self.pending_audio = {}
        self.heard = []
        self.pending_text = ''
        self.displayed_text = ''
        self.chunk_id = 0
        self.control = asyncio.Lock()
        self.ack_event = asyncio.Event()
        self.max_pending_audio = max_output

    async def submit(self, text, *, metadata=None):
        if not text.strip():
            return
        async with self.control:
            if self.closed:
                raise RuntimeError('session is closed')
            await self._interrupt()
            if len(self.retired_tasks) >= 8:
                raise ResourceExhausted('too many pending cancellations')
            self.turn += 1
            user_message = {'role':'user','content':text.strip()}
            self.history.append(user_message)
            self.history = self.history[-self.max_history:]
            # A cutoff must not leave a tool result without its assistant call.
            while self.history and self.history[0]['role'] == 'tool':
                self.history.pop(0)
            self.context = Context(self.session_id,self.turn,self.generation,self.timeout)
            local = dict(metadata or {})
            local.setdefault('request_id', str(uuid.uuid4()))
            self.task = asyncio.create_task(self._generate(self.context, local, user_message))

    async def interrupt(self):
        async with self.control:
            if not self.closed:
                await self._interrupt()

    async def _interrupt(self):
        self.generation += 1
        self.ack_event.set()
        while not self.output.empty():
            self.output.get_nowait()
        self.output.put_nowait((self.generation,Event('interrupted')))
        if self.context:
            self.context.cancelled.set()
        if self.task:
            task = self.task
            task.cancel()
            self.retired_tasks.add(task)
            def finished(done):
                self.retired_tasks.discard(done)
                if not done.cancelled():
                    done.exception()
            task.add_done_callback(finished)
            self.task = None
            # Deliver cancellation, but don't block capture on native inference.
            await asyncio.sleep(0)
        # Commit only audio that the playback sink acknowledged in full.
        if self.heard or self.displayed_text:
            self.history.append({'role':'assistant','content':''.join(self.heard) + self.displayed_text})
        self.heard.clear()
        self.pending_text = self.displayed_text = ''
        self.pending_audio.clear()

    def acknowledge(self, generation, chunk_id):
        if generation != self.generation:
            return False
        # Out-of-order acknowledgements cannot manufacture heard dialogue.
        first = next(iter(self.pending_audio),None)
        if chunk_id != first:
            return False
        text = self.pending_audio.pop(chunk_id)
        self.ack_event.set()
        if text:
            self.heard.append(text)
        return True

    async def _emit(self, context, event):
        context.check()
        if context.generation_id != self.generation or self.closed:
            return
        try:
            await asyncio.wait_for(self.output.put((context.generation_id,event)),
                                   min(1.0,max(.001,context.deadline-__import__('time').monotonic())))
        except TimeoutError as exc:
            raise ResourceExhausted('robot output queue is full') from exc
        context.check()
        if context.generation_id != self.generation:
            raise asyncio.CancelledError

    def acknowledge_text(self, generation):
        if generation != self.generation or not self.pending_text or self.closed:
            return False
        self.displayed_text = self.pending_text
        self.pending_text = ''
        return True

    async def _audio_slot(self, context):
        context.check()
        while len(self.pending_audio) >= self.max_pending_audio:
            self.ack_event.clear()
            await self.ack_event.wait()
            context.check()

    async def _llm_events(self, context, local):
        # Fit by whole oldest turns only after an explicit capacity rejection.
        # Keep the original history until the reduced request is accepted.
        original = list(self.history)
        messages = list(original)
        while True:
            context.check()
            emitted = False
            try:
                async for event in self.llm.stream(Request('llm', {'messages': messages}, local), context):
                    context.check()
                    if not emitted and len(messages) < len(original):
                        removed = len(original) - len(messages)
                        del self.history[:removed]
                        yield Event('context_trimmed', {'removed_messages': removed})
                    emitted = True
                    yield event
                return
            except ContextCapacityExceeded:
                context.check()
                if emitted:
                    raise
                cutoff = next((index for index, message in enumerate(messages)
                               if index > 0 and message.get('role') == 'user'), None)
                if cutoff is None:
                    raise
                messages = messages[cutoff:]

    async def _generate(self, context, local, user_message):
        phrases = asyncio.Queue(maxsize=8)
        output_audio = local.get('output_audio', True)
        text_response = ''
        produced_output = False
        async def synthesize():
            while True:
                phrase = await phrases.get()
                if phrase is None:
                    break
                # A phrase is added to heard history only after its LAST chunk
                # is acknowledged. Partial audio is conservatively excluded.
                pending = None
                async for event in self.tts.stream(Request('tts',{'text':phrase}),context):
                    if event.kind != 'audio_chunk':
                        continue
                    if pending is not None:
                        await self._audio_slot(context)
                        self.chunk_id += 1
                        self.pending_audio[self.chunk_id] = ''
                        await self._emit(context,Event('audio_chunk',dict(pending.data,chunk_id=self.chunk_id)))
                    pending = event
                if pending is not None:
                    await self._audio_slot(context)
                    self.chunk_id += 1
                    self.pending_audio[self.chunk_id] = phrase
                    await self._emit(context,Event('audio_chunk',dict(pending.data,chunk_id=self.chunk_id)))
        try:
            async with asyncio.timeout(self.timeout):
                await self._emit(context, Event('request_started', {'request_id': local['request_id']}))
                async with asyncio.TaskGroup() as group:
                    speaker = group.create_task(synthesize()) if output_audio else None
                    buffer = ''
                    completed = False
                    async for event in self._llm_events(context, local):
                        if event.kind != 'context_trimmed':
                            produced_output = True
                        await self._emit(context,event)
                        if event.kind == 'tool_result':
                            call, result = event.data['call'], event.data['result']
                            self.history.extend([
                                {'role': 'assistant', 'content': None, 'tool_calls': [
                                    {'id': call['id'], 'type': 'function', 'function': {
                                        'name': call['name'], 'arguments': json.dumps(call['arguments'], ensure_ascii=False)}}]},
                                {'role': 'tool', 'tool_call_id': call['id'], 'content': json.dumps(result, ensure_ascii=False)}])
                        if event.kind == 'text_delta':
                            if not output_audio:
                                text_response += event.data['text']
                                if len(text_response) > 16000:
                                    raise ResourceExhausted('text response too large')
                                continue
                            buffer += event.data['text']
                            if len(buffer) >= 160 or buffer.endswith(('.', '?', '!', '\n')):
                                if buffer.strip():
                                    await phrases.put(buffer)
                                buffer = ''
                        elif event.kind == 'completed':
                            completed = True
                    if not completed:
                        raise ProviderError('missing completion')
                    if output_audio:
                        if buffer.strip():
                            await phrases.put(buffer)
                        await phrases.put(None)
                        await speaker
                    else:
                        context.check()
                        self.pending_text = text_response
                    await self._emit(context,Event('turn_done'))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if context.generation_id == self.generation and not self.closed:
                while not self.output.empty():
                    self.output.get_nowait()
                self.pending_audio.clear()
                self.pending_text = ''
                capacity = isinstance(error, ContextCapacityExceeded) or (
                    isinstance(error, BaseExceptionGroup) and error.subgroup(ContextCapacityExceeded) is not None)
                if capacity and not produced_output and self.history and self.history[-1] is user_message:
                    self.history.pop()
                    self.output.put_nowait((self.generation, Event('input_rejected', {'code': 'context_capacity_exceeded'})))
                else:
                    self.output.put_nowait((self.generation,Event('error',{'code':'turn_failed'})))

    async def next_event(self):
        while True:
            generation,event = await self.output.get()
            if generation == self.generation:
                return generation,event

    async def close(self):
        async with self.control:
            if self.closed:
                return
            await self._interrupt()
            self.closed = True
            if self.retired_tasks:
                await asyncio.gather(*self.retired_tasks, return_exceptions=True)
            await self.llm.reset(self.session_id)
            await self.tts.reset(self.session_id)
