"""Strict configuration and artifact validation before any provider is loaded."""
from __future__ import annotations
import hashlib
import json
import math
import tomllib
from dataclasses import dataclass
from pathlib import Path
from .contracts import Capabilities, ConfigurationError, ROLES

@dataclass(frozen=True)
class ProviderConfig:
    role: str
    adapter: str
    manifest: dict
    options: dict
    timeout: float
    manifest_path: Path

    @property
    def capabilities(self):
        m = self.manifest
        return Capabilities(self.role, frozenset(m['features']),
                            frozenset(m['languages']), frozenset(m.get('sample_rates', [])))

def read_config(path: str | Path) -> dict[str, ProviderConfig]:
    path = Path(path).resolve()
    try:
        with path.open('rb') as handle:
            root = tomllib.load(handle)
        if set(root) != {'providers'} or not isinstance(root['providers'], dict):
            raise ConfigurationError('only the providers section is supported')
        result = {}
        validated_hashes = {}
        for role, entry in root['providers'].items():
            if role not in ROLES or not isinstance(entry, dict):
                raise ConfigurationError('unknown role')
            if set(entry) - {'adapter', 'manifest', 'options', 'timeout'}:
                raise ConfigurationError('unknown provider setting')
            adapter = entry['adapter']
            if not isinstance(adapter, str) or not adapter:
                raise ConfigurationError('invalid adapter')
            manifest_path = (path.parent / entry['manifest']).resolve()
            m = json.loads(manifest_path.read_text())
            required = {'model_id','revision','runtime','license','role','features','languages','artifacts'}
            if not isinstance(m, dict) or required - m.keys() or m['role'] != role:
                raise ConfigurationError('invalid manifest')
            if any(not isinstance(m[key], str) or not m[key].strip()
                   for key in ['model_id','revision','runtime','license']):
                raise ConfigurationError('manifest identity must be explicit')
            for key in ['features','languages']:
                if not isinstance(m[key], list) or any(not isinstance(x,str) for x in m[key]):
                    raise ConfigurationError('invalid capability declaration')
            if not isinstance(m['artifacts'], list):
                raise ConfigurationError('invalid artifact list')
            for artifact in m['artifacts']:
                target = (manifest_path.parent / artifact['path']).resolve()
                expected = artifact['sha256']
                if not isinstance(expected,str) or len(expected) != 64:
                    raise ConfigurationError('invalid artifact hash')
                if target not in validated_hashes:
                    with target.open('rb') as artifact_file:
                        validated_hashes[target] = hashlib.file_digest(artifact_file, 'sha256').hexdigest()
                actual = validated_hashes[target]
                if actual != expected:
                    raise ConfigurationError('artifact hash mismatch')
            options = entry.get('options', {})
            timeout = entry.get('timeout',30.0)
            if not isinstance(options,dict) or isinstance(timeout,bool) or not isinstance(timeout,(int,float)) or not math.isfinite(timeout) or timeout <= 0:
                raise ConfigurationError('invalid options or timeout')
            result[role] = ProviderConfig(role,adapter,m,options,float(timeout),manifest_path)
        return result
    except ConfigurationError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ConfigurationError('configuration or artifact validation failed') from exc
