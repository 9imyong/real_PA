"""Explicit factories and atomic composition; never import code from settings."""
from .contracts import ConfigurationError

class Registry:
    def __init__(self):
        self.factories = {}

    def register(self, role, adapter, factory):
        key = (role, adapter)
        if key in self.factories:
            raise ConfigurationError('duplicate adapter registration')
        self.factories[key] = factory

    def validate(self, configs, requirements=None):
        """Check the whole composition before loading any model resources."""
        requirements = requirements or {}
        if requirements.keys() - configs.keys():
            raise ConfigurationError('required role is missing')
        for role, config in configs.items():
            if config.role != role:
                raise ConfigurationError('configuration role mismatch')
            if (role, config.adapter) not in self.factories:
                raise ConfigurationError(f'{role}: unknown adapter')
            config.capabilities.require(requirements.get(role, set()))

    async def build(self, configs, requirements=None):
        requirements = requirements or {}
        self.validate(configs, requirements)
        loaded = {}
        try:
            for role, config in configs.items():
                factory = self.factories[(role,config.adapter)]
                provider = factory(config)
                # Include partially loaded resources in cleanup.
                loaded[role] = provider
                await provider.load()
                if provider.capabilities.role != role:
                    raise ConfigurationError('adapter role mismatch')
                provider.capabilities.require(requirements.get(role,set()))
            return loaded
        except BaseException:
            for provider in reversed(list(loaded.values())):
                try:
                    await provider.close()
                except Exception:
                    pass
            raise
