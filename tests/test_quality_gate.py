import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from tools.quality_gate import validate_submission_zip


class FakeInfo:
    def __init__(self, mode=0o755):
        self.external_attr = mode << 16


class FakeZip:
    def __init__(self, names, start_mode=0o755):
        self._names = names
        self._start_mode = start_mode

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False

    def namelist(self):
        return self._names

    def getinfo(self, name):
        if name != "start.sh":
            raise KeyError(name)
        return FakeInfo(self._start_mode)


class QualityGateTest(unittest.TestCase):
    def test_valid_submission_zip(self):
        with self._zip(["start.sh", "litchi_bot/main.py"]):
            self.assertEqual(validate_submission_zip(path), [])

    def test_rejects_forbidden_submission_paths(self):
        with self._zip(["start.sh", "litchi_bot/main.py", "tests/test_decision.py", "litchi_bot/__pycache__/main.pyc"]):
            issues = validate_submission_zip(path)
            self.assertTrue(any("forbidden submission path" in issue for issue in issues))
            self.assertTrue(any("bytecode/cache file included" in issue for issue in issues))

    def test_rejects_missing_start_script(self):
        with self._zip(["litchi_bot/main.py"]):
            self.assertIn("zip root must contain start.sh", validate_submission_zip(path))

    def test_rejects_non_executable_start_script(self):
        with self._zip(["start.sh", "litchi_bot/main.py"], start_mode=0o644):
            self.assertIn("start.sh is not executable in zip metadata", validate_submission_zip(path))

    @contextmanager
    def _zip(self, names, start_mode=0o755):
        with patch.object(Path, "exists", return_value=True), patch(
            "tools.quality_gate.zipfile.ZipFile", return_value=FakeZip(names, start_mode)
        ):
            yield


path = Path("bot.zip")


if __name__ == "__main__":
    unittest.main()
