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
import re
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


LEGAL_PAGES = ("zasady.html",)

# Design system v2 („Mřížka a papír“). The files are template
# infrastructure (the builder refreshes them on every build); produkt.css
# is the product's only design input.
NAVRH_SOUBORY = (
    "web/styl.css", "web/produkt.css", "web/simtegen.js",
    "web/pismo/schibsted-grotesk.woff2", "web/pismo/plex-mono-400.woff2", "web/pismo/plex-mono-500.woff2",
)
PRAVNI_STRANKY = LEGAL_PAGES
_BARVA = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\s*\(")
_STYL_ATRIBUT = re.compile(r"""\sstyle\s*=\s*("[^"]*"|'[^']*')""", re.IGNORECASE)
_STYL_BLOK = re.compile(r"<style\b[^>]*>(.*?)</style>", re.IGNORECASE | re.DOTALL)
_SVG_BARVA = re.compile(r"""\s(?:fill|stroke|stop-color)\s*=\s*("[^"]*"|'[^']*')""", re.IGNORECASE)
PAPIR_SVETLY, PAPIR_TMAVY = "#f6f4ef", "#161513"


def _jas(hex_barva: str) -> float:
    h = hex_barva.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    kanaly = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        kanaly.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * kanaly[0] + 0.7152 * kanaly[1] + 0.0722 * kanaly[2]


def kontrast(a: str, b: str) -> float:
    la, lb = sorted((_jas(a), _jas(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _zkontroluj_produkt_css() -> list[str]:
    """produkt.css: only --barva-produktu (light, optionally dark) and
    readable on the paper — the product's colour is a pointer and a word
    like „Dnes“, so it must pass as text."""
    cesta = WEB / "produkt.css"
    if not cesta.exists():
        return []
    text = re.sub(r"/\*.*?\*/", "", cesta.read_text(encoding="utf-8"), flags=re.DOTALL)
    chyby: list[str] = []
    deklarace = re.findall(r"([-\w]+)\s*:\s*([^;{}]+);", text)
    for nazev, _ in deklarace:
        if nazev != "--barva-produktu":
            chyby.append(f"web/produkt.css smí nastavit jen --barva-produktu, ne {nazev}.")
    zbytek = re.sub(r"[-\w]+\s*:\s*[^;{}]+;", "", text)
    zbytek = re.sub(r"@media\s*\(\s*prefers-color-scheme\s*:\s*dark\s*\)", "", zbytek)
    if re.sub(r"[\s{}]|:root", "", zbytek):
        chyby.append("web/produkt.css obsahuje něco jiného než :root s --barva-produktu "
                     "(a volitelně totéž v @media (prefers-color-scheme: dark)).")
    tmavy = re.search(r"@media[^{]*dark[^{]*\{(.*)\}", text, re.DOTALL)
    svetla_cast = text[:tmavy.start()] if tmavy else text
    for cast, papir, rezim in ((svetla_cast, PAPIR_SVETLY, "světlém"),
                               (tmavy.group(1) if tmavy else "", PAPIR_TMAVY, "tmavém")):
        m = re.search(r"--barva-produktu\s*:\s*(#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3})\s*;", cast)
        if not m:
            if rezim == "světlém":
                chyby.append("web/produkt.css nemá --barva-produktu jako #hex.")
            continue
        k = kontrast(m.group(1), papir)
        if k < 4.5:
            chyby.append(f"Barva produktu {m.group(1)} má v {rezim} režimu na papíře kontrast {k:.1f}:1 "
                         "— potřeba aspoň 4.5:1 (tmavší ve světlém, světlejší v tmavém).")
    return chyby


def _barvy_v_html(text: str) -> list[str]:
    nalezy: list[str] = []
    for m in list(_STYL_ATRIBUT.finditer(text)) + list(_SVG_BARVA.finditer(text)):
        hodnota = m.group(1)[1:-1]
        if _BARVA.search(hodnota):
            nalezy.append(m.group(0).strip()[:60])
    for m in _STYL_BLOK.finditer(text):
        if _BARVA.search(m.group(1)):
            nalezy.append("<style> s barvou")
    return nalezy


def _zkontroluj_design() -> list[str]:
    """The deterministic part of the design bar (v2). The taste part — one
    main action, the four states, detail that carries information — is the
    reviewer's, from screenshots."""
    chyby: list[str] = []
    for rel in NAVRH_SOUBORY:
        if not Path(rel).exists():
            chyby.append(f"{rel} chybí — návrhový systém v2 je součást každého produktu "
                         "(stavitel ho obnovuje ze šablony).")
    styl = WEB / "styl.css"
    if styl.exists() and "simtegen-navrh v2" not in styl.read_text(encoding="utf-8")[:200]:
        chyby.append("web/styl.css není návrhový systém v2 — v produktu se neupravuje, obnoví ho stavba.")
    chyby += _zkontroluj_produkt_css()
    for path in sorted(WEB.glob("*.html")):
        if path.name in PRAVNI_STRANKY or path.name == "offline.html":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for odkaz, co in (('href="styl.css"', "styl.css"), ('href="produkt.css"', "produkt.css"),
                          ('src="simtegen.js"', "simtegen.js (úvodní obrazovka s logem)")):
            if odkaz not in text:
                chyby.append(f"{path}: nenačítá {co} (viz Kostra v DESIGN.md).")
        if 'name="viewport"' not in text:
            chyby.append(f"{path}: chybí <meta name=\"viewport\"> — není to mobilní stránka.")
        if 'name="application-name"' not in text:
            chyby.append(f"{path}: chybí <meta name=\"application-name\"> — název produktu pro úvodní obrazovku.")
        # Mandatory reporting: simtegen.js opens the form for any element with
        # this class; a page without one leaves the customer no way to tell us.
        if "nahlasit-chybu" not in text:
            chyby.append(f"{path}: chybí tlačítko „Nahlásit chybu“ (class=\"nahlasit-chybu\") — "
                         "hlášení chyb je povinné na každé stránce aplikace.")
        if '<link rel="stylesheet" href="http' in text or "@import" in text:
            chyby.append(f"{path}: externí styl/písmo — produkty jsou bez závislostí.")
        for nalez in _barvy_v_html(text):
            chyby.append(f"{path}: barva zapsaná přímo v HTML ({nalez}) — barvy jsou jen ve styl.css "
                         "a produkt.css, použij třídu nebo proměnnou.")
    return chyby

def _zkontroluj_bezpecnost(manifest: dict, preskocit: set[Path]) -> list[str]:
    """bezpecnostni_kontrola.py: who may call which endpoint, SQL only with
    bound values, customer data filtered by uzivatel_id, no HTML or code
    built from text, no keys in the repository, the CSP header. Infra like
    this checker — the build refreshes it, so every product gets the rules."""
    if not Path("bezpecnostni_kontrola.py").exists():
        return ["chybí bezpecnostni_kontrola.py — je součást šablony (stavitel ho obnovuje při stavbě)."]
    import bezpecnostni_kontrola

    return [f"bezpečnost: {c}" for c in bezpecnostni_kontrola.zkontroluj(Path.cwd(), manifest, preskocit)]


def _zkontroluj_vzhled() -> list[str]:
    """The rendered page (vizualni_kontrola.py): no sideways scroll at 360–1440
    px, labels, thumb-sized targets, contrast in light and dark. Mandatory on
    GitHub Actions, where Chrome always exists — a check that silently skips
    in CI would be a rule that looks enforced and is not. Elsewhere a missing
    browser skips it; VIZUALNI_KONTROLA=vypnuto skips it too, outside CI only
    (the template's own tests run this checker dozens of times)."""
    import os

    v_ci = os.environ.get("GITHUB_ACTIONS") == "true"
    if not v_ci and os.environ.get("VIZUALNI_KONTROLA") == "vypnuto":
        return []
    if not Path("vizualni_kontrola.py").exists():
        return ["chybí vizualni_kontrola.py — je součást šablony (stavitel ho obnovuje při stavbě)."]
    import vizualni_kontrola

    problemy, _, poznamka = vizualni_kontrola.zkontroluj(Path.cwd(), povinne=v_ci)
    if poznamka and not problemy:
        print("Vizuální kontrola:", poznamka)
    return [f"vzhled: {p}" for p in problemy]


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

        # simtegen.js is template infra (refreshed every build): its only
        # request is the report form to the product's own /api/ — not a call
        # out. Everything else on the page is still scanned.
        if manifest.get("externi_pozadavky") == "zadne" and path.name != "simtegen.js":
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
    violations += _zkontroluj_bezpecnost(manifest, preskocit)
    violations += _zkontroluj_vzhled()
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
