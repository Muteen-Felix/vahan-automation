"""Every Compose variable must appear in the config template and the reference (T26)."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTERNAL = {"VAHAN_ENVIRONMENT"}


class ConfigTemplateTests(unittest.TestCase):
    def test_template_and_reference_cover_all_compose_variables(self):
        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        names = set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)(?::[?-]|\})", compose))
        template = (ROOT / "docs/release/config/config-template.env").read_text(encoding="utf-8")
        reference = (ROOT / "docs/release/config/config-reference.md").read_text(encoding="utf-8")
        missing_template = sorted(n for n in names if not re.search(rf"^#?\s*{n}=", template, re.MULTILINE))
        missing_reference = sorted(n for n in names if f"`{n}`" not in reference)
        self.assertEqual(missing_template, [], "variables missing from config-template.env")
        self.assertEqual(missing_reference, [], "variables missing from config-reference.md")

    def test_template_has_no_secret_values(self):
        template = (ROOT / "docs/release/config/config-template.env").read_text(encoding="utf-8")
        for line in template.splitlines():
            key, sep, value = line.partition("=")
            if sep and re.search(r"PASSWORD|SECRET|TOKEN|KEY", key):
                self.assertEqual(value.strip(), "<generate>", key)


if __name__ == "__main__":
    unittest.main()
