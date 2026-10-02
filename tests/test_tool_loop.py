import asyncio
import unittest
from real_pa.contracts import Capabilities, Context, Event, Request, InvalidOutput
from real_pa.tool_loop import ToolLoop

TOOLS = [{'type': 'function', 'function': {'name': 'save_reminder', 'parameters': {}}}]


class Model:
    capabilities = Capabilities('llm', frozenset({'stream', 'cancel', 'tools'}), frozenset({'ko'}))
    def __init__(self, rounds):
        self.rounds = iter(rounds)
        self.requests = []
    async def stream(self, request, context):
        self.requests.append(request)
        for event in next(self.rounds):
            yield event
    async def reset(self, session_id): pass
    async def close(self): pass


class ToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_round_trip_keeps_local_audio_out_of_inference_requests(self):
        call = Event('tool_call', {'id': 'model-id', 'name': 'save_reminder', 'arguments': {'title': '시험'}})
        model = Model([[call, Event('completed')], [Event('text_delta', {'text': '완료'}), Event('completed')]])
        seen = []
        async def execute(call, context, local, key):
            seen.append((local, key))
            return {'id': 1}
        loop = ToolLoop(model, TOOLS, execute)
        output = [e async for e in loop.stream(Request('llm', {'messages': []},
            {'audio_blob': b'private', 'request_id': 'request-0000000001'}), Context('s', 1, 1))]
        self.assertEqual(output[-1].kind, 'completed')
        self.assertEqual(seen[0][1], 'request-0000000001:save_reminder')
        self.assertEqual(seen[0][0]['audio_blob'], b'private')
        self.assertTrue(all(not r.local and 'audio_blob' not in r.data for r in model.requests))
        self.assertEqual(model.requests[1].data['messages'][-1]['role'], 'tool')
        await loop.close()

    async def test_unavailable_tool_never_reaches_executor(self):
        model = Model([[Event('tool_call', {'name': 'delete_note', 'arguments': {}}), Event('completed')]])
        async def execute(*args): self.fail('executor must not run')
        loop = ToolLoop(model, TOOLS, execute)
        with self.assertRaises(InvalidOutput):
            _ = [e async for e in loop.stream(Request('llm', {'messages': []}), Context('s', 1, 1))]

    async def test_cancelled_audio_waiter_does_not_cancel_started_write(self):
        started, release, committed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        model = Model([[Event('tool_call', {'name': 'save_reminder', 'arguments': {}}), Event('completed')]])
        async def execute(*args):
            started.set()
            await release.wait()
            committed.set()
            return {'id': 1}
        loop = ToolLoop(model, TOOLS, execute, write_tools={'save_reminder'})
        async def consume():
            async for _ in loop.stream(Request('llm', {'messages': []}), Context('s', 1, 1)):
                pass
        task = asyncio.create_task(consume())
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertFalse(committed.is_set())
        release.set()
        await loop.close()
        self.assertTrue(committed.is_set())

    async def test_incomplete_round_cannot_execute_a_write(self):
        model = Model([[Event('tool_call', {'name': 'save_reminder', 'arguments': {}})]])
        async def execute(*args): self.fail('executor must not run')
        loop = ToolLoop(model, TOOLS, execute)
        with self.assertRaises(InvalidOutput):
            _ = [e async for e in loop.stream(Request('llm', {'messages': []}), Context('s', 1, 1))]
