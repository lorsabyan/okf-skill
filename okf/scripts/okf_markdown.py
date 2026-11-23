"""Read CommonMark links and the source lines of OKF index sections."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from io import StringIO

from markdown_it import MarkdownIt

MARKDOWN = MarkdownIt("commonmark").enable("table")


FOOTNOTE = re.compile(r"\[\^([^\]\s]+)\]")


def _footnote(state, silent):
    match = FOOTNOTE.match(state.src, state.pos, state.posMax)
    if match is None:
        return False
    end = match.end()
    definition = (state.src.startswith(":", end)
                  and not state.src[state.src.rfind("\n", 0, state.pos) + 1:state.pos].strip())
    if not silent:
        kind = "footnote_definition" if definition else "footnote_use"
        state.env.setdefault(kind, []).append(match[1])
        state.pending += match[0]
    state.pos = end
    return True


# Inspect OKF citations in prose, leaving escapes and code spans to CommonMark.
FOOTNOTE_MARKDOWN = MarkdownIt("commonmark").enable("table")
FOOTNOTE_MARKDOWN.inline.ruler.after("link", "okf_footnote", _footnote)


def footnote_labels(text):
    env = {}
    FOOTNOTE_MARKDOWN.parse(text, env)
    defined = set(env.get("footnote_definition", ()))
    # A single-word footnote definition can also parse as a reference definition.
    lines = markdown_lines(text)
    for ref in env.get("references", {}).values():
        match = FOOTNOTE.match(lines[ref["map"][0]].lstrip())
        if match:
            defined.add(match[1])
    return env.get("footnote_use", ()), defined


@dataclass
class IndexEntry:
    line: int
    paragraph_end: int
    item_end: int
    title: str
    target: str
    description: str


@dataclass
class IndexSection:
    line: int
    heading_end: int
    heading: str
    entries: list[IndexEntry] = field(default_factory=list)


def markdown_lines(text: str) -> list[str]:
    """Match CommonMark source maps, retaining CR, LF and CRLF verbatim."""
    return StringIO(text, newline="").readlines()


def link_targets(text):
    for token in MARKDOWN.parse(text):
        for child in token.children or ():
            if child.type == "link_open":
                yield child.attrGet("href")
            elif child.type == "image":
                yield child.attrGet("src")


def _closed_fence(token) -> bool:
    start, end = token.map
    content_lines = len(markdown_lines(token.content))
    return end - start == content_lines + 2


def headings(text):
    tokens = MARKDOWN.parse(text)
    return [(token.tag, tokens[i + 1].content) for i, token in enumerate(tokens)
            if token.type == "heading_open" and token.level == 0]


def computation_section(text: str) -> tuple[bool, bool]:
    """Return whether the document has a Computation section and a closed fence in it."""
    tokens = MARKDOWN.parse(text)
    found = False
    level = 0
    for i, token in enumerate(tokens):
        if token.level != 0:
            continue
        if token.type == "heading_open":
            depth = int(token.tag[1:])
            if token.markup.startswith("#") and tokens[i + 1].content == "Computation":
                found = True
                level = depth
            elif depth <= level:
                level = 0
        elif level and token.type == "fence" and _closed_fence(token):
            return True, True
    return found, False


def index_append_boundary(text: str, sections: list[IndexSection], eof: int) -> tuple[int, str]:
    """Choose a top-level insertion point without extending a trailing raw block."""
    tokens = MARKDOWN.parse(text)
    if tokens and tokens[-1].type == "html_block":
        # Keep the entire final section together, including its curated HTML.
        position = sections[-1].line if sections else tokens[-1].map[0]
        return position, ""
    if tokens and tokens[-1].type == "fence":
        fence = tokens[-1]
        if not _closed_fence(fence):
            return eof, fence.markup
    return eof, ""


def index_sections(text: str) -> list[IndexSection]:
    """Only actual headings and bullet items count, including reference links."""
    tokens = MARKDOWN.parse(text)
    sections = []
    for i, token in enumerate(tokens):
        if token.type == "heading_open" and token.level == 0:
            sections.append(IndexSection(token.map[0], token.map[1], tokens[i + 1].content))
        if not sections or token.type != "list_item_open" or token.level != 1:
            continue
        if token.markup not in ("*", "-", "+"):
            continue
        if tokens[i + 1].type != "paragraph_open":
            continue
        inline = tokens[i + 2]
        children = inline.children or []
        if not children or children[0].type != "link_open":
            continue
        end = next(j for j, part in enumerate(children) if part.type == "link_close")
        title = "".join(part.content for part in children[1:end]).strip()
        target = children[0].attrGet("href")
        if title and target:
            description = "".join(part.content for part in children[end + 1:]).lstrip(" -–—:\t")
            sections[-1].entries.append(IndexEntry(token.map[0], inline.map[1], token.map[1], title, target, description))
    return sections
