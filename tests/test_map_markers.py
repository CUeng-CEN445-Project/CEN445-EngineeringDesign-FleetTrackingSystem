"""Vehicle markers must stay where Leaflet puts them (web/css + web/js, read as text).

Regression: app.js replaced the marker element's `className` every second, which
removed Leaflet's `leaflet-marker-icon` class and with it `position: absolute`.
A CSS rule `.veh-marker { position: relative }` then put the markers into normal
document flow, so the n-th vehicle was drawn n × 17 px below its real position,
visibly off its route although the server reported 0 m deviation.
"""

if __package__ in (None, ""):  # allow running this file directly: python tests/test_map_markers.py
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import re
import unittest

from backend import config

CSS_DIR = config.WEB_DIR / "css"
APP_JS = (config.WEB_DIR / "js" / "app.js").read_text(encoding="utf-8")


def css_rules_for(selector: str) -> list[str]:
    """Declaration blocks of every rule whose selector list contains exactly `selector`."""
    blocks = []
    for path in CSS_DIR.rglob("*.css"):
        css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
        for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            if selector in (s.strip() for s in selectors.split(",")):
                blocks.append(body)
    return blocks


def js_function_body(name: str) -> str:
    """Source of a top-level `function name(...) { ... }` in app.js."""
    match = re.search(rf"^function {name}\(.*?^\}}", APP_JS, re.S | re.M)
    if not match:
        raise AssertionError(f"function {name} not found in app.js")
    return match.group(0)


class MarkerStyleTest(unittest.TestCase):
    def test_marker_root_does_not_override_leaflet_positioning(self):
        for body in css_rules_for(".veh-marker"):
            self.assertNotRegex(body, r"(^|;)\s*position\s*:")
            self.assertNotRegex(body, r"(^|;)\s*z-index\s*:")

    def test_marker_parts_are_absolutely_positioned_inside_the_marker(self):
        for selector in (".veh-dot", ".veh-pulse", ".veh-label"):
            with self.subTest(selector=selector):
                self.assertTrue(
                    any(re.search(r"position\s*:\s*absolute", body) for body in css_rules_for(selector))
                )


class MarkerScriptTest(unittest.TestCase):
    def test_marker_updates_never_replace_leaflet_classes(self):
        for name in ("renderMarkers", "applySelectionStyles"):
            with self.subTest(function=name):
                body = js_function_body(name)
                self.assertNotRegex(body, r"\.className\s*=")
                self.assertNotRegex(body, r"setAttribute\(\s*['\"]class['\"]")

    def test_status_classes_are_toggled(self):
        body = js_function_body("renderMarkers")
        self.assertIn("classList.remove(...MARKER_STATUS_CLASSES)", body)
        self.assertIn("classList.add(`status-${status}`)", body)


if __name__ == "__main__":
    unittest.main()
