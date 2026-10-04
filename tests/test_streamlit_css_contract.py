import re
import unittest
from pathlib import Path

import streamlit


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
STYLE_MATCH = re.search(r'STREAMLIT_STYLE\s*=\s*"""(.*?)"""', APP_SOURCE, re.S)


class StreamlitCssContractTest(unittest.TestCase):
    def test_pinned_streamlit_columns_match_css_wrappers(self):
        self.assertIsNotNone(STYLE_MATCH, "STREAMLIT_STYLE must remain a literal CSS contract")
        style = STYLE_MATCH.group(1)
        self.assertEqual(streamlit.__version__, "1.64.0")
        for requirement in (ROOT / "requirements.txt", ROOT / "requirements-streamlit.txt"):
            self.assertIn("streamlit==1.64.0", requirement.read_text(encoding="utf-8"))
        self.assertNotIn('[data-testid="column"]', style)
        for index in range(1, 5):
            selector = f".st-key-status-summary .stColumn:nth-child({index}) [data-testid=\"stMetric\"]"
            self.assertIn(selector, style)
        for key in ("status-summary", "report-summary", "create-order-panel", "order-detail"):
            self.assertIn(f".st-key-{key} .stColumn", style)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", style)


if __name__ == "__main__":
    unittest.main(verbosity=2)
