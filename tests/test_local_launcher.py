import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('local_launcher',
    Path(__file__).resolve().parents[1] / 'scripts/start-local-api.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LocalLauncherTests(unittest.TestCase):
    def test_generated_credential_is_private_and_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'local/browser.token'
            token = launcher.local_token(path)
            self.assertGreaterEqual(len(token), 16)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(launcher.local_token(path), token)

    def test_invalid_existing_file_is_rejected_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'browser.token'
            path.write_text('short')
            path.chmod(0o600)
            with self.assertRaises(ValueError): launcher.local_token(path)
            self.assertEqual(path.read_text(), 'short')
            path.write_text('fixture-credential-long-enough')
            path.chmod(0o644)
            with self.assertRaises(ValueError): launcher.local_token(path)

    def test_symlink_is_rejected_without_reading_target(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'browser.token'
            target = Path(directory) / 'target'
            target.write_text('fixture-credential-long-enough')
            path.symlink_to(target)
            with self.assertRaises(OSError): launcher.local_token(path)
