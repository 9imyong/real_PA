"""Actual GPU+audio models, native or RPC, while input remains active.

Synthetic inputs and acknowledged buffer delivery only. This is NOT physical
speaker playback, microphone AEC, Lemmy business E2E, or production certification.
"""
import asyncio
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import secrets
import sys
from time import monotonic
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from real_pa.config import read_config
from real_pa.composition import registry
from real_pa.adapters.rpc import InferenceGateway,RemoteProvider
from real_pa.session import DialogueSession
from real_pa.robot import RobotRuntime

async def main():
 from websockets.asyncio.server import serve
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('config')
 parser.add_argument('--turns',type=int,default=3)
 parser.add_argument('--duration',type=float,default=0,help='Keep generating and capturing for at least this many seconds')
 parser.add_argument('--output',type=Path,default=Path('artifacts/duplex-gpu-smoke.json'))
 parser.add_argument('--native',action='store_true',help='Use the API server native pipeline instead of worker RPC')
 args=parser.parse_args()
 if args.turns < 2:parser.error('at least two turns are required')
 if args.duration < 0:parser.error('duration must not be negative')
 args.output.parent.mkdir(parents=True,exist_ok=True)
 args.output.write_text(json.dumps({'status':'running','pid':os.getpid(),'rpc_transport':not args.native}))
 configs=read_config(args.config)
 local=await registry().build(configs)
 token=secrets.token_urlsafe(32)
 os.environ['REAL_PA_SMOKE_TOKEN']=token
 gateway=InferenceGateway(local,token)
 remotes={}
 session=None
 runtime=None
 captured=processed=max_input_queue=0
 vad_seconds=[]
 try:
  async with serve(gateway.handle,'127.0.0.1',0,max_size=1024*1024) as server:
   url='ws://127.0.0.1:'+str(server.sockets[0].getsockname()[1])
   for role,config in ({} if args.native else configs).items():
    remote=RemoteProvider(replace(config,adapter='company_rpc',options={'url':url,'token_env':'REAL_PA_SMOKE_TOKEN'}))
    await remote.load()
    remotes[role]=remote
   active=local if args.native else remotes
   original_vad=active['vad'].stream
   async def measured_vad(request,context):
    nonlocal processed
    before=monotonic()
    async for event in original_vad(request,context):yield event
    processed+=1
    vad_seconds.append(monotonic()-before)
   active['vad'].stream=measured_vad
   session=DialogueSession('duplex-gpu-smoke',active['llm'],active['tts'],timeout=60)
   runtime=RobotRuntime(session,active)
   await runtime.start(ui_started=True)
   feeding=True
   async def capture():
    nonlocal captured,max_input_queue
    while feeding:
     runtime.accept_audio(b'\0\0'*1600)
     captured+=1
     max_input_queue=max(max_input_queue,runtime.input.qsize())
     await asyncio.sleep(.1)
   feeder=asyncio.create_task(capture())
   async def next_event():
    pending=asyncio.create_task(session.next_event())
    try:
     done,_=await asyncio.wait({pending,feeder,runtime.running},return_when=asyncio.FIRST_COMPLETED)
     for task in (feeder,runtime.running):
      if task in done:
       await task
       raise RuntimeError('input processing stopped during generation')
     return await pending
    finally:
     pending.cancel()
     await asyncio.gather(pending,return_exceptions=True)
   started=monotonic()
   audio_chunks=0
   interrupted=False
   first_audio=None
   turns=0
   try:
    i=0
    while i < args.turns or monotonic()-started < args.duration:
     await session.submit('한국어로 짧게 인사해 주세요.')
     expected=session.generation
     async with asyncio.timeout(60):
      while True:
       generation,event=await next_event()
       if generation!=expected:
        continue
       if event.kind=='error':
        raise RuntimeError('actual duplex turn failed')
       if event.kind=='audio_chunk':
        first_audio=first_audio or monotonic()
        audio_chunks+=1
        assert session.acknowledge(generation,event.data['chunk_id'])
        if i==0 and not interrupted:
         old=generation
         await session.interrupt()
         interrupted=True
         assert not session.acknowledge(old,event.data['chunk_id'])
         break
       if event.kind=='turn_done':
        turns+=1
        break
     i+=1
     if i % 10 == 0:
      args.output.write_text(json.dumps({'status':'running','pid':os.getpid(),'rpc_transport':not args.native,
       'completed_followup_turns':turns,'captured':captured,'processed':processed,'max_input_queue':max_input_queue}))
    feeding=False
    await feeder
    async with asyncio.timeout(10):
     while processed < captured:
      if runtime.running.done():await runtime.running
      await asyncio.sleep(.01)
    if feeder.done():await feeder
    if runtime.running.done():await runtime.running
    assert captured>0 and audio_chunks>0 and interrupted and turns==i-1 and processed==captured
    result={'status':'passed','actual_gpu_llm':True,'actual_audio_models':True,'rpc_transport':not args.native,
      'synthetic_input_only':True,'physical_playback_verified':False,
      'capture_frames_while_generating':captured,'audio_chunks':audio_chunks,
      'processed_input_frames':processed,'max_input_queue':max_input_queue,
      'vad_max_seconds':round(max(vad_seconds,default=0),4),
      'vad_mean_seconds':round(sum(vad_seconds)/max(1,len(vad_seconds)),4),
      'interrupted_generation_discarded':interrupted,'completed_followup_turns':turns,
      'first_audio_seconds':round(first_audio-started,3),'total_seconds':round(monotonic()-started,3)}
    root=Path(__file__).resolve().parents[1]/'artifacts';root.mkdir(exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2))
    print(json.dumps(result))
   finally:
    feeding=False
    feeder.cancel()
    await asyncio.gather(feeder,return_exceptions=True)
    await runtime.close()
    runtime=None
    for remote in remotes.values():await remote.close()
    remotes.clear()
 except BaseException as error:
  root=Path(__file__).resolve().parents[1]/'artifacts';root.mkdir(exist_ok=True)
  args.output.write_text(json.dumps({'status':'failed','error_type':type(error).__name__,
    'rpc_transport':not args.native,'captured':captured,'processed':processed,'max_input_queue':max_input_queue,
    'vad_max_seconds':round(max(vad_seconds,default=0),4),
    'vad_mean_seconds':round(sum(vad_seconds)/max(1,len(vad_seconds)),4)}))
  raise
 finally:
  for remote in remotes.values():await remote.close()
  for provider in local.values():await provider.close()
  os.environ.pop('REAL_PA_SMOKE_TOKEN',None)

asyncio.run(main())
