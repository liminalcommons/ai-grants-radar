"""HTML -> readable text and a cosmetic-change-proof content hash. Stdlib only."""
import hashlib
import re
from html.parser import HTMLParser

_SKIP = {"script", "style", "title", "nav", "footer", "noscript", "svg", "template", "iframe"}
_BLOCK = {"p", "div", "section", "article", "main", "header", "br", "tr", "table", "ul", "ol",
          "dl", "dt", "dd", "blockquote", "form", "fieldset", "aside", "figure", "figcaption"}
_HEADINGS = {"h1": "#", "h2": "##", "h3": "###", "h4": "####", "h5": "#####", "h6": "######"}


class _Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if self._skip_depth:
            if tag in _SKIP:
                self._skip_depth += 1
            return
        if tag in _SKIP:
            self._skip_depth = 1
            return
        if tag in _HEADINGS:
            self.parts.append("\n\n" + _HEADINGS[tag] + " ")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in ("td", "th"):
            self.parts.append(" | ")
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if self._skip_depth:
            if tag in _SKIP:
                self._skip_depth -= 1
            return
        if tag in _HEADINGS:
            self.parts.append("\n\n")
        elif tag in _BLOCK or tag == "li":
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip_depth:
            self.parts.append(data)


def html_to_text(html):
    """Readable text: headings as '# ', list items as '- ', nav/footer/script/style dropped."""
    if not html:
        return ""
    p = _Extractor()
    p.feed(html)
    p.close()
    raw = "".join(p.parts).replace("\xa0", " ")
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in raw.split("\n")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return text.strip()


def normalize_text(text):
    """Whitespace-collapsed, casefolded text used for hashing."""
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip().casefold()


def content_hash(text):
    """sha256 hex of normalised text; whitespace/case-only changes do not flip it."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()
