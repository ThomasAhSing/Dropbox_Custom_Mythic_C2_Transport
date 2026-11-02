"""Check the runtime/development dependency boundary after the package move."""

import ast
from pathlib import Path
import unittest


class LayoutTests(unittest.TestCase):
    def test_root_runtime_has_no_development_dependencies(self):
        root = Path(__file__).resolve().parents[2]
        for name in ("storage.py", "dropbox_storage.py", "dropbox_client.py"):
            with self.subTest(module=name):
                tree = ast.parse((root / name).read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        modules = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        modules = [node.module or ""]
                    else:
                        continue
                    self.assertFalse(any(m == "dev" or m.startswith("dev.") for m in modules))


if __name__ == "__main__":
    unittest.main()
