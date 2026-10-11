"""Security/reproducibility checks for the release boundary (stdlib only)."""

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from release import build


class ReleaseTests(unittest.TestCase):
    def test_allowlist_manifest_and_reproducibility(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "VERSION").write_text("1.0.0")
            for name in (
                "backend/app/main.py",
                "frontend/src/App.tsx",
                "README.md",
                "LICENSE",
                "docs/TECHNICAL.md",
                "docs/images/demo.png",
                "licenses/NOTICE.txt",
                "licenses/python/example/LICENSE.txt",
                "secrets/key",
                "backend/.venv/private.py",
                "backend/data/orders.json",
                "frontend/node_modules/private.json",
                "frontend/test-results/private.png",
                "frontend/dist/main.js",
                ".env",
                "unknown.txt",
            ):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("test")
            first = build(root, root / "output/first").read_bytes()
            self.assertEqual(first, build(root, root / "output/second").read_bytes())
            with zipfile.ZipFile(
                root / "output/first/ShopPulse-1.0.0-source.zip"
            ) as z:
                base = "ShopPulse-1.0.0/"
                manifest = json.loads(z.read(base + "MANIFEST.json"))
                self.assertEqual(
                    set(manifest["files"]),
                    {
                        "VERSION",
                        "backend/app/main.py",
                        "frontend/src/App.tsx",
                        "README.md",
                        "LICENSE",
                        "docs/TECHNICAL.md",
                        "docs/images/demo.png",
                        "licenses/NOTICE.txt",
                        "licenses/python/example/LICENSE.txt",
                    },
                )
                self.assertTrue(manifest["license_confirmed"])
                for name, expected in manifest["files"].items():
                    self.assertEqual(
                        hashlib.sha256(z.read(base + name)).hexdigest(), expected
                    )

    def test_secret_leak_refuses_package(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "VERSION").write_text("1.0.0")
            (root / "secrets").mkdir()
            (root / "secrets/key").write_text("synthetic-credential-for-test")
            (root / "README.md").write_text("leaked synthetic-credential-for-test")
            with self.assertRaisesRegex(ValueError, "Local secret"):
                build(root, root / "output")
            self.assertFalse(list((root / "output").glob("*.zip")))

    def test_invalid_version_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "VERSION").write_text("../../escape")
            with self.assertRaisesRegex(ValueError, "VERSION"):
                build(root, root / "output")


if __name__ == "__main__":
    unittest.main()
