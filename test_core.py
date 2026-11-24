import tempfile
import unittest
from pathlib import Path

from main import ControlledTerminal, Project, extract_json, validate_python


class CoreTests(unittest.TestCase):
    def test_extract_json_accepts_fenced_response(self):
        result = extract_json('```json\n{"action":"answer","response":"ok"}\n```')
        self.assertEqual(result["action"], "answer")

    def test_project_rejects_escape_and_round_trips_write(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Project(Path(directory))
            with self.assertRaises(ValueError):
                project.safe_path("../outside.txt")
            result, backup = project.write("nested/value.txt", "hello")
            self.assertIn("nested/value.txt", result)
            self.assertIsNone(backup)
            self.assertEqual(project.read("nested/value.txt"), "hello")

    def test_python_validation_and_terminal_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Project(Path(directory))
            project.write("valid.py", "answer = 42\n")
            self.assertEqual(validate_python(project.safe_path("valid.py")), "syntax_check=passed")
            terminal = ControlledTerminal(project, lambda _: True)
            with self.assertRaises(ValueError):
                terminal.run("python -c 'print(1)' | whoami")


if __name__ == "__main__":
    unittest.main()
