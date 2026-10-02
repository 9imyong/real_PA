"""Create ignored development manifests from explicitly selected local files."""
import argparse
import hashlib
import json
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('--models-root',type=Path,required=True)
p.add_argument('--llm-url',default='http://127.0.0.1:18181/v1')
p.add_argument('--stt-model',choices=['transducer','sensevoice'],default='transducer')
p.add_argument('--output-dir',type=Path)
a=p.parse_args()
r=Path(__file__).resolve().parents[1]
out=a.output_dir or r/'config/local'
out.mkdir(parents=True,exist_ok=True)
roles={
 'llm':('chat_http',{'model':'llm/Qwen3.5-0.8B-Q4_0.gguf'},['stream','cancel'],{'base_url':a.llm_url,'max_tokens':96,'enable_thinking':False}),
 'stt':('sherpa',dict(tokens='kws/tokens.txt',encoder='kws/encoder-epoch-99-avg-1.int8.onnx',decoder='kws/decoder-epoch-99-avg-1.onnx',joiner='kws/joiner-epoch-99-avg-1.int8.onnx'),['stream','partial','final','cancel'],{}),
 'kws':('sherpa',dict(tokens='kws/tokens.txt',encoder='kws/encoder-epoch-99-avg-1.int8.onnx',decoder='kws/decoder-epoch-99-avg-1.onnx',joiner='kws/joiner-epoch-99-avg-1.int8.onnx',keywords='kws/keywords.txt'),['stream','cancel'],{}),
 'vad':('sherpa',{'model':'silero_vad.onnx'},['stream','cancel'],{}),
 'tts':('sherpa',dict(duration_predictor='supertonic/duration_predictor.int8.onnx',text_encoder='supertonic/text_encoder.int8.onnx',vector_estimator='supertonic/vector_estimator.int8.onnx',vocoder='supertonic/vocoder.int8.onnx',tts_json='supertonic/tts.json',unicode_indexer='supertonic/unicode_indexer.bin',voice_style='supertonic/voice.bin'),['phrase','chunks','cancel'],{'num_steps':4})}
if a.stt_model == 'sensevoice':
 roles['stt']=('sensevoice_buffered',dict(model='sensevoice/model.int8.onnx',tokens='sensevoice/tokens.txt'),
  ['stream','partial','final','cancel','buffered_partial'],{'partial_seconds':1.0,'max_seconds':22.0})
lines=[]
for role,(adapter,paths,features,options) in roles.items():
 artifacts=[]
 for name,rel in paths.items():
  target=(a.models_root/rel).resolve()
  with target.open('rb') as f:
   sha=hashlib.file_digest(f,'sha256').hexdigest()
  artifacts.append({'name':name,'path':str(target),'sha256':sha})
 manifest={'role':role,'model_id':Path(next(iter(paths.values()))).name,
  'revision':'local-artifact-sha256','runtime':('sherpa-onnx==1.13.5' if adapter in {'sherpa','sensevoice_buffered'} else 'llama.cpp:localforge-56b9eb280a67'),'license':'verification-required-before-distribution',
  'features':features,'languages':['ko'],'sample_rates':[16000] if role!='tts' else [],'artifacts':artifacts}
 (out/f'{role}.json').write_text(json.dumps(manifest,indent=2))
 lines.extend([f'[providers.{role}]',f'adapter = "{adapter}"',f'manifest = "{role}.json"','timeout = 60',f'[providers.{role}.options]'])
 for name,value in options.items():
  lines.append(f'{name} = '+json.dumps(value))
 lines.append('')
# Served model name is configured independently of its local filename.
m=json.loads((out/'llm.json').read_text());m['model_id']='Qwen3.5-0.8B-Q4_0.gguf';(out/'llm.json').write_text(json.dumps(m,indent=2))
(out/'worker.toml').write_text('\n'.join(lines))
print('Development configuration created. License verification and quality evaluation remain required.')
