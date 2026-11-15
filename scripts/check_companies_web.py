"""Check the honey companies found on the web before they are shown (reference/companies_web.py).

    python scripts/check_companies_web.py CANDIDATES.json [MORE.json ...] --out SEED.json --report REPORT.json
    python scripts/check_companies_web.py --recheck          (the seed itself: which entries still pass)

A candidate is {"iso3", "name", "role", "city", "website", "source_url", "what_it", "what_en"}. It is
kept only when Paladex can open the company's own page and that page (its text, title or
description) speaks of honey and carries the company's name (or the name is the site's address).
Everything else is left out and listed in the report with the reason: a site that refuses automated
readers is not worked around, it is simply not shown.

One polite request per site (generic client name, as every Paladex collector), a second address
(the home page) when the first fails, and a few retries when the name look-up fails.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "backend" / "paladex" / "reference" / "companies_web_seed.json"
UA = "Paladex/0.1 (internal research tool)"
ROLES = {"exporter", "packer", "cooperative", "importer", "trader"}
NOT_OWN_SITE = ("alibaba.", "made-in-china.", "tridge.", "volza.", "europages.", "kompass.", "linkedin.", "facebook.",
                "instagram.", "wikipedia.", "youtube.", "twitter.", "indiamart.", "tradeindia.", "exportersindia.",
                "go4worldbusiness.", "ec21.", "globalsources.", "yellowpages", "paginasamarillas", "dnb.com", "zoominfo.",
                "crunchbase.", "bloomberg.", "importgenius.", "panjiva.", "trademap.", "google.")
# "honey" in the languages of the countries searched; short words only as whole words
HONEY = re.compile(
    r"honey|honig|honing|miele\b|\bmiel\b|\bmieles\b|\bmel\b|\bm[eé]z\b|\bmed\b|\bmedu\b|\bmiere\b|mi[oó]d|\bbal\b|medus|"
    r"мед|мёд|μέλι|μελι|mật ong|蜂蜜|عسل|น้ำผึ้ง|apicol|apicult|apiari|beekeep|imker|pszczel|včel|pčel|albine|"
    # Nordic, Baltic, Albanian, Maltese, Luxembourgish, Icelandic (folded text: "ë" -> "e", "ħ" stays)
    r"hunaja|honung|honning|mesi|mee|mjalt|ghasel|għasel|hunneg|hunang|biodl|mehilai|mesinik|cebel|bit[eė]s|bišu",
    re.I)
GENERIC = {"honey", "honig", "miel", "miele", "mel", "mieles", "company", "group", "grupo", "gruppo", "foods", "food", "trading",
           "export", "exports", "import", "international", "limited", "ltd", "gmbh", "srl", "spa", "sa", "s.a.", "inc", "llc",
           "co", "corp", "cooperativa", "cooperative", "sociedad", "the", "and", "de", "del", "la", "le", "les", "di", "da",
           "natural", "products", "apiaries", "apicola", "apícola", "bee", "bees"}


def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))


def name_tokens(name: str) -> list[str]:
    return [t for t in re.split(r"[^0-9a-zA-ZÀ-￿]+", fold(name)) if len(t) >= 3 and t not in GENERIC]


def page_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    meta = " ".join(m.get("content", "") for m in soup.find_all("meta") if m.get("name") in ("description", "keywords")
                    or m.get("property") in ("og:title", "og:description", "og:site_name"))
    title = soup.title.get_text(" ") if soup.title else ""
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return f"{title} {meta} {soup.get_text(' ')}"


def fetch(client: httpx.Client, url: str) -> tuple[str | None, str]:
    """(html, problem). A failed name look-up is tried again; an error status is final."""
    last = "no answer"
    for attempt in range(4):
        try:
            r = client.get(url)
        except httpx.ConnectError as exc:
            last = f"cannot connect ({type(exc).__name__})"
            time.sleep(6)
            continue
        except httpx.HTTPError as exc:
            return None, f"{type(exc).__name__}"
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        if "html" not in r.headers.get("content-type", "html"):
            return None, f"not a web page ({r.headers.get('content-type')})"
        return r.text, ""
    return None, last


def check(client: httpx.Client, e: dict) -> tuple[bool, str]:
    site = str(e.get("website") or "").strip()
    host = urlparse(site).hostname or ""
    if not site.startswith(("http://", "https://")) or not host:
        return False, "no website"
    if any(bad in host for bad in NOT_OWN_SITE) or host in ("x.com", "www.x.com"):
        return False, f"not the company's own site ({host})"
    if not str(e.get("name") or "").strip() or e.get("role") not in ROLES or len(str(e.get("iso3") or "")) != 3:
        return False, "name, role or country missing"
    problems = []
    for url in dict.fromkeys([e.get("source_url") or site, site, f"https://{host}/"]):
        if not str(url).startswith(("http://", "https://")) or (urlparse(str(url)).hostname or "") != host:
            continue        # the page checked is always on the company's own site
        html, problem = fetch(client, str(url))
        if html is None:
            problems.append(f"{url}: {problem}")
            continue
        text = fold(page_text(html))
        if not HONEY.search(text) and not HONEY.search(host):
            problems.append(f"{url}: the page does not speak of honey")
            continue
        tokens = name_tokens(e["name"])
        squeezed = re.sub(r"[^0-9a-z]", "", fold(host))
        if tokens and not any(t in text or t in squeezed for t in tokens):
            problems.append(f"{url}: the company name is not on the page")
            continue
        return True, str(url)
    return False, "; ".join(problems) or "no page on the company's own site"


def main() -> int:
    for stream in (sys.stdout, sys.stderr):      # company names in any alphabet, on any console
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--out", default=str(SEED))
    ap.add_argument("--report")
    ap.add_argument("--recheck", action="store_true")
    ap.add_argument("--searched-on")
    args = ap.parse_args()
    files = [str(SEED)] if args.recheck else args.files
    if not files:
        ap.error("give the candidate files, or --recheck")
    candidates, searched = [], args.searched_on
    for f in files:
        doc = json.loads(Path(f).read_text(encoding="utf-8"))
        searched = searched or doc.get("searched_on")
        candidates += doc.get("entries") or []
    seen, kept, dropped = set(), [], []
    with httpx.Client(headers={"User-Agent": UA, "Accept-Language": "en,it;q=0.8"}, timeout=25, follow_redirects=True) as client:
        for e in candidates:
            key = (str(e.get("iso3")).upper(), urlparse(str(e.get("website") or "")).hostname or fold(str(e.get("name"))))
            if key in seen:
                continue
            seen.add(key)
            ok, detail = check(client, e)
            print(("OK   " if ok else "DROP ") + f"{e.get('iso3')} {e.get('name')}: {detail}"[:200], flush=True)
            if ok:
                kept.append({"iso3": str(e["iso3"]).upper(), "name": str(e["name"]).strip(), "role": e["role"],
                             "city": (str(e["city"]).strip() or None) if e.get("city") else None,
                             "website": str(e["website"]).strip(), "source_url": detail,
                             "what_it": (e.get("what_it") or "").strip() or None, "what_en": (e.get("what_en") or "").strip() or None})
            else:
                dropped.append({"iso3": e.get("iso3"), "name": e.get("name"), "website": e.get("website"), "reason": detail})
            time.sleep(0.5)
    kept.sort(key=lambda x: (x["iso3"], x["name"].casefold()))
    if args.recheck:
        print(f"{len(kept)} of {len(candidates)} still pass; {len(dropped)} do not (nothing written)")
    else:
        Path(args.out).write_text(json.dumps({"searched_on": searched, "entries": kept}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"kept {len(kept)}, left out {len(dropped)} -> {args.out}")
    if args.report:
        Path(args.report).write_text(json.dumps({"kept": len(kept), "dropped": dropped}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
