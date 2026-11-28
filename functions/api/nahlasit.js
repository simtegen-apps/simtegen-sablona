// POST /api/nahlasit {text, kontext} — nahlášení chyby BEZ přihlášení.
// Infrastruktura šablony (NEUPRAVOVAT V PRODUKTU), veřejný endpoint.
//
// Kdo se nedokáže přihlásit, je přesně ten, kdo potřebuje nahlásit chybu —
// a statická stránka účty nemá vůbec. Nic se tu neukládá: hlášení odejde
// šifrovaně firmě (schranka_sifra.js) a hotovo. Odpověď v aplikaci tu proto
// není; kdo ji chce, napíše do zprávy kontakt.
//
// Brzda proti spamu bez databáze (statická stránka D1 nemá): nejvýš LIMIT_IP
// hlášení za hodinu z jedné adresy a LIMIT celkem za hodinu na jedno datové
// centrum (Cache API). Adresa se do klíče dostane jen jako SHA-256 spolu
// s hodinou — nikdy sama. SimteGen má navíc vlastní strop na počet nových
// hlášení za den. (Produkty s databází počítají v D1: sablona_pamet/ochrana.js.)
//
// Selhání počítadla = odmítnutí (dřív se pustilo všechno, bezpečnostní
// kontrola 7. 11. 2026), a počítadlo, které si zápis nezapamatuje, je
// selhání také. Na adrese *.pages.dev je Cache API bez účinku (match nic
// nenajde, put nic neuloží), takže se tam hlášení nepřijímá vůbec —
// odpověď ukáže vlastní adresu aplikace (ta je u každého živého produktu,
// SimteGen ji zakládá a pages.dev na ni přesměruje).
//
// Jako v šabloně s pamětí (functions/api/_middleware.js): požadavek z cizí
// stránky (Origin / Sec-Fetch-Site) se odmítne a tělo musí být JSON —
// obyčejný formulář na jakékoli stránce umí poslat text/plain bez ptaní.

import { jsonOdpoved, ocistiKontext, zrcadliHlaseni, MIN_DELKA, MAX_DELKA } from "../../schranka_sifra.js";

const LIMIT = 10;
const LIMIT_IP = 5;

async function otisk(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function pricti(klic, max) {
  // true = pod limitem (a započteno). Chyba Cache API letí ven — i když
  // si cache zápis nezapamatovala: limit, který nepočítá, nic nebrzdí.
  const pozadavek = new Request(`https://limit.simtegen.invalid/${klic}`);
  const ulozeno = await caches.default.match(pozadavek);
  const pocet = ulozeno ? Number(await ulozeno.text()) || 0 : 0;
  if (pocet >= max) return false;
  await caches.default.put(pozadavek, new Response(String(pocet + 1), {
    headers: { "Cache-Control": "max-age=3600" },
  }));
  if (!(await caches.default.match(pozadavek))) throw new Error("cache nic neuložila");
  return true;
}

function zCiziStranky(request) {
  // Origin is what browsers send on every POST; Sec-Fetch-Site where an
  // older one does not. A request with neither is no browser.
  const puvod = request.headers.get("Origin");
  if (puvod) return puvod !== new URL(request.url).origin;
  const stranka = request.headers.get("Sec-Fetch-Site");
  if (stranka) return stranka !== "same-origin" && stranka !== "none";
  return false;
}

async function vlastniAdresa(context) {
  // The canonical link vykresli_seo.py writes into the page once the
  // product knows its address; empty when it does not.
  try {
    const stranka = await context.env.ASSETS.fetch(new URL("/", context.request.url));
    const html = stranka.ok ? await stranka.text() : "";
    const m = html.match(/<link\s[^>]*rel=["']canonical["'][^>]*href=["'](https:\/\/[^"'<>\s]+)["']/i)
      || html.match(/<link\s[^>]*href=["'](https:\/\/[^"'<>\s]+)["'][^>]*rel=["']canonical["']/i);
    const adresa = m ? new URL(m[1]) : null;
    return adresa && !adresa.hostname.endsWith(".pages.dev") ? adresa.origin : "";
  } catch {
    return "";
  }
}

async function vLimitu(request) {
  // "ok", "moc" (nad limitem) nebo "chyba" (počítadlo nejde).
  try {
    const hodina = Math.floor(Date.now() / 3600000);
    // Cloudflare hlavičku nastaví vždy a klient ji nepřepíše; bez ní jde
    // o lokální běh (jeden stroj, mnoho testů) — tam se nepočítá jen IP.
    const ip = request.headers.get("CF-Connecting-IP");
    if (ip && !(await pricti(`nahlasit-ip/${await otisk(`${ip}|${hodina}`)}`, LIMIT_IP))) return "moc";
    return (await pricti(`nahlasit/${hodina}`, LIMIT)) ? "ok" : "moc";
  } catch {
    return "chyba";
  }
}

export async function onRequestPost(context) {
  const { request, env } = context;
  if (zCiziStranky(request)) {
    return jsonOdpoved({ chyba: "Požadavek z cizí stránky jsme odmítli.", kod: "cizi_stranka" }, 403);
  }
  const typ = (request.headers.get("Content-Type") || "").split(";")[0].trim().toLowerCase();
  if (typ !== "application/json") {
    return jsonOdpoved({ chyba: "Požadavek musí být ve formátu JSON.", kod: "format" }, 415);
  }
  if (new URL(request.url).hostname.toLowerCase().endsWith(".pages.dev")) {
    const adresa = await vlastniAdresa(context);
    return jsonOdpoved({
      chyba: "Na této adrese hlášení nepřijímáme" + (adresa ? ` — otevřete prosím aplikaci na ${adresa}.` : "."),
      kod: "jina_adresa", ...(adresa ? { adresa } : {}),
    }, 403);
  }
  let telo;
  try {
    telo = await request.json();
  } catch {
    return jsonOdpoved({ chyba: "Neplatný požadavek." }, 400);
  }
  const text = String((telo && telo.text) || "").trim();
  if (text.length < MIN_DELKA) return jsonOdpoved({ chyba: "Napište nám prosím, o co jde." }, 422);
  if (text.length > MAX_DELKA) {
    return jsonOdpoved({ chyba: `Zpráva je moc dlouhá (max ${MAX_DELKA} znaků).` }, 422);
  }
  const limit = await vLimitu(request);
  if (limit === "moc") {
    return jsonOdpoved({ chyba: "Teď přijímáme hodně hlášení — zkuste to prosím za hodinu." }, 429);
  }
  if (limit === "chyba") {
    return jsonOdpoved({ chyba: "Hlášení teď nejde přijmout. Zkuste to prosím za chvíli." }, 503);
  }
  const cislo = await zrcadliHlaseni(env, "Hlášení (bez přihlášení)", {
    zdroj: "bez_prihlaseni", text, kontext: ocistiKontext(telo.kontext),
  });
  return jsonOdpoved({ stav: "prijato", predano: Boolean(cislo) });
}
