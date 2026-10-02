import asyncio
from dataclasses import dataclass,field
from types import SimpleNamespace
import unittest

from real_pa.adapters.lemmy_llm import chat_messages,json_schema,LemmyLlmAdapter
from real_pa.contracts import Event


@dataclass
class Part:
    text: str|None=None
    tool_call: object=None
    tool_result: object=None


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    def test_tool_history_has_correlated_chat_ids(self):
        call=SimpleNamespace(name='get_reminders',arguments={'date':'2026-10-02'})
        reply=SimpleNamespace(name='get_reminders',response={'items':[]})
        messages=[SimpleNamespace(role='assistant',parts=[Part(tool_call=call)]),
                  SimpleNamespace(role='user',parts=[Part(tool_result=reply)])]
        output=chat_messages(messages,'한국어로 답하기')
        self.assertEqual(output[1]['tool_calls'][0]['id'],output[2]['tool_call_id'])
        self.assertEqual(output[2]['role'],'tool')

    def test_gemini_schema_converted_at_boundary(self):
        value={'type':'OBJECT','properties':{'when':{'type':'STRING','nullable':True}}}
        result=json_schema(value)
        self.assertEqual(result['type'],'object')
        self.assertEqual(result['properties']['when']['type'],['string','null'])
        self.assertEqual(value['type'],'OBJECT')

    async def test_bridge_emits_lemmy_contract(self):
        class Provider:
            config=SimpleNamespace(timeout=2)
            async def load(self):pass
            async def stream(self,request,context):
                yield Event('text_delta',{'text':'안녕'})
                yield Event('tool_call',{'id':'c1','name':'search_notes','arguments':{'query':'약'}})
                yield Event('completed')
        schemas=SimpleNamespace(LlmStreamEvent=lambda kind,**kw:SimpleNamespace(kind=kind,**kw),
                                ToolCall=lambda name,args:SimpleNamespace(name=name,arguments=args))
        bridge=LemmyLlmAdapter(Provider(),schema_module=schemas)
        request=SimpleNamespace(messages=[SimpleNamespace(role='user',parts=[Part(text='메모 보여줘')])],
            options=SimpleNamespace(system_instruction=None,tools=()))
        events=[e async for e in bridge.stream(request)]
        self.assertEqual([e.kind for e in events],['text','tool_call'])
        self.assertEqual(events[1].tool_call.name,'search_notes')
