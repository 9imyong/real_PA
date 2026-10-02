"""Generate robot RPC manifests with hashes but without model file paths."""
import argparse
import json
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('worker_config',type=Path)
p.add_argument('--url',required=True)
p.add_argument('--output',type=Path,default=Path('config/local/robot'))
p.add_argument('--token-env',default='REAL_PA_WORKER_TOKEN')
a=p.parse_args()
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from real_pa.config import read_config
configs=read_config(a.worker_config)
a.output.mkdir(parents=True,exist_ok=True)
lines=[]
for role,c in configs.items():
 m=dict(c.manifest)
 m['artifact_fingerprints']=sorted([{'name':f.get('name','artifact'),'sha256':f['sha256']}
                                  for f in m['artifacts']],key=lambda item:item['name'])
 m['artifacts']=[]
 (a.output/f'{role}.json').write_text(json.dumps(m,indent=2))
 lines.extend([f'[providers.{role}]','adapter = "company_rpc"',f'manifest = "{role}.json"',
               'timeout = 60',f'[providers.{role}.options]',f'url = {json.dumps(a.url)}',
               f'token_env = {json.dumps(a.token_env)}',''])
(a.output/'robot.toml').write_text('\n'.join(lines))
print('Robot RPC profile generated; no model paths or credentials copied.')
