"""The Microsoft Store rejected a package asking for the unvirtualizedResources restricted capability."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "native_app" / "msix" / "AppxManifest.xml.template"


class StoreManifestTests(unittest.TestCase):
    def setUp(self):
        if not TEMPLATE.is_file():
            self.skipTest("no Store manifest template in this checkout")
        self.manifest = TEMPLATE.read_text(encoding="utf-8")

    def test_only_runfulltrust_is_a_restricted_capability(self):
        restricted = re.findall(r'<rescap:Capability\s+Name="([^"]+)"', self.manifest)
        self.assertEqual(restricted, ["runFullTrust"])
        self.assertNotIn("unvirtualizedResources", self.manifest)
        self.assertNotIn("desktop6:", self.manifest)  # registry/file virtualization opt-outs

    def test_startup_task_is_off_until_the_user_enables_it(self):
        self.assertRegex(self.manifest, r'<desktop:StartupTask[^>]*Enabled="false"')


if __name__ == "__main__":
    unittest.main()
