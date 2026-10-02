"""Synthetic Korean TTS->STT smoke, not microphone or quality certification."""
import asyncio
import json
import sys
from pathlib import Path
from time import monotonic
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from real_pa.config import read_config
from real_pa.composition import registry
from real_pa.contracts import Request,Context

async def main():
 import numpy as np
 configs=read_config(sys.argv[1])
 selected={r:configs[r] for r in ['tts','stt','kws','vad']}
 started=monotonic()
 providers=await registry().build(selected,{'stt':{'partial','final'}})
 load_seconds=monotonic()-started
 try:
  text='안녕하세요. 오늘 일정 알려주세요.'
  started=monotonic()
  chunks=[e async for e in providers['tts'].stream(Request('tts',{'text':text}),Context('smoke',1,1,60)) if e.kind=='audio_chunk']
  assert chunks,'TTS generated no audio'
  tts_seconds=monotonic()-started
  sr=chunks[0].data['sample_rate']
  samples=np.frombuffer(b''.join(e.data['pcm'] for e in chunks),dtype='<i2')
  x=np.arange(len(samples))*16000/sr
  y=np.arange(int(len(samples)*16000/sr))
  pcm=np.interp(y,x,samples).astype('<i2').tobytes()
  partials=0
  transcript=''
  started=monotonic()
  for seq,i in enumerate(range(0,len(pcm),3200)):
   frame=pcm[i:i+3200]
   for role in ['stt','kws','vad']:
    request=Request(role,{'pcm':frame,'sample_rate':16000,'final':False})
    async for e in providers[role].stream(request,Context('smoke',1,1,60)):
     if e.kind=='transcript_partial':partials+=1
  async for e in providers['stt'].stream(Request('stt',{'pcm':b'\0\0'*8000,'sample_rate':16000,'final':True}),Context('smoke',1,1,60)):
   if e.kind=='transcript_final':transcript=e.data['text']
  report={'actual_models':True,'synthetic_audio_only':True,'load_seconds':round(load_seconds,3),
   'tts_seconds':round(tts_seconds,3),'audio_seconds':round(len(samples)/sr,3),
   'stt_seconds':round(monotonic()-started,3),'partial_events':partials,
   'transcript_characters':len(transcript),'contains_korean':any('\uac00'<=c<='\ud7a3' for c in transcript)}
  root=Path(__file__).resolve().parents[1]/'artifacts';root.mkdir(exist_ok=True)
  (root/'audio-model-smoke.json').write_text(json.dumps(report,indent=2))
  print(json.dumps(report))
 finally:
  for provider in providers.values():await provider.close()

asyncio.run(main())
