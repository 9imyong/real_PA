import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('local_launcher',
    Path(__file__).resolve().parents[1] / 'scripts/start-local-api.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LocalLauncherTests(unittest.TestCase):
    def test_launcher_needs_no_token_and_creates_no_credential_file(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'worker.toml'
            config.write_text('')
            with patch('sys.argv', ['start-local-api', '--config', str(config)]), \
                    patch.object(launcher.os, 'execv') as execute:
                launcher.main()
            command = execute.call_args.args[1]
            self.assertNotIn('--require-token', command)
            self.assertNotIn('--token-env', command)
            self.assertEqual(list(Path(directory).iterdir()), [config])
