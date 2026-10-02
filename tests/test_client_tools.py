"""Client-routed tool contract with fixture providers, not model quality."""
import asyncio
import json
import unittest

from real_pa.client_tools import ClientToolBridge, Route, validate_tools
from real_pa.contracts import Capabilities, Event
from real_pa.robot_gateway import RobotGateway
from test_robot import AudioFixture
from test_robot_gateway import Socket
from test_runtime import FixtureProvider

WEATHER = {'type': 'function', 'function': {'name': 'get_weather', 'description': '날씨',
                                            'parameters': {'type': 'object', 'properties': {}}}}
YOUTUBE = {'type': 'function', 'function': {'name': 'search_youtube', 'description': '영상',
                                            'parameters': {'type': 'object', 'properties': {}}}}


class ToolLLM:
    """Calls the first offered tool, then answers from the tool message."""

    def __init__(self):
        self.capabilities = Capabilities('llm', frozenset({'stream', 'cancel', 'tools'}), frozenset({'ko'}))
        self.requests = []

    async def stream(self, request, context):
        self.requests.append(request.data)
        tools = request.data.get('tools')
        if tools and request.data.get('tool_choice') != 'none' and request.data['messages'][-1]['role'] != 'tool':
            yield Event('tool_call', {'name': tools[0]['function']['name'], 'arguments': {}})
        else:
            last = request.data['messages'][-1]
            yield Event('text_delta', {'text': '맑아요.' if last['role'] == 'tool' else '안녕하세요.'})
        yield Event('completed')

    async def reset(self, session_id):
        pass

    async def close(self):
        pass


class ClientToolTests(unittest.IsolatedAsyncioTestCase):
    def providers(self, llm=None):
        return dict(llm=llm or ToolLLM(), tts=FixtureProvider('tts'),
                    **{r: AudioFixture(r) for r in ['stt', 'kws', 'vad']})

    async def connect(self, providers, **start):
        socket = Socket()
        socket.input.put_nowait(json.dumps({'type': 'start', 'ui_started': True, **start}))
        task = asyncio.create_task(RobotGateway(providers, None, anonymous=True).handle(socket))
        await socket.wait_type('session_started')
        return socket, task

    async def close(self, task):
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    def say(self, socket, text):
        socket.input.put_nowait(json.dumps({'type': 'text', 'text': text, 'output_audio': False}))

    async def test_routed_tool_round_trip_reaches_the_answer(self):
        llm = ToolLLM()
        socket, task = await self.connect(self.providers(llm), route=True, tools=[WEATHER, YOUTUBE])
        try:
            self.say(socket, '밖에 나가도 될까?')
            request = await socket.wait_type('route_request')
            self.assertEqual(request['data']['text'], '밖에 나가도 될까?')
            socket.input.put_nowait(json.dumps({'type': 'route', 'request_id': request['data']['request_id'],
                                                'tools': ['get_weather'], 'tool_choice': 'required'}))
            call = await socket.wait_type('tool_call')
            self.assertEqual(call['data']['name'], 'get_weather')
            socket.input.put_nowait(json.dumps({'type': 'tool_output', 'call_id': call['data']['call_id'],
                                                'result': {'sky': 'clear'}}))
            delta = await socket.wait_type('text_delta')
            self.assertEqual(delta['data']['text'], '맑아요.')
            await socket.wait_type('turn_done')
            first, second = llm.requests
            self.assertEqual([t['function']['name'] for t in first['tools']], ['get_weather'])
            self.assertEqual(first['tool_choice'], 'required')
            self.assertNotIn('tool_choice', second)  # forcing never repeats after results
            self.assertEqual(json.loads(second['messages'][-1]['content']), {'sky': 'clear'})
        finally:
            await self.close(task)

    async def test_empty_route_answers_without_tools(self):
        llm = ToolLLM()
        providers = self.providers(llm)
        socket, task = await self.connect(providers, route=True, tools=[WEATHER])
        try:
            self.say(socket, '안녕')
            request = await socket.wait_type('route_request')
            socket.input.put_nowait(json.dumps({'type': 'route', 'request_id': request['data']['request_id'],
                                                'tools': []}))
            self.assertEqual((await socket.wait_type('text_delta'))['data']['text'], '안녕하세요.')
            self.assertNotIn('tools', llm.requests[-1])
        finally:
            await self.close(task)

    async def test_route_timeout_falls_back_to_plain_answer(self):
        bridge = ClientToolBridge([WEATHER], route_timeout=0.01)
        emitted = []

        async def emit(event):
            emitted.append(event.kind)
        self.assertEqual(await bridge.route('r1', '안녕', emit), Route())
        self.assertEqual(emitted, ['route_request'])

    async def test_unknown_tool_or_choice_routes_to_no_tools(self):
        for route in [{'tools': ['delete_everything']}, {'tools': ['get_weather'], 'tool_choice': 'force'},
                      {'tools': 'get_weather'},
                      {'prefetched': [{'name': 'delete_everything', 'arguments': {}, 'result': {}}]},
                      {'prefetched': [{'name': 'get_weather', 'arguments': {}, 'result': 'sunny'}]},
                      {'reply': '   '}, {'reply': 'x' * 501}]:
            with self.subTest(route=route):
                bridge = ClientToolBridge([WEATHER])

                async def emit(event):
                    bridge.resolve_route({'request_id': 'r1', **route})
                self.assertEqual(await bridge.route('r1', 'x', emit), Route())

    async def test_tool_output_timeout_and_invalid_result_are_failures(self):
        bridge = ClientToolBridge([WEATHER], tool_timeout=0.01)
        call = {'id': 'call_1_1', 'name': 'get_weather', 'arguments': {}}

        async def silent(event):
            pass
        self.assertEqual(await bridge.execute(call, 'k', silent), {'error': 'tool_timeout'})

        async def invalid(event):
            bridge.resolve_output({'call_id': 'call_1_1', 'result': ['not', 'an', 'object']})
        self.assertEqual(await bridge.execute(call, 'k', invalid), {'error': 'invalid_tool_output'})

    async def test_interrupt_releases_a_pending_tool_wait(self):
        llm = ToolLLM()
        socket, task = await self.connect(self.providers(llm), route=True, tools=[WEATHER])
        try:
            self.say(socket, '날씨')
            request = await socket.wait_type('route_request')
            socket.input.put_nowait(json.dumps({'type': 'route', 'request_id': request['data']['request_id'],
                                                'tools': ['get_weather']}))
            call = await socket.wait_type('tool_call')
            socket.input.put_nowait(json.dumps({'type': 'interrupt'}))
            await socket.wait_type('interrupted')
            # A late output for the cancelled call is ignored, not an error.
            socket.input.put_nowait(json.dumps({'type': 'tool_output', 'call_id': call['data']['call_id'],
                                                'result': {'sky': 'clear'}}))
            self.say(socket, '안녕')
            request = await socket.wait_type('route_request')
            socket.input.put_nowait(json.dumps({'type': 'route', 'request_id': request['data']['request_id']}))
            self.assertEqual((await socket.wait_type('text_delta'))['data']['text'], '안녕하세요.')
        finally:
            await self.close(task)

    async def test_prefetched_lookup_is_answered_without_offering_tools(self):
        llm = ToolLLM()
        socket, task = await self.connect(self.providers(llm), route=True, tools=[WEATHER, YOUTUBE])
        try:
            self.say(socket, '밖에 나가도 될까?')
            request = await socket.wait_type('route_request')
            socket.input.put_nowait(json.dumps({'type': 'route', 'request_id': request['data']['request_id'],
                'prefetched': [{'name': 'get_weather', 'arguments': {'location': None}, 'result': {'sky': 'clear'}}]}))
            self.assertEqual((await socket.wait_type('text_delta'))['data']['text'], '맑아요.')
            done = await socket.wait_type('turn_done')
            socket.input.put_nowait(json.dumps({'type': 'text_ack', 'generation_id': done['generation_id']}))
            (request_data,) = llm.requests  # one LLM round, no forced tool decision
            self.assertNotIn('tools', request_data)
            assistant, tool = request_data['messages'][-2:]
            self.assertEqual(assistant['tool_calls'][0]['function']['name'], 'get_weather')
            self.assertEqual(json.loads(tool['content']), {'sky': 'clear'})
            # The lookup stays in history for follow-up turns.
            self.say(socket, '고마워')
            request = await socket.wait_type('route_request')
            socket.input.put_nowait(json.dumps({'type': 'route', 'request_id': request['data']['request_id']}))
            await socket.wait_type('turn_done')
            roles = [m['role'] for m in llm.requests[-1]['messages']]
            self.assertIn('tool', roles)
        finally:
            await self.close(task)

    async def test_fixed_reply_is_spoken_without_any_llm_call(self):
        llm = ToolLLM()
        socket, task = await self.connect(self.providers(llm), route=True, tools=[WEATHER])
        try:
            self.say(socket, '날씨 어때')
            request = await socket.wait_type('route_request')
            socket.input.put_nowait(json.dumps({'type': 'route', 'request_id': request['data']['request_id'],
                'prefetched': [{'name': 'get_weather', 'arguments': {}, 'result': {'error': 'tool_failed'}}],
                'reply': '지금 날씨 정보를 확인하지 못했어요.'}))
            self.assertEqual((await socket.wait_type('text_delta'))['data']['text'], '지금 날씨 정보를 확인하지 못했어요.')
            await socket.wait_type('turn_done')
            self.assertEqual(llm.requests, [])  # fail-closed: the model never answers from memory
        finally:
            await self.close(task)

    async def test_tool_schemas_stay_identical_across_none_auto_and_prefetched_turns(self):
        llm = ToolLLM()
        socket, task = await self.connect(self.providers(llm), route=True, tools=[WEATHER, YOUTUBE])
        both = ['get_weather', 'search_youtube']
        routes = [{'tools': both, 'tool_choice': 'none'},
                  {'tools': both, 'tool_choice': 'none',
                   'prefetched': [{'name': 'get_weather', 'arguments': {}, 'result': {'sky': 'clear'}}]},
                  {'tools': both, 'tool_choice': 'none'}]
        try:
            for text, route in zip(['안녕', '날씨', '고마워'], routes):
                self.say(socket, text)
                request = await socket.wait_type('route_request')
                socket.input.put_nowait(json.dumps({'type': 'route', 'request_id': request['data']['request_id'], **route}))
                done = await socket.wait_type('turn_done')
                socket.input.put_nowait(json.dumps({'type': 'text_ack', 'generation_id': done['generation_id']}))
            # Prefix cache: every request carries byte-identical schemas, none forbids calls.
            self.assertEqual(len(llm.requests), 3)
            self.assertEqual({json.dumps(r['tools'], ensure_ascii=False) for r in llm.requests},
                             {json.dumps([WEATHER, YOUTUBE], ensure_ascii=False)})
            self.assertEqual([r['tool_choice'] for r in llm.requests], ['none', 'none', 'none'])
        finally:
            await self.close(task)

    async def test_start_rejects_tools_without_route_or_tool_capable_llm(self):
        for start, llm in [({'tools': [WEATHER]}, ToolLLM()), ({'route': True}, ToolLLM()),
                           ({'route': True, 'tools': [WEATHER], 'route_timeout_ms': 50}, ToolLLM()),
                           ({'route': True, 'tools': [WEATHER], 'route_timeout_ms': 1.5}, ToolLLM()),
                           ({'route': True, 'tools': [WEATHER]}, FixtureProvider())]:
            with self.subTest(start=start):
                socket = Socket()
                socket.input.put_nowait(json.dumps({'type': 'start', **start}))
                await RobotGateway(self.providers(llm), None, anonymous=True).handle(socket)
                self.assertEqual(socket.closed, 1008)

    def test_tool_definitions_are_validated(self):
        bad = [[], [{'type': 'function', 'function': {'name': 'a b'}}], [WEATHER, WEATHER],
               [{'type': 'other', 'function': {'name': 'x'}}], [WEATHER] * 17]
        for tools in bad:
            with self.subTest(tools=tools):
                with self.assertRaises(ValueError):
                    validate_tools(tools)


if __name__ == '__main__':
    unittest.main()
