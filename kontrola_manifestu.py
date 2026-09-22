"""CI gate: the code must not contradict data-manifest.json.

Version 1 is a deliberately crude, deterministic heuristic: it greps the
deployed files for patterns that would mean network calls or browser storage
the manifest does not declare. It cannot prove compliance -- it exists so the
manifest cannot drift from reality *silently*, which is the failure mode that
turns a policy document into an aggravating circumstance. The legal template
itself is written and frozen by a human lawyer, never generated.

Stdlib only, so the CI step needs nothing but python3.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# The messages carry Czech diacritics; a Windows console defaulting to a
# legacy codepage must not turn a failed check into a UnicodeEncodeError.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

WEB = Path("web")
MANIFEST = Path("data-manifest.json")

# Patterns that mean an outbound request from the page (loading a foreign
# resource or calling out). Plain links (<a href="http...">) are fine -- the
# user clicks them; resources load without asking.
NETWORK_PATTERNS = (
    "fetch(",
    "XMLHttpRequest",
    "sendBeacon",
    "new WebSocket",
    '<script src="http',
    "<script src='http",
    'href="http',  # only checked inside <link ...> lines, see below
    "@import url(http",
    '<img src="http',
    "<img src='http",
)

STORAGE_PATTERNS = (
    "localStorage",
    "sessionStorage",
    "indexedDB",
    "document.cookie",
)


def _zkontroluj_design() -> list[str]:
    """The cheap, deterministic part of the design bar: every deployed page
    uses the shared design system and is a mobile page. The taste part is
    the reviewer's; this stops the "web form with its own CSS" failure mode
    before a model ever looks at it."""
    chyby: list[str] = []
    for path in sorted(WEB.glob("*.html")):
        if path.name == "zasady.html":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if 'href="styl.css"' not in text:
            chyby.append(f"{path}: nepoužívá návrhový systém web/styl.css (viz DESIGN.md).")
        if 'name="viewport"' not in text:
            chyby.append(f"{path}: chybí <meta name=\"viewport\"> — není to mobilní stránka.")
        if '<link rel="stylesheet" href="http' in text or "@import" in text:
            chyby.append(f"{path}: externí styl/písmo — produkty jsou bez závislostí.")
    if not (WEB / "styl.css").exists():
        chyby.append("web/styl.css chybí — návrhový systém je součást každého produktu.")
    return chyby


def _zkontroluj_aplikaci(manifest: dict) -> list[str]:
    """The installable-app module (vykresli_aplikaci.py): off without an
    `aplikace` section; on, every generated file must equal the generator."""
    if "aplikace" not in manifest:
        return []
    try:
        import vykresli_aplikaci
    except ImportError:
        return ["data-manifest.json zapíná modul aplikace, ale chybí vykresli_aplikaci.py "
                "(obnoví ho příští stavba ze šablony)."]
    return vykresli_aplikaci.zkontroluj(manifest)


def _generovane(manifest: dict) -> set[Path]:
    """Files owned by a generator that proves them separately — the service
    worker has to fetch and cache, which the scans below would flag."""
    try:
        import vykresli_aplikaci
    except ImportError:
        return set()
    return vykresli_aplikaci.generovane_soubory(manifest)


def main() -> int:
    if not MANIFEST.exists():
        print("CHYBA: chybí data-manifest.json.")
        return 1
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    violations: list[str] = []
    preskocit = _generovane(manifest)

    for path in sorted(WEB.rglob("*")):
        if path in preskocit:
            continue
        if not path.is_file() or path.suffix.lower() not in (
            ".html", ".htm", ".js", ".css", ".mjs",
        ):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()

        if manifest.get("externi_pozadavky") == "zadne":
            for number, line in enumerate(lines, 1):
                for pattern in NETWORK_PATTERNS:
                    if pattern == 'href="http':
                        # An external stylesheet is a request; a plain link is not.
                        if "<link" in line and pattern in line:
                            violations.append(f"{path}:{number}: externí <link> ({line.strip()[:80]})")
                        continue
                    if pattern in line:
                        violations.append(f"{path}:{number}: {pattern} ({line.strip()[:80]})")

        if not manifest.get("uloziste_v_prohlizeci"):
            for number, line in enumerate(lines, 1):
                for pattern in STORAGE_PATTERNS:
                    if pattern in line:
                        violations.append(f"{path}:{number}: {pattern} ({line.strip()[:80]})")

    violations += _zkontroluj_design()
    violations += _zkontroluj_aplikaci(manifest)
    if violations:
        print("Kód se rozešel s data-manifest.json nebo s DESIGN.md:")
        for violation in violations:
            print(" -", violation)
        print("Buď to z kódu odstraň, nebo to deklaruj v manifestu (a v zásadách).")
        return 1
    print("Manifest souhlasí s kódem.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
