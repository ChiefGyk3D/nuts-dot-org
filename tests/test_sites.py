"""Checks for the two sites.

Everything here is stdlib. There is no build step, so these tests read the
files that get deployed and assert the properties the sites depend on:

* the two sides stay in sync where they are meant to be identical,
* each side points at the other and only at the other,
* no page loads anything from a third party,
* the headers the hosts serve from ``_headers`` match what the pages need,
* the CI workflow is pinned the way the rest of the maintainer's repos are.

Each test has been broken on purpose once and seen to go red; the docstring
says how.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITES = ROOT / "sites"

SIDES = {
    "left": {"domain": "myleftnut.org", "other": "right"},
    "right": {"domain": "myrightnut.org", "other": "left"},
}
DOMAINS = {s: f"https://{v['domain']}" for s, v in SIDES.items()}
SOURCE_REPO = "https://github.com/ChiefGyk3D/nuts-dot-org"

# Files every side must ship. The set is asserted exactly, so a file added to
# one side and forgotten on the other fails.
EXPECTED_FILES = {
    "index.html",
    "404.html",
    "style.css",
    "app.js",
    "status.json",
    "favicon.svg",
    "robots.txt",
    "_headers",
}

# These are byte-identical across sides on purpose; the theming hangs off
# html[data-side]. A fix applied to one copy and not the other fails here.
SHARED_FILES = {"style.css", "app.js", "robots.txt"}

VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}


class Page(HTMLParser):
    """A small structural parser: tag balance, attributes, text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.errors: list[str] = []
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.text: list[str] = []
        self.ids: list[str] = []
        self.has_doctype = False

    def handle_decl(self, decl: str) -> None:
        if decl.lower().startswith("doctype"):
            self.has_doctype = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        self.tags.append((tag, a))
        if "id" in a and a["id"]:
            self.ids.append(a["id"])
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(
                f"</{tag}> at line {self.getpos()[0]} closes "
                f"<{self.stack[-1] if self.stack else 'nothing'}>"
            )
            return
        self.stack.pop()

    def handle_data(self, data: str) -> None:
        self.text.append(data)

    def attrs(self, tag: str) -> list[dict[str, str | None]]:
        return [a for t, a in self.tags if t == tag]


def parse(path: Path) -> Page:
    p = Page()
    p.feed(path.read_text(encoding="utf-8"))
    p.close()
    assert p.has_doctype, f"{path}: no <!doctype html>"
    assert not p.errors, f"{path}: {p.errors}"
    assert not p.stack, f"{path}: unclosed tags {p.stack}"
    return p


def html_pages() -> list[tuple[str, Path]]:
    return [
        (side, SITES / side / "public" / name)
        for side in SIDES
        for name in ("index.html", "404.html")
    ]


# ---------------------------------------------------------------------------
# layout and sync


def test_both_sides_ship_the_same_files() -> None:
    """Break: delete sites/right/public/robots.txt."""
    for side in SIDES:
        have = {p.name for p in (SITES / side / "public").iterdir()}
        assert have == EXPECTED_FILES, f"{side}: {have ^ EXPECTED_FILES}"


@pytest.mark.parametrize("name", sorted(SHARED_FILES))
def test_shared_files_are_identical(name: str) -> None:
    """Break: change one character in sites/left/public/app.js only."""
    left = (SITES / "left" / "public" / name).read_bytes()
    right = (SITES / "right" / "public" / name).read_bytes()
    assert left == right, f"{name} differs between sides; copy the fixed one over"


def test_stylesheet_themes_both_sides() -> None:
    """Break: remove the html[data-side="right"] block from style.css."""
    css = (SITES / "left" / "public" / "style.css").read_text()
    for side in SIDES:
        assert f'html[data-side="{side}"]' in css, side


def test_netlify_config_per_side() -> None:
    """Break: set publish = "dist" in one netlify.toml."""
    for side in SIDES:
        toml = (SITES / side / "netlify.toml").read_text()
        assert re.search(r'^\s*publish\s*=\s*"public"\s*$', toml, re.M), side
        assert re.search(r'^\s*command\s*=\s*""\s*$', toml, re.M), side


# ---------------------------------------------------------------------------
# pages


@pytest.mark.parametrize("side,path", html_pages(), ids=lambda v: getattr(v, "name", v))
def test_page_basics(side: str, path: Path) -> None:
    """Break: remove the <meta name="viewport"> line from a page."""
    page = parse(path)
    html = page.attrs("html")[0]
    assert html.get("lang") == "en"
    assert html.get("data-side") == side
    assert html.get("data-other") == DOMAINS[SIDES[side]["other"]]

    metas = {a.get("name"): a.get("content") for a in page.attrs("meta")}
    assert "width=device-width" in (metas.get("viewport") or "")
    assert metas.get("description"), "description missing"
    assert any("charset" in a for a in page.attrs("meta"))
    assert len(page.attrs("title")) == 1
    assert len(page.attrs("h1")) == 1, "exactly one h1"
    assert len(page.ids) == len(set(page.ids)), "duplicate ids"
    assert "TODO" not in path.read_text() and "lorem" not in path.read_text().lower()


@pytest.mark.parametrize("side,path", html_pages(), ids=lambda v: getattr(v, "name", v))
def test_page_names_its_own_side_and_links_the_other(side: str, path: Path) -> None:
    """Break: change the brand <b>left</b> to <b>right</b> on the left site."""
    page = parse(path)
    text = " ".join(page.text)
    assert f"my{side}nut" in text.replace(" ", "").replace("\n", ""), "brand text"
    hrefs = {a.get("href") for a in page.attrs("a")}
    other = DOMAINS[SIDES[side]["other"]] + "/"
    assert other in hrefs, f"{path.name} does not link to {other}"
    assert DOMAINS[side] + "/" not in hrefs, "a side should not link to itself by domain"


@pytest.mark.parametrize("side,path", html_pages(), ids=lambda v: getattr(v, "name", v))
def test_page_loads_nothing_from_third_parties(side: str, path: Path) -> None:
    """Break: add <script src="https://cdn.example.com/x.js">.

    Sub-resources (scripts, styles, images, icons) must be same-origin, so
    the CSP's default-src 'none' holds and nobody else sees a visitor. Links
    may leave the site, but only to the sibling or the source repository.
    """
    page = parse(path)
    allowed_hosts = {SIDES[side]["domain"], SIDES[SIDES[side]["other"]]["domain"], "github.com"}
    for tag, attrs in page.tags:
        for key in ("src", "href"):
            value = attrs.get(key)
            if not value:
                continue
            url = urlparse(value)
            if tag == "link" and attrs.get("rel") == "canonical":
                assert value == DOMAINS[side] + "/", f"canonical is {value}"
                continue
            if tag in {"script", "link", "img", "source", "iframe"}:
                assert url.scheme == "" and url.netloc == "", f"<{tag} {key}={value}> is remote"
                assert value.startswith("/"), f"<{tag} {key}={value}> should be root-relative"
            else:
                assert url.netloc in allowed_hosts | {""}, f"<{tag} {key}={value}> leaves the family"
                if url.netloc:
                    assert url.scheme == "https", value
    assert not any(t in {"iframe", "embed", "object"} for t, _ in page.tags)
    assert not any(a.get("onclick") or a.get("onload") for _, a in page.tags), "inline handlers"
    assert not any(t == "style" for t, _ in page.tags), "inline <style> breaks the CSP"
    assert not any(t == "script" and "src" not in a for t, a in page.tags), "inline <script> breaks the CSP"


@pytest.mark.parametrize("side", sorted(SIDES))
def test_index_has_the_hooks_app_js_expects(side: str) -> None:
    """Break: rename id="flip" in index.html."""
    page = parse(SITES / side / "public" / "index.html")
    js = (SITES / side / "public" / "app.js").read_text()
    for needed in re.findall(r'getElementById\("([^"]+)"\)', js):
        assert needed in page.ids, f"app.js looks up #{needed}; index.html has no such id"


@pytest.mark.parametrize("side", sorted(SIDES))
def test_source_link_matches_repo(side: str) -> None:
    """Break: point the footer Source link at a different repo."""
    text = (SITES / side / "public" / "index.html").read_text()
    assert SOURCE_REPO in text


# ---------------------------------------------------------------------------
# status.json and headers


@pytest.mark.parametrize("side", sorted(SIDES))
def test_status_json(side: str) -> None:
    """Break: set "side": "left" in sites/right/public/status.json."""
    data = json.loads((SITES / side / "public" / "status.json").read_text())
    assert data["side"] == side
    assert data["status"] == "present"
    assert isinstance(data["mood"], str) and data["mood"]
    assert data["sibling"] == DOMAINS[SIDES[side]["other"]]
    assert data["source"] == SOURCE_REPO


def parse_headers(text: str) -> dict[str, dict[str, str]]:
    """Netlify/Cloudflare _headers: a path line, then indented Name: Value."""
    out: dict[str, dict[str, str]] = {}
    path = None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if not raw[0].isspace():
            path = raw.strip()
            out[path] = {}
        else:
            assert path, f"header line before any path: {raw!r}"
            name, _, value = raw.strip().partition(":")
            out[path][name.strip()] = value.strip()
    return out


@pytest.mark.parametrize("side", sorted(SIDES))
def test_headers_file(side: str) -> None:
    """Break: drop the sibling from connect-src, or the CORS line on status.json."""
    headers = parse_headers((SITES / side / "public" / "_headers").read_text())
    assert set(headers) == {"/*", "/status.json"}
    csp = headers["/*"]["Content-Security-Policy"]
    directives = {d.split()[0]: d.split()[1:] for d in csp.split(";") if d.strip()}
    assert directives["default-src"] == ["'none'"]
    assert directives["script-src"] == ["'self'"]
    assert directives["style-src"] == ["'self'"]
    assert "'unsafe-inline'" not in csp and "'unsafe-eval'" not in csp
    # app.js fetches the sibling's status.json; the CSP must allow exactly that.
    assert set(directives["connect-src"]) == {"'self'", DOMAINS[SIDES[side]["other"]]}
    assert directives["frame-ancestors"] == ["'none'"]
    assert headers["/*"]["X-Content-Type-Options"] == "nosniff"
    assert headers["/*"]["Referrer-Policy"]
    # ...and the sibling must be allowed to read ours.
    assert headers["/status.json"]["Access-Control-Allow-Origin"] == "*"
    assert headers["/status.json"]["Cache-Control"] == "no-store"


def test_app_js_only_talks_to_the_sibling() -> None:
    """Break: add fetch("https://example.com/") to app.js."""
    js = (SITES / "left" / "public" / "app.js").read_text()
    assert "innerHTML" not in js and "eval(" not in js and "document.write" not in js
    assert js.count("fetch(") == 1
    for url in re.findall(r"https?://[^\s\"'`)]+", js):
        pytest.fail(f"hardcoded URL in app.js: {url}; read it from data-other instead")
    code = "\n".join(l for l in js.splitlines() if not l.lstrip().startswith("//"))
    assert code.count("localStorage.getItem") == 1 and code.count("localStorage.setItem") == 1, (
        "storage goes through the store wrapper only"
    )


# ---------------------------------------------------------------------------
# repo hygiene


def test_workflow_actions_are_pinned_to_commits() -> None:
    """Break: change a `uses:` to @v7.

    Every action is pinned to a 40-hex commit with the version in a trailing
    comment, and the workflow asks for read-only contents. Resolve a pin with
    `git ls-remote --tags https://github.com/<owner>/<action>`, never from
    memory.
    """
    for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
        text = wf.read_text()
        uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)(.*)$", text, re.M)
        assert uses, wf
        for ref, rest in uses:
            assert re.fullmatch(r"[\w.-]+/[\w.-]+(/[\w.-]+)*@[0-9a-f]{40}", ref), f"{wf.name}: {ref} is not SHA-pinned"
            assert re.search(r"#\s*v\d", rest), f"{wf.name}: {ref} has no version comment"
        assert re.search(r"^permissions:\s*\n\s+contents:\s*read", text, re.M), f"{wf.name}: permissions"
        assert "persist-credentials: false" in text, f"{wf.name}: checkout keeps credentials"


def test_readme_names_both_domains_and_both_hosts() -> None:
    """Break: remove myrightnut.org from README.md."""
    readme = (ROOT / "README.md").read_text()
    for domain in ("myleftnut.org", "myrightnut.org"):
        assert domain in readme
    for host in ("Netlify", "Cloudflare Pages"):
        assert host in readme
    assert "## Deploying" in readme


def test_no_tracked_secrets_or_envs() -> None:
    """Break: add a .env file at the repo root."""
    for p in ROOT.rglob("*"):
        if "node_modules" in p.parts or ".git" in p.parts:
            continue
        assert p.name not in {".env", ".env.local", "secrets.json"}, p
