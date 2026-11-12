"""web/js/i18n.js: translation dictionaries stay complete and in sync with the code.

These tests read the JavaScript / HTML sources as text, so they need no
browser or JavaScript runtime:
  - English and Turkish define the same keys,
  - every key referenced from index.html and app.js exists,
  - every vehicle kind and route coming from the backend can be displayed in Turkish.
"""

if __package__ in (None, ""):  # allow running this file directly: python tests/test_i18n.py
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import re
import unittest

from backend import config
from backend.alarms import DEVIATION, SPEED
from backend.routes import ROUTES, VEHICLES

I18N_JS = (config.WEB_DIR / "js" / "i18n.js").read_text(encoding="utf-8")
APP_JS = (config.WEB_DIR / "js" / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (config.WEB_DIR / "index.html").read_text(encoding="utf-8")

# Keys that only the Turkish dictionary needs: English route names come from the server
TURKISH_ONLY_PREFIXES = ("route.",)


def dictionary_keys(locale: str) -> set[str]:
    """Keys of `MESSAGES.<locale>` in i18n.js."""
    match = re.search(rf"\n    {locale}: \{{(.*?)\n    \}},", I18N_JS, re.S)
    if not match:
        raise AssertionError(f"dictionary '{locale}' not found in i18n.js")
    return set(re.findall(r"^\s+'([\w.]+)':", match.group(1), re.M))


EN = dictionary_keys("en")
TR = dictionary_keys("tr")


class DictionaryTest(unittest.TestCase):
    def test_dictionaries_are_not_empty(self):
        self.assertGreater(len(EN), 100)

    def test_turkish_defines_every_english_key(self):
        self.assertEqual(sorted(EN - TR), [])

    def test_english_defines_every_turkish_key(self):
        extra = {k for k in TR - EN if not k.startswith(TURKISH_ONLY_PREFIXES)}
        self.assertEqual(sorted(extra), [])

    def test_placeholders_match_between_languages(self):
        for key in EN & TR:
            with self.subTest(key=key):
                en = set(re.findall(r"\{(\w+)\}", _raw_value("en", key)))
                tr = set(re.findall(r"\{(\w+)\}", _raw_value("tr", key)))
                self.assertEqual(en, tr)


class UsageTest(unittest.TestCase):
    def test_keys_used_in_html_exist(self):
        used = set(re.findall(r'data-i18n(?:-[\w-]+)?="([\w.]+)"', INDEX_HTML))
        self.assertGreater(len(used), 40)
        self.assertEqual(sorted(used - EN), [])

    def test_static_keys_used_in_app_js_exist(self):
        used = set(re.findall(r"\bt\('([\w.]+)'", APP_JS))
        self.assertGreater(len(used), 30)
        self.assertEqual(sorted(used - EN), [])

    def test_dynamic_status_and_alarm_keys_exist(self):
        for status in ("moving", "speed", "deviation", "stopped"):
            self.assertIn(f"status.{status}", EN)
        for alarm_type in (SPEED, DEVIATION):
            self.assertIn(f"alarmType.{alarm_type}", EN)
            self.assertIn(f"alarmMessage.{alarm_type}", EN)


class BackendDataTest(unittest.TestCase):
    def test_every_vehicle_kind_is_translated(self):
        for vehicle in VEHICLES:
            with self.subTest(vehicle=vehicle["id"]):
                self.assertRegex(vehicle["kind"], r"^[a-z_]+$")  # a key, not display text
                self.assertIn(f"kind.{vehicle['kind']}", EN)
                self.assertIn(f"kind.{vehicle['kind']}", TR)

    def test_turkish_route_overrides_refer_to_existing_routes(self):
        for key in TR:
            if key.startswith("route."):
                route_id = key.split(".")[1]
                self.assertIn(route_id, ROUTES, key)


def _raw_value(locale: str, key: str) -> str:
    """Raw source text of one entry (string or plural object)."""
    match = re.search(rf"\n    {locale}: \{{(.*?)\n    \}},", I18N_JS, re.S)
    entry = re.search(rf"^\s+'{re.escape(key)}': (.+)$", match.group(1), re.M)
    return entry.group(1)


if __name__ == "__main__":
    unittest.main()
