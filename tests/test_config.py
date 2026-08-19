from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from config import load_local_env


class LocalEnvConfigTest(unittest.TestCase):
    def test_loads_valid_values_without_overriding_exported_variables(self) -> None:
        previous = {name: os.environ.get(name) for name in ("KITUNGA_TEST_VALUE", "KITUNGA_TEST_FIXED")}
        try:
            os.environ["KITUNGA_TEST_FIXED"] = "exported"
            with tempfile.TemporaryDirectory() as directory:
                env_file = Path(directory) / ".env"
                env_file.write_text(
                    "# comment\nKITUNGA_TEST_VALUE = local\nKITUNGA_TEST_FIXED=local\nINVALID-NAME=value\n",
                    encoding="utf-8",
                )
                load_local_env(env_file)

            self.assertEqual(os.environ["KITUNGA_TEST_VALUE"], "local")
            self.assertEqual(os.environ["KITUNGA_TEST_FIXED"], "exported")
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
