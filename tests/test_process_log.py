import unittest
from io import StringIO

from litchi_bot.process_log import append_process_event, create_process_log


class FakeParent:
    def __init__(self):
        self.mkdir_calls = []

    def mkdir(self, **kwargs):
        self.mkdir_calls.append(kwargs)


class FakeAppendHandle(StringIO):
    def __init__(self, path):
        super().__init__()
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        self.path.content += self.getvalue()
        self.path.exists_value = True
        return False


class FakePath:
    def __init__(self, content="", exists=False):
        self.content = content
        self.exists_value = exists
        self.parent = FakeParent()
        self.write_calls = []

    def exists(self):
        return self.exists_value

    def write_text(self, text, encoding=None):
        self.write_calls.append((text, encoding))
        self.content = text
        self.exists_value = True

    def open(self, mode, encoding=None):
        self.write_calls.append((f"open:{mode}", encoding))
        return FakeAppendHandle(self)


class ProcessLogTest(unittest.TestCase):
    def test_create_and_append_process_log(self):
        path = FakePath()

        create_process_log(path, "Replay Iteration", {"replay": "match.json", "player_id": 1001})
        append_process_event(path, "Tests", "python -B tools/quality_gate.py passed.")
        text = path.content

        self.assertTrue(path.parent.mkdir_calls)
        self.assertIn("# Replay Iteration", text)
        self.assertIn("- replay: `match.json`", text)
        self.assertIn("- player_id: `1001`", text)
        self.assertIn("## Timeline", text)
        self.assertIn(" - Tests", text)
        self.assertIn("python -B tools/quality_gate.py passed.", text)

    def test_create_process_log_preserves_existing_content(self):
        path = FakePath(content="existing\n", exists=True)

        create_process_log(path, "New Title")

        self.assertEqual(path.content, "existing\n")


if __name__ == "__main__":
    unittest.main()
