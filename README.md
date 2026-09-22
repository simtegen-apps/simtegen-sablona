# Produkt SimteGen

Repozitář vznikl ze šablony `simtegen-sablona`. Pravidla, která drží celý
podnik, platí i tady:

- **`web/` je jediné, co se nasazuje.** Statická stránka bez závislostí a
  bez build systému — musí jít otevřít lokálně ze souboru.
- **Neukládá se obsah zákazníka.** Ideálně neopustí jeho prohlížeč. Co se
  přesto sbírá, deklaruje `data-manifest.json` — a CI shodí build, když se
  kód s manifestem rozejde (`kontrola_manifestu.py`).
- **Nasazuje se výhradně merge do `main`.** Stavitel (SimteGen) pushuje jen
  větve `build/*` a otevírá pull requesty; merge je lidské rozhodnutí.
  Push větve zároveň vytvoří preview nasazení na Cloudflare Pages.
- **`.github/` patří člověku.** SimteGen na workflow soubory nesahá — jeho
  token na ně ani nemá právo, GitHub takový push odmítne celý.

Produkční URL: `https://<název-repa>.pages.dev` (projekt na Cloudflare Pages
se jmenuje po repozitáři). Preview větve: `https://<větev>.<název-repa>.pages.dev`.

**Design je součást zadání.** `web/styl.css` je jediný návrhový systém
(barvy, písma, rozměry, komponenty) a `DESIGN.md` říká, jak z něj skládat
obrazovku: čtyři stavy (prázdný, načítání, chyba, úspěch), hlavní akce
v dosahu palce, dotykové cíle 44 px, žádné vlastní barvy ani externí
písma. CI hlídá deterministickou část (styl.css, viewport, žádné externí
styly); recenzent hlídá zbytek a vzhled webového formuláře vrací.

**Aplikace do Google Play je modul, ne jiný produkt.** Sekce `aplikace`
v `data-manifest.json` (balíček, název ≤ 30, krátký název ≤ 12, popis ≤ 80,
otisky podpisového klíče) a `python vykresli_aplikaci.py` z webu udělají
instalovatelnou aplikaci: manifest, ikony z návrhového systému, offline
stránku, service worker (nikdy nesahá na `/api/`), `.well-known/assetlinks.json`
a odkazy v `index.html`. Nic z toho se needituje ručně — CI to porovnává
s generátorem. Balíček se po prvním vydání nesmí změnit nikdy. Sestavení
a nahrání na interní kanál dělá workflow **Vydani** v repu šablony (vstup
`projekt`); do produkce aplikaci pouští majitel klepnutím v Play Console.
