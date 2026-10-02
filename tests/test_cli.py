"""Static composition validation without loading models or contacting servers."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from real_pa.cli import main


class ConfigCliTests(unittest.TestCase):
    def run_check(self, adapter, profile='worker'):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = {'role': 'llm', 'model_id': 'test-only', 'revision': '1',
                        'runtime': 'test-only', 'license': 'test-only',
                        'features': ['stream', 'cancel'], 'languages': ['ko'], 'artifacts': []}
            (root / 'model.json').write_text(json.dumps(manifest))
            config = root / 'config.toml'
            config.write_text(f'[providers.llm]\nadapter="{adapter}"\nmanifest="model.json"\n')
            out, err = io.StringIO(), io.StringIO()
            with patch('sys.argv', ['real-pa', 'check-config', str(config), '--profile', profile]), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = 0
                try:
                    main()
                except SystemExit as exit:
                    code = exit.code
            return code, out.getvalue(), err.getvalue()

    def test_unknown_adapter_does_not_report_validated(self):
        code, output, error = self.run_check('unregistered')
        self.assertEqual(code, 2)
        self.assertEqual(output, '')
        self.assertIn('configuration_error', error)

    def test_api_profile_requires_complete_composition(self):
        code, output, _ = self.run_check('chat_http', 'api')
        self.assertEqual(code, 2)
        self.assertEqual(output, '')

    def test_worker_check_is_explicitly_static(self):
        code, output, _ = self.run_check('chat_http')
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(output)['model_load_performed'])
