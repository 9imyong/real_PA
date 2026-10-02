"""Actual GPU server smoke; reports numbers only, never user conversation."""
import asyncio
import json
import sys
from pathlib import Path
from time import monotonic
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from real_pa.adapters.chat_http import ChatHttp
from real_pa.config import ProviderConfig
from real_pa.contracts import Request, Context

async def main():
    manifest = {'model_id':'Qwen3.5-0.8B-Q4_0.gguf','features':['stream','cancel'],
                'languages':['ko']}
    config = ProviderConfig('llm','chat_http',manifest,
        {'base_url':'http://127.0.0.1:18181/v1','max_tokens':48,'temperature':0,
         'enable_thinking':False},30,Path('development'))
    provider = ChatHttp(config)
    await provider.load()
    started = monotonic()
    first = None
    text = ''
    completed = False
    try:
        async for event in provider.stream(Request('llm',{'messages':[
            {'role':'system','content':'한국어로 짧게 한 문장만 답하세요.'},
            {'role':'user','content':'안녕하세요. 간단히 인사해주세요.'}]}),Context('gpu-smoke',1,1)):
            if event.kind == 'text_delta':
                first = first or monotonic()
                text += event.data['text']
            completed |= event.kind == 'completed'
        assert completed and text.strip(), 'empty or incomplete model output'
        result = {'actual_model':True,'completed':completed,'output_characters':len(text),
                  'contains_korean':any('\uac00' <= c <= '\ud7a3' for c in text),
                  'first_token_seconds':round(first-started,4),
                  'total_seconds':round(monotonic()-started,4)}
        root = Path(__file__).resolve().parents[1]/'artifacts'
        root.mkdir(exist_ok=True)
        (root/'gpu-smoke.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result,ensure_ascii=False))
    finally:
        await provider.close()

asyncio.run(main())
