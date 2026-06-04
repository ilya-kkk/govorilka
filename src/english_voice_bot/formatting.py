from __future__ import annotations

import html
import re
from html.parser import HTMLParser

TELEGRAM_MESSAGE_LIMIT = 4096
SAFE_TELEGRAM_CHUNK_LIMIT = 3900


def escape_html(text: str) -> str:
    return html.escape(text, quote=False)


def format_transcription(transcription: str) -> str:
    return f"📝 I understood:\n\n<blockquote>{escape_html(transcription)}</blockquote>"


def format_spoiler_text(text: str) -> str:
    return f"<tg-spoiler>{escape_html(text)}</tg-spoiler>"


_TAG_ALIASES = {
    "strong": "b",
    "em": "i",
    "ins": "u",
    "del": "s",
    "strike": "s",
}
_ALLOWED_TAGS = {"b", "i", "u", "s", "code", "pre", "blockquote", "tg-spoiler"}


class _TelegramHTMLSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self.stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        normalized = _TAG_ALIASES.get(tag.lower(), tag.lower())
        if normalized not in _ALLOWED_TAGS:
            self.parts.append(escape_html(self.get_starttag_text() or ""))
            return
        self.parts.append(f"<{normalized}>")
        self.stack.append(normalized)

    def handle_endtag(self, tag: str) -> None:
        normalized = _TAG_ALIASES.get(tag.lower(), tag.lower())
        if normalized not in _ALLOWED_TAGS or normalized not in self.stack:
            self.parts.append(escape_html(f"</{tag}>"))
            return

        while self.stack:
            open_tag = self.stack.pop()
            self.parts.append(f"</{open_tag}>")
            if open_tag == normalized:
                break

    def handle_data(self, data: str) -> None:
        self.parts.append(escape_html(data))

    def handle_entityref(self, name: str) -> None:
        self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.parts.append(f"&#{name};")

    def get_html(self) -> str:
        while self.stack:
            self.parts.append(f"</{self.stack.pop()}>")
        return "".join(self.parts)


def sanitize_telegram_html(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    parser = _TelegramHTMLSanitizer()
    parser.feed(text)
    parser.close()
    return parser.get_html()


def format_review_report(report: str) -> str:
    normalized = report.replace("\r\n", "\n").replace("\r", "\n")
    markdownish = _html_to_markdownish(normalized)
    return _markdown_to_telegram_markdown_v2(markdownish)


_MARKDOWN_V2_SPECIAL_RE = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")
_BR_PLACEHOLDER = "\ue000"


def escape_markdown_v2(text: str) -> str:
    return _MARKDOWN_V2_SPECIAL_RE.sub(r"\\\1", text)


def _html_to_markdownish(text: str) -> str:
    text = re.sub(r"<br\s*/?>", _BR_PLACEHOLDER, text, flags=re.IGNORECASE)
    text = re.sub(r"</?(b|strong)>", "**", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(i|em)>", "*", text, flags=re.IGNORECASE)
    text = re.sub(r"</?[^>]+>", "", text)
    return html.unescape(text)


def _looks_like_markdown(text: str) -> bool:
    return any(
        (
            "**" in text,
            bool(re.search(r"(?m)^#{1,6}\s+", text)),
            bool(re.search(r"(?m)^\s*\|?.*?\|\s*$", text))
            and bool(re.search(r"(?m)^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$", text)),
        )
    )


def _markdown_to_telegram_markdown_v2(text: str) -> str:
    lines = text.splitlines()
    rendered: list[str] = []
    index = 0

    while index < len(lines):
        line = lines[index].rstrip()
        stripped = line.strip()

        if _is_markdown_table(lines, index):
            headers = _split_markdown_table_row(lines[index])
            index += 2
            while index < len(lines) and _is_table_row(lines[index]):
                row = _split_markdown_table_row(lines[index])
                rendered.extend(_render_markdown_table_row(headers, row))
                rendered.append("")
                index += 1
            continue

        if not stripped:
            rendered.append("")
            index += 1
            continue

        if re.fullmatch(r"[-—]{3,}", stripped):
            rendered.append("")
            index += 1
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading_match:
            rendered.append(_bold_markdown_v2(_strip_inline_markdown(heading_match.group(2))))
            index += 1
            continue

        bullet_match = re.match(r"^[-*]\s+(.+)$", stripped)
        if bullet_match:
            rendered.append(f"• {_render_inline_markdown_v2(bullet_match.group(1))}")
            index += 1
            continue

        numbered_match = re.match(r"^(\d+)[.)]\s+(.+)$", stripped)
        if numbered_match:
            rendered.append(
                f"{numbered_match.group(1)}\\. {_render_inline_markdown_v2(numbered_match.group(2))}"
            )
            index += 1
            continue

        rendered.append(_render_inline_markdown_v2(line))
        index += 1

    return "\n".join(rendered).strip()


def _is_markdown_table(lines: list[str], index: int) -> bool:
    return (
        index + 1 < len(lines)
        and _is_table_row(lines[index])
        and bool(
            re.match(
                r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$",
                lines[index + 1],
            )
        )
    )


def _is_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.count("|") >= 2


def _split_markdown_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _render_markdown_table_row(headers: list[str], row: list[str]) -> list[str]:
    rendered: list[str] = []
    if not row:
        return rendered

    first_header = headers[0] if headers else "№"
    first_cell = row[0] if row else ""
    if first_cell:
        rendered.append(_bold_markdown_v2(f"{_strip_inline_markdown(first_header)} {first_cell}"))

    for header, cell in zip(headers[1:], row[1:], strict=False):
        if not cell:
            continue
        rendered.append(
            f"{_bold_markdown_v2(f'{_strip_inline_markdown(header)}:')} "
            f"{_render_inline_markdown_v2(cell)}"
        )
    return rendered


def _render_inline_markdown_v2(text: str) -> str:
    normalized = re.sub(r"<br\s*/?>", _BR_PLACEHOLDER, text, flags=re.IGNORECASE)
    normalized = normalized.replace(_BR_PLACEHOLDER, "\n")
    parts: list[str] = []
    position = 0
    inline_re = re.compile(r"\*\*(.+?)\*\*|(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
    for match in inline_re.finditer(normalized):
        parts.append(escape_markdown_v2(normalized[position : match.start()]))
        bold_text = match.group(1)
        italic_text = match.group(2)
        if bold_text is not None:
            parts.append(_bold_markdown_v2(bold_text))
        elif italic_text is not None:
            parts.append(_italic_markdown_v2(italic_text))
        position = match.end()
    parts.append(escape_markdown_v2(normalized[position:]))
    return "".join(parts)


def _bold_markdown_v2(text: str) -> str:
    return f"*{escape_markdown_v2(text)}*"


def _italic_markdown_v2(text: str) -> str:
    return f"_{escape_markdown_v2(text)}_"


def _strip_inline_markdown(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*|(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", _strip_match, text)


def _strip_match(match: re.Match[str]) -> str:
    return match.group(1) or match.group(2) or ""


_SPLIT_TOKEN_RE = re.compile(r"(<[^>]+>|&[A-Za-z0-9#]+;|\s+|[^<&\s]+)")


def split_telegram_html(text: str, *, limit: int = SAFE_TELEGRAM_CHUNK_LIMIT) -> list[str]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for paragraph in re.split(r"(\n\n+)", text):
        if not paragraph:
            continue
        candidate = current + paragraph
        if len(candidate) <= limit:
            current = candidate
            continue
        if current.strip():
            chunks.append(current.strip())
            current = ""
        if len(paragraph) <= limit:
            current = paragraph
            continue
        chunks.extend(_split_long_fragment(paragraph, limit=limit))

    if current.strip():
        chunks.append(current.strip())
    return chunks


def _split_long_fragment(fragment: str, *, limit: int) -> list[str]:
    chunks: list[str] = []
    current = ""

    for token in _SPLIT_TOKEN_RE.findall(fragment):
        if len(token) > limit:
            if current.strip():
                chunks.append(current.strip())
                current = ""
            chunks.extend(token[index : index + limit] for index in range(0, len(token), limit))
            continue

        candidate = current + token
        if len(candidate) <= limit:
            current = candidate
            continue

        if current.strip():
            chunks.append(current.strip())
        current = token.lstrip()

    if current.strip():
        chunks.append(current.strip())
    return chunks
