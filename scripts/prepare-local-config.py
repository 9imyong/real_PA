"""Create ignored development manifests from explicitly selected local files."""
import argparse
import hashlib
import json
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('--models-root',type=Path,required=True)
p.add_argument('--llm-url',default='http://127.0.0.1:18181/v1')
p.add_argument('--llm-model',type=Path,default=Path('llm/Qwen3.5-0.8B-Q4_0.gguf'),
 help='Existing GGUF, absolute or relative to models-root')
p.add_argument('--llm-model-id',help='Served model name; defaults to the GGUF filename')
p.add_argument('--llm-max-tokens',type=int,default=512)
p.add_argument('--llm-system-prompt',help='Trusted assistant instructions; defaults to local assistant identity')
p.add_argument('--stt-model',choices=['transducer','sensevoice'],default='transducer')
p.add_argument('--tts-model',choices=['supertonic','mimic3-korean'],default='supertonic')
p.add_argument('--vits-dir',type=Path,help='Extracted Korean Mimic3 directory; required for mimic3-korean')
p.add_argument('--output-dir',type=Path)
a=p.parse_args()
if a.llm_max_tokens < 1:
 p.error('--llm-max-tokens must be positive')
model_id=a.llm_model_id or a.llm_model.name
system_prompt=a.llm_system_prompt if a.llm_system_prompt is not None else (
 f'당신은 real-PA라는 한국어 대화 비서입니다. 실행 모델은 {model_id}이며 자체 서버에서 추론합니다. '
 '최신 질문에 직접 답하고, 이전 대화의 사실을 참조하세요. 없는 사실은 지어내지 마세요. '
 '잘못된 답변을 지적받으면 바로잡으세요. 자기소개를 반복하지 마세요. '
 '일반 대화는 짧게, 설명 요청은 필요한 내용을 완결된 문장으로 답하세요.')
if not system_prompt.strip() or len(system_prompt)>4000:
 p.error('--llm-system-prompt must contain 1 to 4000 characters')
if a.tts_model == 'mimic3-korean' and a.vits_dir is None:
 p.error('--tts-model mimic3-korean requires --vits-dir')
r=Path(__file__).resolve().parents[1]
out=a.output_dir or r/'config/local'
out.mkdir(parents=True,exist_ok=True)
roles={
 'llm':('chat_http',{'model':str(a.llm_model)},['stream','cancel'],{'base_url':a.llm_url,'max_tokens':a.llm_max_tokens,'temperature':0.2,'enable_thinking':False,'system_prompt':system_prompt}),
 'stt':('sherpa',dict(tokens='kws/tokens.txt',encoder='kws/encoder-epoch-99-avg-1.int8.onnx',decoder='kws/decoder-epoch-99-avg-1.onnx',joiner='kws/joiner-epoch-99-avg-1.int8.onnx'),['stream','partial','final','cancel'],{}),
 'kws':('sherpa',dict(tokens='kws/tokens.txt',encoder='kws/encoder-epoch-99-avg-1.int8.onnx',decoder='kws/decoder-epoch-99-avg-1.onnx',joiner='kws/joiner-epoch-99-avg-1.int8.onnx',keywords='kws/keywords.txt'),['stream','cancel'],{}),
 'vad':('sherpa',{'model':'silero_vad.onnx'},['stream','cancel'],{}),
 'tts':('sherpa',dict(duration_predictor='supertonic/duration_predictor.int8.onnx',text_encoder='supertonic/text_encoder.int8.onnx',vector_estimator='supertonic/vector_estimator.int8.onnx',vocoder='supertonic/vocoder.int8.onnx',tts_json='supertonic/tts.json',unicode_indexer='supertonic/unicode_indexer.bin',voice_style='supertonic/voice.bin'),['phrase','chunks','cancel'],{'num_steps':4})}
if a.stt_model == 'sensevoice':
 roles['stt']=('sensevoice_buffered',dict(model='sensevoice/model.int8.onnx',tokens='sensevoice/tokens.txt'),
  ['stream','partial','final','cancel','buffered_partial'],{'partial_seconds':1.0,'max_seconds':22.0})
if a.tts_model == 'mimic3-korean':
 vits=a.vits_dir.resolve()
 paths={'model':str(vits/'ko_KO-kss_low.onnx'),'tokens':str(vits/'tokens.txt'),
        'phondata':str(vits/'espeak-ng-data/phondata')}
 for path in sorted((vits/'espeak-ng-data').rglob('*')):
  if path.is_file() and path.name != 'phondata':
   paths[str(path.relative_to(vits))]=str(path)
 roles['tts']=('sherpa_vits_korean',paths,['phrase','chunks','cancel'],{'num_threads':2})
lines=[]
for role,(adapter,paths,features,options) in roles.items():
 artifacts=[]
 for name,rel in paths.items():
  target=(a.models_root/rel).resolve()
  with target.open('rb') as f:
   sha=hashlib.file_digest(f,'sha256').hexdigest()
  artifacts.append({'name':name,'path':str(target),'sha256':sha})
 manifest={'role':role,'model_id':Path(next(iter(paths.values()))).name,
  'revision':'local-artifact-sha256','runtime':('sherpa-onnx==1.13.5' if adapter in {'sherpa','sensevoice_buffered','sherpa_vits_korean'} else 'llama.cpp:localforge-56b9eb280a67'),'license':'verification-required-before-distribution',
  'features':features,'languages':['ko'],'sample_rates':([22050] if adapter=='sherpa_vits_korean' else []) if role=='tts' else [16000],'artifacts':artifacts}
 (out/f'{role}.json').write_text(json.dumps(manifest,indent=2))
 lines.extend([f'[providers.{role}]',f'adapter = "{adapter}"',f'manifest = "{role}.json"','timeout = 60',f'[providers.{role}.options]'])
 for name,value in options.items():
  lines.append(f'{name} = '+json.dumps(value))
 lines.append('')
# Served model name is configured independently of its local filename.
m=json.loads((out/'llm.json').read_text());m['model_id']=a.llm_model_id or a.llm_model.name;(out/'llm.json').write_text(json.dumps(m,indent=2))
(out/'worker.toml').write_text('\n'.join(lines))
print('Development configuration created. License verification and quality evaluation remain required.')
