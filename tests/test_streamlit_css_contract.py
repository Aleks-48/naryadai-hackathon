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

    def test_form_controls_have_visible_boundaries_and_focus_state(self):
        style = STYLE_MATCH.group(1)
        for selector in (
            '[data-testid="stTextInputRootElement"]',
            '[data-testid="stTextAreaRootElement"]',
            '[data-testid="stNumberInput"] [data-baseweb="input"]',
            '[data-testid="stSelectbox"] > .react-aria-ComboBox > div',
        ):
            self.assertIn(selector, style)
        self.assertIn('[data-testid="stTextInputField"]', style)
        self.assertIn("border: 1px solid #7f9088 !important", style)
        self.assertIn("background-color: var(--nai-white) !important", style)
        self.assertIn("min-height: 44px;", style)
        self.assertIn('[data-testid="stSelectbox"] button { min-height: 44px; }', style)
        self.assertIn(":focus-within", style)
        self.assertIn('[data-testid="stTextInputRootElement"]:focus-within', style)
        self.assertIn('[data-testid="stTextAreaRootElement"]:focus', style)
        self.assertIn("box-shadow: 0 0 0 3px rgba(21, 155, 122, .2)", style)
        self.assertIn("input::placeholder", style)

    def test_status_captions_wrap_and_metrics_reflow_before_tablet_overflow(self):
        style = STYLE_MATCH.group(1)
        tablet = style.split("@media (max-width: 1200px)", 1)[1].split("@media (max-width: 760px)", 1)[0]
        self.assertIn("overflow-wrap: anywhere", style)
        self.assertIn("text-overflow: clip !important", style)
        self.assertIn("white-space: normal !important", style)
        self.assertIn('[data-testid="stMetricLabel"] [data-testid="stMarkdownContainer"] *', style)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr)) !important", tablet)
        self.assertIn("min-width: 0 !important", tablet)


if __name__ == "__main__":
    unittest.main(verbosity=2)
