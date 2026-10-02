"""Model negotiation unit tests without network sockets."""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from real_pa.adapters.rpc import RemoteProvider
from real_pa.config import ProviderConfig
from real_pa.contracts import InvalidOutput


class RpcIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def negotiate(self,actual_model):
        os.environ['REAL_PA_IDENTITY_TEST']='unit-test-credential'
        manifest={'model_id':'expected','revision':'1','runtime':'engine-1',
            'artifact_fingerprints':[{'name':'model','sha256':'a'*64}],
            'features':['stream'],'languages':['ko']}
        config=ProviderConfig('llm','company_rpc',manifest,
            {'url':'ws://127.0.0.1:1','token_env':'REAL_PA_IDENTITY_TEST'},1,Path('fixture'))
        class Socket:
            async def send(self,raw):pass
            async def recv(self):
                return json.dumps({'type':'capabilities','role':'llm','features':['stream'],
                    'languages':['ko'],'model_identity':dict(manifest,model_id=actual_model)})
        class Connection:
            async def __aenter__(self):return Socket()
            async def __aexit__(self,*args):pass
        try:
            with patch('websockets.asyncio.client.connect',return_value=Connection()):
                provider=RemoteProvider(config)
                await provider.load()
                return provider
        finally:
            os.environ.pop('REAL_PA_IDENTITY_TEST',None)

    async def test_identity_mismatch_is_rejected(self):
        with self.assertRaises(InvalidOutput):
            await self.negotiate('unexpected')

    async def test_identity_match_preserves_actual_capabilities(self):
        provider=await self.negotiate('expected')
        self.assertEqual(provider.capabilities.features,frozenset({'stream'}))
        await provider.close()
