from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class Element:
    def __init__(self, tag: str, attrs: dict[str, str] | None = None):
        self.tag = tag.lower()
        self.attrs = attrs or {}
        self.parent: Element | None = None
        self.children: list[Element] = []

    def append(self, child: Element) -> None:
        child.parent = self
        self.children.append(child)


class TreeParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Element("#document")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Element(tag, {key: value or "" for key, value in attrs})
        self.stack[-1].append(node)
        if tag.lower() not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].append(Element(tag, {key: value or "" for key, value in attrs}))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag.lower():
                del self.stack[index:]
                break


def nodes(root: Element):
    yield root
    for child in root.children:
        yield from nodes(child)


def simple_match(node: Element, compound: str) -> bool:
    if any(mark in compound for mark in (":", "[", "]", "+", "~")):
        return False
    match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_-]*|\*)?((?:[#.][A-Za-z0-9_-]+)*)", compound)
    if not match:
        return False
    tag, suffix = match.groups()
    if tag and tag != "*" and node.tag != tag.lower():
        return False
    if not tag and not suffix:
        return False
    for kind, name in re.findall(r"([#.])([A-Za-z0-9_-]+)", suffix):
        if kind == "#" and node.attrs.get("id") != name:
            return False
        if kind == "." and name not in node.attrs.get("class", "").split():
            return False
    return True


def selector_match(node: Element, selector: str) -> bool:
    parts = selector.strip().split()
    if not parts:
        return False
    if not simple_match(node, parts[-1]):
        return False
    current: Element | None = node.parent
    for compound in reversed(parts[:-1]):
        while current is not None and not simple_match(current, compound):
            current = current.parent
        if current is None:
            return False
        current = current.parent
    return True


def parse_rules(css: str):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    index = 0
    order = 0
    while index < len(css):
        start = css.find("{", index)
        if start < 0:
            break
        selector_text = css[index:start].strip()
        depth, end = 1, start + 1
        while end < len(css) and depth:
            depth += (css[end] == "{") - (css[end] == "}")
            end += 1
        if depth:
            break
        if selector_text.startswith("@"):
            index = end
            continue
        declarations = {}
        for declaration in css[start + 1:end - 1].split(";"):
            if ":" not in declaration:
                continue
            name, value = declaration.split(":", 1)
            declarations[name.strip().lower()] = value.strip()
        for selector in selector_text.split(","):
            order += 1
            yield selector.strip(), declarations, order
        index = end


def specificity(selector: str) -> tuple[int, int, int]:
    ids = len(re.findall(r"#[A-Za-z0-9_-]+", selector))
    classes = len(re.findall(r"\.[A-Za-z0-9_-]+", selector))
    tags = sum(bool(re.match(r"^[A-Za-z]", item)) for item in selector.split())
    return ids, classes, tags


class Cascade:
    def __init__(self, rules):
        self.rules = list(rules)

    def style(self, node: Element, property_name: str) -> str | None:
        candidates = []
        for selector, declarations, order in self.rules:
            value = declarations.get(property_name)
            if property_name == "background":
                value = declarations.get("background-color") or declarations.get("background")
                if value:
                    color = re.match(r"^(#[0-9a-fA-F]{3,8})", value)
                    value = color.group(1) if color else None
            if value is not None and selector_match(node, selector):
                important = value.endswith("!important")
                if important:
                    value = value.removesuffix("!important").strip()
                candidates.append(((important, specificity(selector), order), value))
        return max(candidates, default=(None, None), key=lambda item: item[0])[1]

    def color(self, node: Element) -> str | None:
        current: Element | None = node
        while current is not None:
            color = self.style(current, "color")
            if color and color.startswith("#"):
                return color
            current = current.parent
        return None

    def background(self, node: Element) -> str | None:
        current: Element | None = node
        while current is not None:
            color = self.style(current, "background")
            if color:
                return color
            current = current.parent
        return None


def query(root: Element, selector: str) -> Element:
    return next(node for node in nodes(root) if selector_match(node, selector))


def contrast(foreground: str, background: str) -> float:
    def luminance(value: str) -> float:
        channels = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [channel / 12.92 if channel <= .04045 else ((channel + .055) / 1.055) ** 2.4 for channel in channels]
        return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]
    light, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (light + .05) / (dark + .05)


def append_fragment(parent: Element, markup: str) -> None:
    parser = TreeParser()
    parser.feed(markup)
    for child in parser.root.children:
        parent.append(child)


class DetachedOverlayContrastTest(unittest.TestCase):
    def test_selector_rightmost_compound_must_match_the_candidate_node(self):
        parser = TreeParser()
        parser.feed('<div class="ancestor"><p id="child">text</p></div>')
        child = query(parser.root, "#child")
        self.assertFalse(selector_match(child, ".ancestor"))
        self.assertTrue(selector_match(child, ".ancestor p"))

    @classmethod
    def setUpClass(cls):
        parser = TreeParser()
        parser.feed((ROOT / "static/index.html").read_text(encoding="utf-8"))
        cls.document = parser.root
        cls.body = query(cls.document, "body")
        cls.app = query(cls.document, "#app")
        cls.drawer = query(cls.document, "#detail-drawer")
        append_fragment(cls.drawer, """
          <div class="drawer-head"><small>MASTER</small><b>Order details</b></div>
          <div class="drawer-body"><h1 class="detail-title">Order</h1><p class="detail-sub">Details</p>
            <div class="detail-field"><span>Code</span><b>NA-001</b></div>
            <div class="detail-section"><h3>Report</h3><p>Work completed and result recorded.</p>
              <label class="field-label">Assignee<select class="field-select"><option selected>Worker</option></select></label>
              <input class="field-input" type="text" disabled><textarea class="field-textarea"></textarea>
              <div class="ai-result"><b>AI summary</b><p>Text review</p></div>
              <div class="ai-result caution"><b>Master attention</b><p>Uncertain evidence</p></div>
            </div>
          </div>
        """)
        append_fragment(cls.body, """
          <div id="notification-popover" class="notification-popover">
            <h3>Notifications</h3><div class="notification-item">New order<small>10:30</small></div>
          </div>
          <div id="telegram-popover" class="notification-popover">
            <div class="popover-head"><h3>Telegram</h3></div><p>Connection state</p>
            <label class="field-label">Chat<select><option selected>Unlinked</option></select></label>
          </div>
        """)
        cls.cascade = Cascade(parse_rules((ROOT / "static/styles.css").read_text(encoding="utf-8")))

    def test_runtime_roots_are_detached_siblings_of_the_app_shell(self):
        self.assertIs(self.app.parent, self.body)
        self.assertIs(self.drawer.parent, self.body)
        self.assertIs(query(self.body, "#notification-popover").parent, self.body)
        self.assertIs(query(self.body, "#telegram-popover").parent, self.body)
        self.assertNotIn(self.app, list(_ancestors(self.drawer)))

    def test_cascade_produces_readable_colors_for_drawer_fields_and_both_ai_states(self):
        checks = (
            ("drawer heading", query(self.drawer, ".detail-title")),
            ("drawer subtitle", query(self.drawer, ".detail-sub")),
            ("field caption", query(self.drawer, ".detail-field span")),
            ("field value", query(self.drawer, ".detail-field b")),
            ("section heading", query(self.drawer, ".detail-section h3")),
            ("section body", query(self.drawer, ".detail-section p")),
            ("field label", query(self.drawer, ".field-label")),
            ("input", query(self.drawer, "input")),
            ("select", query(self.drawer, "select")),
            ("option", query(self.drawer, "option")),
            ("AI body", query(self.drawer, ".ai-result p")),
            ("AI caution body", query(self.drawer, ".ai-result.caution p")),
        )
        for label, node in checks:
            with self.subTest(label=label):
                foreground, background = self.cascade.color(node), self.cascade.background(node)
                self.assertIsNotNone(foreground, label)
                self.assertIsNotNone(background, label)
                self.assertGreaterEqual(contrast(foreground, background), 4.5, (label, foreground, background))

    def test_cascade_produces_readable_notification_and_telegram_popovers(self):
        checks = (
            ("notification heading", query(self.body, "#notification-popover h3")),
            ("notification text", query(self.body, ".notification-item")),
            ("notification timestamp", query(self.body, ".notification-item small")),
            ("telegram heading", query(self.body, "#telegram-popover h3")),
            ("telegram status", query(self.body, "#telegram-popover p")),
            ("telegram label", query(self.body, "#telegram-popover .field-label")),
            ("telegram option", query(self.body, "#telegram-popover option")),
        )
        for label, node in checks:
            with self.subTest(label=label):
                foreground, background = self.cascade.color(node), self.cascade.background(node)
                self.assertIsNotNone(foreground, label)
                self.assertIsNotNone(background, label)
                self.assertGreaterEqual(contrast(foreground, background), 4.5, (label, foreground, background))


def _ancestors(node: Element):
    current = node.parent
    while current is not None:
        yield current
        current = current.parent


if __name__ == "__main__":
    unittest.main(verbosity=2)
