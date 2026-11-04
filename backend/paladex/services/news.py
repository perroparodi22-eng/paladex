"""News ingestion: URL canonicalisation, honey relevance gate, de-duplication, tagging and
relevance scoring.

`ingest_article()` is the single entry point used by collectors (via `ctx.add_news`). It
never fetches web pages; it only works on what the feed provides (headline, link, excerpt,
image, publisher).

Pipeline for one feed item:

1. clean the inputs (HTML stripped from title/excerpt, excerpt capped at ~600 chars,
   image taken from the excerpt's first <img> when the feed gives none);
2. canonicalise the link (tracking parameters, AMP variants and fragments removed;
   Google News redirect links replaced only when the feed itself carries the real URL);
   a link we already hold -> ``"unchanged"`` (gaps are filled: image, publisher and, when
   it was stored headline-only, the publisher's excerpt with the tags it adds);
3. honey gate: the headline + excerpt must be about honey / beekeeping (multilingual
   keyword set). Items failing the gate are NOT stored -> ``"filtered"``;
4. duplicates: an identical normalised headline, or a fuzzy match (rapidfuzz
   token_set_ratio >= 88) against non-duplicate articles dated within ±5 days, is stored
   with ``duplicate_of_id`` pointing at the first-seen article and that article's
   ``duplicate_count`` incremented -> ``"duplicate"`` (so we keep the record of which
   outlets reported the story). A fuzzy match is never a duplicate when the two headlines
   name different countries, carry different figures, or take opposite sides of a
   rise/fall or preliminary/final contrast: those are different stories;
5. otherwise -> stored as ``"new"``.

Every stored article is tagged with countries (ISO3), topics (keys of `TOPICS`) and a
0-100 relevance score for Parodi Group (bulk honey importer, Italy/USA) with a short,
machine-parseable `relevance_reason` (rendered in IT/EN by `explain_reason`).
"""
from __future__ import annotations

import html as htmlmod
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from rapidfuzz import fuzz
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import NewsArticle, Source, utcnow
from ..reference.countries import COUNTRY_KEYWORDS, country_name

Outcome = Literal["new", "unchanged", "duplicate", "filtered"]

# Short excerpt only (licensing: headline + link + very short extract; see DATA_SOURCES.md)
SNIPPET_MAX_CHARS = 300
DEDUP_WINDOW_DAYS = 5
FUZZY_THRESHOLD = 88
FUTURE_TOLERANCE = timedelta(hours=36)

# Origins Parodi Group buys from / watches, and its own markets.
ORIGINS_OF_INTEREST = ("ARG", "CHN", "UKR", "SRB", "BRA", "VNM", "IND", "URY", "MEX", "TUR", "HUN", "ROU")
HOME_MARKETS = ("ITA", "USA")


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def fold(text: str) -> str:
    """Lower-case, strip accents, normalise quotes/dashes. Used for keyword matching."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKD", text)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = t.replace("–", "-").replace("—", "-").replace(" ", " ")
    return t.lower()


_WS = re.compile(r"\s+")
_FEED_BOILERPLATE = [
    re.compile(r"\s*The post .{1,300}? appeared first on .{1,200}?\.?\s*$", re.I | re.S),
    re.compile(r"\s*L'articolo .{1,300}? proviene da .{1,200}?\.?\s*$", re.I | re.S),
    re.compile(r"\s*\[(?:…|\.\.\.|&hellip;)\]\s*"),
    re.compile(r"\s*(?:Continue reading|Read more|Read the full (?:story|article)|Leggi tutto|Continua a leggere|"
               r"Leer m[aá]s|Seguir leyendo|Leia mais|Weiterlesen)\s*(?:→|»|›|>|\.\.\.)?\s*$", re.I),
]


def strip_html(value: str | None) -> str:
    """Plain text from an HTML fragment (or from already-plain text with entities)."""
    if not value:
        return ""
    text = value
    if "<" in text and ">" in text:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(text, "html.parser")
        for tag in soup(["script", "style", "noscript", "iframe", "figure", "figcaption"]):
            tag.decompose()
        text = soup.get_text(" ", strip=True)
    text = htmlmod.unescape(text)
    return _WS.sub(" ", text).strip()


def truncate(text: str, limit: int = SNIPPET_MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,;:-") + "…"


def clean_title(title: str | None, publisher: str | None = None) -> str:
    t = strip_html(title)
    if publisher:
        t = strip_publisher_suffix(t, publisher)
    return t


def strip_publisher_suffix(title: str, publisher: str) -> str:
    """'Headline - Reuters' -> 'Headline' (aggregators append the outlet to the headline)."""
    pub = publisher.strip()
    if not pub:
        return title
    for sep in (" - ", " | ", " – ", " — ", " :: "):
        suffix = f"{sep}{pub}"
        if title.lower().endswith(suffix.lower()) and len(title) > len(suffix) + 3:
            return title[: -len(suffix)].rstrip()
    return title


def clean_snippet(value: str | None, title: str = "", publisher: str | None = None) -> str | None:
    """Excerpt as plain text, without feed boilerplate, capped; None if it adds nothing."""
    text = strip_html(value)
    if not text:
        return None
    for rx in _FEED_BOILERPLATE:
        text = rx.sub("", text).strip()
    # Aggregator descriptions often repeat the headline and the outlet only.
    rest = fold(text)
    for piece in (title, publisher or ""):
        p = fold(piece).strip()
        if p:
            rest = rest.replace(p, " ")
    if len(re.sub(r"[\W_]+", "", rest)) < 25:
        return None
    return truncate(text)


_IMG_SKIP = re.compile(r"(feedburner|/pixel|pixel\.|stats\.wordpress|/b\.gif|1x1|spacer|blank\.gif|"
                       r"gravatar\.com/avatar|doubleclick|/emoji/)", re.I)


def normalise_image_url(url: str | None) -> str | None:
    if not url:
        return None
    url = htmlmod.unescape(url.strip())
    if url.startswith("//"):
        url = "https:" + url
    if not url.lower().startswith(("http://", "https://")) or _IMG_SKIP.search(url):
        return None
    return url[:1500]


def first_image(html_fragment: str | None) -> str | None:
    """First meaningful <img src> in an HTML fragment (tracking pixels skipped)."""
    if not html_fragment or "<img" not in html_fragment.lower():
        return None
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_fragment, "html.parser")
    for img in soup.find_all("img"):
        if img.get("width") in ("1", "0") or img.get("height") in ("1", "0"):
            continue
        src = img.get("src") or img.get("data-src") or ""
        if not src and img.get("srcset"):
            src = img["srcset"].split(",")[0].strip().split(" ")[0]
        url = normalise_image_url(src)
        if url:
            return url
    return None


def normalise_title(title: str, publisher: str | None = None) -> str:
    """Key used for duplicate detection: folded, punctuation-free, publisher suffix removed."""
    t = clean_title(title, publisher)
    t = fold(t)
    t = re.sub(r"[^\w\s]", " ", t)
    return _WS.sub(" ", t).strip()[:600]


def normalise_language(lang: str | None) -> str | None:
    if not lang:
        return None
    code = lang.strip().replace("_", "-").split("-")[0].lower()
    return code[:5] or None


def _to_naive_utc(value: date | datetime | str | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        from dateutil import parser as dparser

        try:
            value = dparser.parse(value)
        except (ValueError, OverflowError):
            return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    return datetime(value.year, value.month, value.day)


# ---------------------------------------------------------------------------
# URL canonicalisation
# ---------------------------------------------------------------------------

_TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "gclsrc", "msclkid", "yclid", "igshid", "mc_cid", "mc_eid", "_ga", "_gl",
    "ocid", "cmpid", "cmp", "ito", "ref_src", "ref_url", "src_campaign", "sr_share", "smid", "smtyp",
    "at_medium", "at_campaign", "at_custom1", "at_custom2", "at_custom3", "at_custom4", "spm", "share",
    "rss", "feed", "wt.mc_id", "wt_mc_id", "mkt_tok", "vero_id", "trk", "trkcampaign", "s_cid",
    "outputtype", "amp", "amp_js_v", "usqp", "__twitter_impression", "guccounter", "guce_referrer",
    "guce_referrer_sig", "partner", "taid", "xtor",
}
_TRACKING_PREFIXES = ("utm_", "pk_", "mtm_", "hsa_", "oly_", "__hs", "_hs", "ga_")
_GOOGLE_NEWS_HOSTS = ("news.google.com", "news.google.it", "news.google.es", "news.google.de")


def _is_google_news(host: str) -> bool:
    return host.lower() in _GOOGLE_NEWS_HOSTS


def resolve_redirect(url: str) -> str:
    """Undo wrappers that carry the real article URL inside the link itself (no fetching):
    old Google News `.../url?url=REAL`, Google `google.com/url?q=REAL`, Google AMP viewer
    `google.com/amp/s/REAL` and the AMP cache `*.cdn.ampproject.org/c/s/REAL`."""
    parts = urlsplit(url)
    host = parts.netloc.lower()
    if host.endswith("google.com") or _is_google_news(host):
        if parts.path.endswith("/url"):
            q = dict(parse_qsl(parts.query))
            real = q.get("url") or q.get("q")
            if real and real.startswith(("http://", "https://")):
                return real
        m = re.match(r"^/amp/(s/)?(.+)$", parts.path)
        if m and host.endswith("google.com"):
            return ("https://" if m.group(1) else "http://") + m.group(2)
    if host.endswith(".cdn.ampproject.org"):
        m = re.match(r"^/(?:[a-z]+/)*?(?:c|v|i|wp)/(s/)?(.+)$", parts.path)
        if m:
            return ("https://" if m.group(1) else "http://") + m.group(2)
    return url


def google_news_real_url(link: str, description_html: str | None) -> str:
    """For a Google News item, return the publisher's URL when the feed gives it in the
    description (`<a href=...>`); otherwise keep the Google News link. Never fetches."""
    host = urlsplit(link).netloc.lower()
    if not _is_google_news(host):
        return link
    resolved = resolve_redirect(link)
    if resolved != link:
        return resolved
    if description_html:
        for href in re.findall(r"""<a\s[^>]*href=["']([^"']+)["']""", description_html, flags=re.I):
            href = htmlmod.unescape(href)
            h = urlsplit(href).netloc.lower()
            if href.startswith(("http://", "https://")) and h and not _is_google_news(h) and "google." not in h:
                return href
    return link


def clean_url(url: str) -> str:
    """The link the user clicks: wrappers resolved, tracking parameters, AMP variants and
    the fragment removed; scheme/host kept as published."""
    url = htmlmod.unescape((url or "").strip())
    if not url:
        return ""
    for _ in range(3):  # wrappers can be nested
        nxt = resolve_redirect(url)
        if nxt == url:
            break
        url = nxt
    parts = urlsplit(url)
    host = parts.netloc
    if host.lower().startswith("amp."):
        host = host[4:]
    path = parts.path or "/"
    # AMP path variants: /amp, /amp/, /amp.html, .amp, /amp/<path>
    path = re.sub(r"/amp(?:\.html?)?/?$", "/", path, flags=re.I)
    path = re.sub(r"\.amp(\.html?)?$", r"\1", path, flags=re.I)
    path = re.sub(r"^/amp/", "/", path, flags=re.I)
    query = []
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        kl = k.lower()
        if kl in _TRACKING_PARAMS or kl.startswith(_TRACKING_PREFIXES):
            continue
        if _is_google_news(host) and kl in ("oc", "hl", "gl", "ceid"):
            continue
        query.append((k, v))
    return urlunsplit((parts.scheme.lower() or "https", host.lower(), path, urlencode(query), ""))


def canonicalize_url(url: str) -> str:
    """Identity key for an article URL (stored in `canonical_url`, unique):
    clean_url() + https, no 'www.'/'m.' host prefix, sorted query, no trailing slash."""
    cleaned = clean_url(url)
    if not cleaned:
        return ""
    parts = urlsplit(cleaned)
    host = parts.netloc.lower()
    if host.endswith(":80") or host.endswith(":443"):
        host = host.rsplit(":", 1)[0]
    for prefix in ("www.", "m.", "mobile."):
        if host.startswith(prefix) and host.count(".") >= 2:
            host = host[len(prefix):]
    path = unquote(parts.path) or "/"
    path = re.sub(r"/{2,}", "/", path)
    if len(path) > 1:
        path = path.rstrip("/")
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit(("https", host, path, query, ""))[:1500]


# ---------------------------------------------------------------------------
# Honey gate, topics, countries
# ---------------------------------------------------------------------------


def _words(patterns: list[str]) -> re.Pattern:
    """Alternation of folded regex fragments, matched on word boundaries."""
    return re.compile(r"(?<!\w)(?:" + "|".join(patterns) + r")(?!\w)")


def _fwords(patterns: list[str]) -> re.Pattern:
    """Like `_words`, with each fragment folded like the text it is matched on, so Cyrillic
    stems can be written naturally (й -> и, ї -> і, ё -> е). Fragments must not use
    upper-case escapes (\\W, \\S, \\D, \\B), which folding would lower-case."""
    return _words([fold(p) for p in patterns])


def _raw(patterns: list[str]) -> re.Pattern | None:
    return re.compile("|".join(patterns)) if patterns else None


def _unfolded(patterns: list[str]) -> re.Pattern | None:
    """Case-insensitive word match on the original (accented) text. For short English words
    whose folded form is also a word in another language (Vietnamese "bán" -> "ban")."""
    return re.compile(r"(?<!\w)(?:" + "|".join(patterns) + r")(?!\w)", re.I) if patterns else None


# Phrases that contain honey words but are not about honey (removed before the gate).
_GATE_EXCLUSIONS = _words([
    r"yo yo honey singh", r"honey singh", r"honey badgers?", r"honey ?traps?", r"honey boo boo",
    r"honey bunch(?:es)?(?: of oats)?", r"honey nut(?: cheerios)?", r"honey irani", r"honey rose",
    r"honey bunny", r"honey blonde", r"honey locusts?", r"honey crisp", r"honey ?pots?", r"honey ?moon\w*",
    r"(?:land of )?milk (?:and|&) honey", r"honey,? i shrunk", r"american honey (?:queen|movie|film)",
    r"mel gibson", r"mel b", r"mel brooks", r"mel tucker", r"mel robbins",
    r"royal honey", r"honey packets? (?:with|containing) (?:sildenafil|tadalafil)",
    # Miele the appliance maker, PayPal's "Honey" browser extension, Spanish/French honeymoon
    # (noise sources named in docs/research/news.json)
    r"miele (?:spa|group|gruppe|& cie|elettrodomestici)", r"paypal(?:'s)? honey",
    r"honey (?:browser |shopping |coupon |chrome )?extension", r"honey coupons?", r"(?:luna|lune) de miel",
])
# Item-level vetoes: male-enhancement "honey" sachets with hidden drugs (FDA warnings). Removing
# the phrase is not enough because the item still says "honey" elsewhere.
_GATE_VETO = _words([r"sildenafil", r"tadalafil", r"male enhancement", r"(?:sexual|libido) enhanc\w*",
                     r"vip honey", r"royal honey"])
# An item whose only honey word is "miele" and that talks about appliances is about Miele the brand.
_APPLIANCE = _words([r"lavatric\w*", r"lavastovigl\w*", r"elettrodomestic\w*", r"asciugatric\w*",
                     r"aspirapolver\w*", r"dishwashers?", r"washing machines?", r"dryers?", r"appliances?",
                     r"vacuum cleaners?", r"waschmaschin\w*", r"geschirrspul\w*", r"hausgerat\w*", r"gutersloh"])
# Ukrainian/Russian "мед." / "мед-" is the abbreviation of "medical" (медичний / медицинский), not
# honey. Matched on the original text: only an abbreviation is followed by a lower-case word.
_MED_ABBR = re.compile(r"(?<!\w)[Мм]ед(?:\.(?=\s*[а-яіїєґё])|-(?=\w))")

# Strong terms: any one is enough to pass the gate.
_GATE_STRONG = _words([
    r"honey(?:s|bees?|comb\w*)?", r"miele", r"mieli", r"miel(?:es)?", r"honig\w*", r"apicolt\w*", r"apicult\w*",
    r"apicolas?", r"apiculteurs?", r"beekeep\w*", r"bee[- ]keep\w*", r"apiar\w*", r"alveari?", r"alveare",
    r"colmenas?", r"mielato", r"melata", r"manuka", r"varroa\w*", r"imker\w*", r"bienenvolk\w*",
    r"bienenvolker\w*", r"ruches?", r"bee colon\w*", r"colonie di api", r"colonias de abejas",
    r"colony collapse", r"royal jelly", r"pappa reale", r"jalea real", r"propoli\w*",
    r"(?:hs|nc|cn|code|codice|partida|heading|voce|subheading)[\s.]*(?:code[\s.]*)?0409\w*",
])
# Non-Latin scripts / languages without spaces (GDELT queries in ZH, UK, RU, VI, SR).
# CJK has no word boundaries, so these are matched as plain substrings.
_GATE_STRONG_RAW = re.compile(
    # Chinese (simplified + traditional): honey, beekeeping, beekeepers, honeybee, bee products,
    # bee industry; explicit variety honeys only (no generic "..蜜": 闺蜜/甜蜜/蜜月 are not honey)
    r"蜂蜜|养蜂|養蜂|蜂农|蜂農|蜜蜂|蜂产品|蜂產品|蜂业|蜂業|"
    r"(?:洋槐|槐花|椴树|椴樹|荆条|荊條|枣花|棗花|百花|油菜|紫云英|荔枝|龙眼|龍眼|葵花)蜜|"
    # Ukrainian/Russian/Serbian Cyrillic (folded: ё -> е): honey, bee(s), beekeeper(s), apiary
    # (not медов*: "медовий місяць" is a honeymoon)
    r"(?<!\w)(?:мед|меду|меда|медом|бджіл\w*|бджол\w*|пасічн\w*|пасік\w*|пчел\w*|пасек\w*|пасеч\w*)(?!\w)|"
    r"(?<!\w)(?:mat ong|nuoi ong)(?!\w)|"                 # Vietnamese (accents folded): honey, beekeeping
    r"(?<!\w)(?:pcel\w*|izvoz meda|meda)(?!\w)"          # Serbian/Croatian (folded): bee*, honey export
)
# Portuguese "mel" is a name elsewhere (Mel Gibson): bare "mel" only in Portuguese items,
# otherwise only in unmistakable Portuguese phrases.
_GATE_MEL_PT = _words([r"mel"])
_GATE_MEL_PHRASES = _words([r"(?:de|do|o|no|ao|com) mel", r"mel (?:de abelhas?|brasileiro|organico|natural|puro)"])
# Weak terms: pass only together with a bee word.
_GATE_WEAK = _words([r"pollinat\w*", r"impollinat\w*", r"poliniza\w*", r"bestaub\w*", r"hives?",
                     r"colon(?:y|ies)", r"swarms?", r"sciam\w*", r"enjambres?", r"overwinter\w*"])
_BEE_CONTEXT = _words([r"bees?", r"api", r"ape", r"abejas?", r"abelhas?", r"bienen?", r"abeilles?",
                       r"bumble ?bees?"])


def honey_terms(text: str, language: str | None = None) -> list[str]:
    """Honey/beekeeping terms found in `text` (folded matching). Empty list = not about honey."""
    t = fold(_MED_ABBR.sub(" ", unicodedata.normalize("NFC", text or "")))
    if _GATE_VETO.search(t):
        return []
    t = _GATE_EXCLUSIONS.sub(" ", t)
    found = [m.group(0) for m in _GATE_STRONG.finditer(t)]
    found += [m.group(0) for m in _GATE_STRONG_RAW.finditer(t)]
    mel = _GATE_MEL_PT if (language or "").startswith("pt") else _GATE_MEL_PHRASES
    found += [m.group(0) for m in mel.finditer(t)]
    if found and all(f == "miele" for f in found) and _APPLIANCE.search(t):
        return []  # Miele (the appliance maker), not miele (honey)
    if not found:
        weak = [m.group(0) for m in _GATE_WEAK.finditer(t)]
        bees = [m.group(0) for m in _BEE_CONTEXT.finditer(t)]
        if weak and bees:
            found = weak + bees
    return found


def is_honey_related(title: str, snippet: str | None = None, language: str | None = None) -> bool:
    return bool(honey_terms(f"{title} \n {snippet or ''}", language))


TOPICS: dict[str, dict] = {
    "prices": {
        "it": "Prezzi", "en": "Prices", "weight": 30,
        "words": [r"prices?", r"pric(?:ing|ed)", r"price war", r"prezz[oi]", r"quotazion[ei]", r"listin[oi]",
                  r"precios?", r"cotizac\w*", r"cotizan?", r"precos?", r"cotac\w*", r"preis(?:e|en)?",
                  r"preisentwicklung", r"honigpreis\w*", r"cheap\w*", r"underpric\w*", r"sottocosto",
                  r"rincar\w*", r"aument\w* (?:dei|del|de los|del) prezz\w*", r"price (?:drop|fall|rise|increase)s?",
                  r"cents? (?:a|per) pound", r"valor(?:es)? (?:de|por) (?:la )?(?:miel|tonelada|kilo)",
                  # Ukrainian / Russian / Serbian (Cyrillic + Latin) / Vietnamese
                  r"цін[аиуіо]\w*", r"цен[аыуеоя]\w*", r"подорожча\w*", r"подорожа\w*", r"подешев\w*",
                  r"cen[aeiu] med[au]", r"otkupn\w* cen\w*", r"gia (?:ban |xuat khau )?mat ong"],
        "raw": [(r"\d\s*(?:€|eur|euros?|usd|us\$|\$|dollars?|dolares|cents?|centavos|pesos|reais|r\$)?\s*"
                 r"(?:/|per|al|el|por|pro|a)\s*(?:kg|kilo\w*|chilo\w*|lbs?|libbr\w*|libras?|pound|tonn?e?s?\b|"
                 r"tonnellat\w*|tonelad\w*)"),
                r"价|價|跌|涨|漲"],   # Chinese: price, fall, rise (no word boundaries in CJK)
    },
    "production": {
        "it": "Produzione e raccolto", "en": "Production & harvest", "weight": 20,
        "words": [r"production", r"produc(?:e|ed|es|ing)", r"output", r"harvests?", r"harvesting", r"crops?",
                  r"yields?", r"produzion[ei]", r"produttiv\w*", r"raccolt[oai]", r"rese", r"resa",
                  r"produccion", r"producida", r"cosechas?", r"zafra", r"rendimientos?", r"producao",
                  r"colheitas?", r"safra", r"ernte\w*", r"produktion", r"honigernte", r"forecasts?", r"outlook",
                  r"previsioni", r"stime", r"stima", r"estimac\w*", r"estimates?",
                  r"врожа\w*", r"урожа\w*", r"виробництв\w*", r"производств\w*", r"proizvodnj\w*",
                  r"производњ\w*"],
        "raw": [r"产量|產量|减产|減產|增产|增產"],
    },
    "trade": {
        "it": "Commercio, export e import", "en": "Trade, exports & imports", "weight": 24,
        "words": [r"exports?", r"export(?:ed|ing|ers?)", r"imports?", r"import(?:ed|ing|ers?)", r"trade",
                  r"trading", r"traders?", r"shipments?", r"shipping", r"containers?", r"esportazion[ei]",
                  r"esportator[ei]", r"esportat[oaie]", r"importazion[ei]", r"importator[ei]", r"importat[oaie]",
                  r"commerc(?:io|iale|iali)", r"interscambio", r"exportac\w*", r"exportador\w*", r"exportan?",
                  r"importac\w*", r"importador\w*", r"comercio exterior", r"comercio",
                  r"embarques?", r"ausfuhr\w*", r"einfuhr\w*", r"aussenhandel", r"bulk", r"customs",
                  r"dogan\w*", r"aduan\w*", r"fob", r"cif", r"trade data", r"balanza comercial",
                  r"експорт\w*", r"экспорт\w*", r"імпорт\w*", r"импорт\w*", r"митн\w*", r"таможен\w*",
                  r"извоз\w*", r"увоз\w*", r"izvoz\w*", r"uvoz\w*", r"xuat khau", r"nhap khau"],
        "raw": [r"出口|进口|進口|贸易|貿易"],
    },
    "adulteration": {
        "it": "Adulterazioni e frodi", "en": "Adulteration & fraud", "weight": 22,
        "words": [r"adulter\w*", r"fraud\w*", r"frode", r"frodi", r"fraude\w*", r"fake honey", r"fake",
                  r"miele falso", r"falso miele", r"miel falsa", r"miel adulterada", r"falsificat\w*",
                  r"falsifica\w*", r"contraffa\w*", r"sofisticaz\w*", r"sofisticat\w*", r"syrups?", r"sciropp\w*",
                  r"jarabes?", r"xaropes?", r"sirup", r"authentic\w*", r"inauthentic\w*", r"autentic\w*",
                  r"mislabel\w*", r"nmr", r"irms", r"c4 sugars?", r"exogenous sugars?",
                  r"zuccheri (?:esogeni|aggiunti)", r"from the hives", r"honey laundering", r"transshipp\w*",
                  r"circumvent\w*", r"triangulat\w*", r"verfalsch\w*", r"gepanscht\w*", r"pansch\w*",
                  r"фальсиф\w*", r"підроб\w*", r"поддел\w*", r"falsifik\w*"],
        "raw": [r"掺假|摻假|造假|假蜂蜜"],
    },
    "quality": {
        "it": "Qualità e sicurezza alimentare", "en": "Quality & food safety", "weight": 10,
        "words": [r"food safety", r"sicurezza alimentare", r"seguridad alimentaria", r"inocuidad",
                  r"lebensmittelsicherheit", r"residues?", r"residu[oi]", r"residuos?", r"ruckstand\w*",
                  r"contamin\w*", r"recalls?", r"recalled", r"richiam[oi]", r"ritir[oa] dal mercato",
                  r"glyphosate", r"glifosat\w*", r"glyphosat", r"antibiotic\w*", r"antibiotici", r"pesticid\w*",
                  r"mrls?", r"lmr", r"rasff", r"hmf", r"botulism\w*", r"pyrrolizidine\w*", r"pirrolizidin\w*",
                  r"heavy metals?", r"metalli pesanti", r"quality (?:control|standards?|testing|checks?)",
                  r"controll[oi] (?:di )?qualita", r"control de calidad", r"food standards?", r"fda", r"efsa",
                  r"cfia", r"senasa", r"lab(?:oratory)? tests?", r"testing"],
    },
    "policy": {
        "it": "Politiche e normativa", "en": "Policy & regulation", "weight": 20,
        "words": [r"regulations?", r"regulator\w*", r"regolament[oi]", r"normativ[ae]", r"reglament\w*",
                  r"normativas?", r"verordnung\w*", r"directives?", r"direttiva", r"directiva", r"richtlinie",
                  r"breakfast directive", r"direttiva colazione", r"labell?ing", r"labels?", r"etichett\w*",
                  r"etiquetado", r"etiquetas?", r"rotulagem", r"kennzeichnung\w*", r"legislat\w*", r"legge",
                  r"leggi", r"decret[oi]", r"decrees?", r"ley", r"leyes", r"laws?", r"bills?", r"ministr\w*",
                  r"government", r"governo", r"gobierno", r"bundesregierung", r"european commission",
                  r"commissione europea", r"comision europea", r"eu-kommission", r"european parliament",
                  r"parlamento europeo", r"subsid\w*", r"sussid\w*", r"aiuti", r"ayudas?", r"incentiv\w*",
                  r"farm bill", r"codex", r"senate", r"senato", r"congress", r"congreso", r"policy", r"policies",
                  r"politica agricola", r"origin labell?ing", r"country of origin", r"paese d'origine",
                  r"pais de origen", r"herkunftsangabe\w*", r"standard of identity"],
    },
    "tariffs": {
        "it": "Dazi e antidumping", "en": "Tariffs & anti-dumping", "weight": 26,
        "words": [r"tariffs?", r"dazi", r"dazio", r"aranceles?", r"arancelari\w*", r"tarifas?", r"zoll\w*",
                  r"zolle", r"anti-?dumping", r"dumping", r"countervailing", r"duties", r"import dut(?:y|ies)",
                  r"customs dut(?:y|ies)", r"section 301", r"section 232", r"trade war", r"guerra commerciale",
                  r"guerra comercial", r"handelskrieg", r"retaliat\w*", r"ritorsion\w*", r"represalias?",
                  r"derechos de importacion", r"diritti doganali", r"derechos de exportacion", r"retenciones",
                  r"мит[оа]\w*", r"пошлин\w*", r"антидемпінг\w*", r"антидемпинг\w*", r"антидампинг\w*",
                  r"antidamping\w*", r"carinsk\w*", r"chong ban pha gia"],
        "raw": [r"反倾销|反傾銷|关税|關稅"],
    },
    "import_restrictions": {
        "it": "Restrizioni all'import", "en": "Import restrictions", "weight": 22,
        # bare "ban(s)" is matched on the unfolded text: folded Vietnamese "bán" (sell) / "Bản" is "ban"
        "unfolded": [r"bans?"],
        "words": [r"import bans?", r"bans? on (?:honey )?imports?", r"banned", r"embargo\w*",
                  r"quotas?", r"contingent[ei]", r"cuotas?", r"cupos?", r"kontingent\w*", r"import alerts?",
                  r"border rejections?", r"rejected at the border", r"respint[oai]", r"respingiment\w*",
                  r"rechaz\w*", r"detention\w*", r"detained", r"seized", r"seizures?", r"sequestr\w*",
                  r"incautac\w*", r"decomis\w*", r"suspend\w* (?:of )?imports?", r"blocco delle importazioni",
                  r"stop alle importazioni", r"import restrictions?", r"restrizion[ei]", r"restriccion\w*",
                  r"safeguards?", r"salvaguardi\w*", r"trq", r"tariff[- ]rate quotas?", r"import licen[cs]\w*",
                  r"barreras? sanitarias?", r"sanitary barriers?", r"einfuhrverbot\w*", r"importverbot\w*",
                  r"квот\w*", r"заборон\w*", r"запрет\w*", r"забран\w*", r"zabran\w*"],
        "raw": [r"禁止进口|禁止進口|进口禁令|進口禁令"],
    },
    "companies": {
        "it": "Aziende e fornitori", "en": "Companies & suppliers", "weight": 8,
        "words": [r"compan(?:y|ies)", r"aziend[ae]", r"impres[ae]", r"empresas?", r"unternehmen", r"firms?",
                  r"corporat\w*", r"cooperativ[ae]s?", r"cooperatives?", r"packers?", r"packing", r"confezion\w*",
                  r"invasat\w*", r"envasador\w*", r"fraccionador\w*", r"abfuller\w*", r"suppliers?",
                  r"fornitor[ei]", r"proveedor\w*", r"exporters?", r"importers?", r"acquisitions?",
                  r"acquires?", r"acquired", r"acquisizion\w*", r"mergers?", r"fusion\w*", r"bankrupt\w*",
                  r"fallimento", r"quiebra", r"insolven\w*", r"revenues?", r"fatturato", r"facturac\w*",
                  r"umsatz", r"conapi", r"mielizia", r"ambrosoli", r"rigoni", r"langnese", r"breitsamer",
                  r"sioux honey", r"sue bee", r"dutch gold", r"comvita", r"capilano", r"hilltop honey",
                  r"golden acres", r"wedderspoon", r"dabur", r"patanjali", r"honey packers"],
    },
    "colony_health": {
        "it": "Apicoltura e salute degli alveari", "en": "Beekeeping & colony health", "weight": 4,
        "words": [r"varroa\w*", r"colony (?:loss|losses|collapse)\w*",
                  r"bee (?:deaths?|losses|die-?offs?|mortality|health|decline)",
                  r"(?:hive|colony) (?:losses|deaths|mortality)", r"perdit[ae] (?:di )?(?:alveari|colonie|api)",
                  r"mori[ae] (?:delle |di )?api", r"moria", r"spopolament\w*", r"mortalita", r"mortalidad",
                  r"mortandad", r"bienensterben", r"neonicotinoid\w*", r"vespa velutina", r"asian hornets?",
                  r"calabrone asiatico", r"vespa orientalis", r"small hive beetle", r"aethina", r"nosema\w*",
                  r"foulbrood", r"peste americana", r"loque", r"winter losses", r"svernament\w*", r"invernada",
                  r"colonies", r"colonie", r"colonias", r"alveari", r"colmenas", r"bienenvolk\w*",
                  r"bienenvolker\w*", r"beekeeping", r"apicoltura", r"apicultura", r"imkerei", r"pollinat\w*",
                  r"impollinat\w*", r"poliniza\w*"],
    },
    "weather": {
        "it": "Meteo e clima", "en": "Weather & climate", "weight": 6,
        "words": [r"droughts?", r"siccita", r"sequias?", r"secas?", r"durre", r"trockenheit", r"frosts?",
                  r"gelat[ae]", r"gelo", r"heladas?", r"geadas?", r"rains?", r"rainfall", r"piogg\w*", r"lluvias?",
                  r"chuvas?", r"regen", r"floods?", r"flooding", r"alluvion\w*", r"inondaz\w*", r"inundac\w*",
                  r"enchentes?", r"hochwasser", r"heat ?waves?", r"ondat[ae] di calore", r"olas? de calor",
                  r"hitzewelle", r"extreme heat", r"caldo", r"calor", r"hitze", r"climat\w*", r"clima",
                  r"el nino", r"la nina", r"wildfires?", r"incendi\w*", r"weather", r"meteo\w*", r"temperatur\w*",
                  r"storms?", r"grandin\w*", r"granizo", r"hailstorms?", r"maltempo"],
    },
}
_TOPIC_RX = {k: (_fwords(v["words"]), _raw(v.get("raw", [])), _unfolded(v.get("unfolded", [])))
             for k, v in TOPICS.items()}

# Signals of low relevance for a bulk importer.
_PENALTIES: dict[str, tuple[re.Pattern, int]] = {
    "recipe": (_words([r"recipes?", r"ricett[ae]", r"recetas?", r"receitas?", r"rezept\w*", r"how to make",
                       r"cocktails?", r"desserts?", r"glazed?", r"marinad\w*", r"dressings?", r"baking", r"bake[ds]?",
                       r"tablespoons?", r"teaspoons?", r"cucchia\w*", r"cucharad\w*", r"cooking", r"cucina",
                       r"cocina", r"salads?", r"cakes?", r"torta", r"biscott\w*", r"cookies?", r"chicken", r"pollo",
                       r"salmon", r"hot honey", r"pancakes?", r"smoothies?", r"tea recipe"]), 35),
    "health": (_words([r"health benefits?", r"benefits of honey", r"benefici (?:del miele|per la salute)",
                       r"beneficios (?:de la miel|para la salud)",
                       r"proprieta (?:benefiche|del miele|curative|nutrizionali)",
                       r"propiedades (?:de la miel|medicinales|curativas|nutricionales)", r"rimedi\w*",
                       r"remed(?:y|ies|io|ios)", r"cough\w*", r"tosse",
                       r"tos", r"sore throat", r"mal di gola", r"skin ?care", r"skin", r"pelle", r"piel",
                       r"face masks?", r"weight loss", r"dimagr\w*", r"adelgaz\w*", r"sleep", r"sonno", r"immun\w*",
                       r"wellness", r"benessere", r"diet", r"dieta", r"superfoods?", r"antioxidants?",
                       r"antiossidant\w*", r"hangover", r"wounds?", r"ferite", r"heridas", r"beauty", r"bellezza",
                       r"belleza", r"cosmetic\w*", r"nutritionists?", r"doctors? (?:say|explain)", r"medic[oi]"]), 30),
    "local": (_words([r"backyard", r"hobby\w*", r"schools?", r"students?", r"kids", r"children", r"bambini",
                      r"ninos", r"scuol[ae]", r"escuelas?", r"festivals?", r"sagra", r"county fair", r"state fair",
                      r"museums?", r"museo", r"swarm removal", r"rooftops?", r"gardens?", r"gardening",
                      r"giardin\w*", r"jardin\w*", r"bee-friendly", r"open day", r"workshops?",
                      r"corso di apicoltura", r"beginners?", r"principianti", r"community gardens?", r"volunteers?",
                      r"volontari", r"church", r"gifts?", r"weddings?", r"matrimonio", r"celebrity", r"influencer"]), 18),
}

_BULK = _words([r"bulk", r"sfuso", r"all'ingrosso", r"ingrosso", r"wholesale", r"a granel", r"granel",
                r"drums?", r"fusti", r"tambores?", r"containers?", r"metric tons?", r"tonnes?", r"tons?",
                r"tonnellat[ae]", r"toneladas?", r"tonnen", r"packers?", r"importers?", r"exporters?",
                r"importator[ei]", r"esportator[ei]", r"exportador(?:es)?", r"importador(?:es)?", r"fob", r"cif",
                r"cfr", r"trade data", r"customs data", r"per (?:kg|kilo|pound|lb)", r"al (?:kg|chilo)",
                r"por kilo", r"el kilo", r"тонн\w*", r"тон"])
_BULK_RAW = re.compile(r"吨|噸")   # Chinese: tonne(s)
_EU_FOLDED = _fwords([r"european union", r"unione europea", r"union europea", r"uniao europeia",
                      r"europaische union", r"european commission", r"commissione europea", r"comision europea",
                      r"eu-kommission", r"european parliament", r"parlamento europeo", r"brussels", r"bruxelles",
                      r"bruselas", r"breakfast directive", r"direttiva colazione",
                      r"євросоюз\w*", r"евросоюз\w*", r"європейськ\w* союз\w*", r"европейск\w* союз\w*",
                      r"evropsk\w* unij\w*", r"европск\w* униј\w*"])
_EU_CASED = re.compile(r"(?<![\w-])(?:EU|UE|ЄС|ЕС|ЕУ)(?![\w])")   # + Ukrainian/Russian/Serbian abbreviations
_EU_RAW = re.compile(r"欧盟|歐盟")

# Extra multilingual country forms (folded); COUNTRY_KEYWORDS (shared reference) is merged in.
_EXTRA_COUNTRY_KEYWORDS: dict[str, list[str]] = {
    "ARG": ["argentinas", "argentinos", "argentini", "argentinien", "argentinischer", "argentinischen"],
    "BRA": ["brasileiro", "brasileira", "brasileiros", "brasileno", "brasilena", "brasiliano", "brasiliani",
            "brasilien"],
    "URY": ["uruguayo", "uruguaya", "uruguayos"],
    "CHL": ["chilena", "chilenos"],
    "CHN": ["cinesi", "chino", "chinos", "chinesisch", "chinesische", "chinesischen", "chinesischer", "chinas"],
    "UKR": ["ucraini", "ucraina", "ucrania", "ucraniano", "ucraniana", "ukrainische", "ukrainischen",
            "ukrainischer"],
    "VNM": ["vietnamita", "vietnamiti", "vietnamesischen", "vietnamesischer"],
    "IND": ["indien", "indische", "indischen", "indischer"],
    "MEX": ["mexicano", "mexicana", "mexicanos", "messicano", "messicana", "mexiko"],
    "USA": ["estados unidos", "ee.uu.", "ee. uu.", "eeuu", "eua", "statunitense", "statunitensi", "u.s.a.",
            "vereinigte staaten", "american honey producers", "us-amerikanisch", "us-amerikanische",
            "us-amerikanischen"],
    "DEU": ["tedesco", "tedesca", "tedeschi", "tedesche", "alemania", "aleman", "alemana", "alemanha"],
    "ESP": ["spagnola", "spagnoli", "espanol", "espanola", "espanoles", "spanien"],
    "HUN": ["ungherese", "ungheresi", "hungria", "ungarn"],
    "ROU": ["rumena", "rumeni", "rumania", "rumano", "rumanien", "romeno", "romena"],
    "SRB": ["serba", "serbi", "serbien"],
    "TUR": ["turca", "turchi", "turquia", "turkei"],
    "ITA": ["italiani", "italiane", "italien"],
    "POL": ["polacco", "polacca", "polen"],
    "NZL": ["neuseeland", "nueva zelanda"],
    "CAN": ["canadesi", "kanada"],
    "AUS": ["australiani", "australien"],
    "FRA": ["francese", "francesi", "frankreich"],
}
# Native-script stems (Ukrainian / Russian / Serbian Cyrillic and Serbian Latin) for the
# origins and markets that matter, as regex fragments. Folded at compile time like the text
# (й -> и, ї -> і, ё -> е) and matched on word boundaries (Python's \w is Unicode).
_COUNTRY_STEMS: dict[str, list[str]] = {
    "UKR": [r"україн\w*", r"украин\w*", r"украјин\w*", r"ukrajin\w*"],
    "CHN": [r"кита[йїюяєе]\w*"],
    "USA": [r"сша", r"сполучен\w* штат\w*", r"соединенн\w* штат\w*"],   # not Serbian "САД": "сад" = garden
    "ARG": [r"аргентин\w*"],
    "BRA": [r"бразил\w*"],
    "VNM": [r"в['\u02bc]?єтнам\w*", r"вьетнам\w*", r"вијетнам\w*", r"vijetnam\w*"],
    "IND": [r"інді[яїює]\w*", r"індійськ\w*", r"инди[яию]", r"индией", r"индийск\w*"],
    "RUS": [r"росі[яїює]\w*", r"російськ\w*", r"росси\w*", r"рф", r"русиј\w*", r"rusij\w*"],
    "SRB": [r"србиј\w*", r"српск\w*", r"сербі\w*", r"серби\w*", r"сербск\w*", r"srbij\w*", r"srpsk\w*"],
    "DEU": [r"німеччин\w*", r"німецьк\w*", r"германи\w*", r"немецк\w*", r"немачк\w*", r"nemačk\w*"],
    "ITA": [r"італі\w*", r"итали\w*", r"итальянск\w*", r"италиј\w*", r"italij\w*"],
    "POL": [r"польщ\w*", r"польш\w*", r"польськ\w*", r"польск\w*"],
    "TUR": [r"туреччин\w*", r"турецьк\w*", r"турци\w*", r"турецк\w*", r"турск\w*", r"tursk\w*"],
    "HUN": [r"угорщин\w*", r"угорськ\w*", r"венгри\w*", r"венгерск\w*", r"мађарск\w*", r"mađarsk\w*",
            r"madjarsk\w*"],
    "ROU": [r"румуні\w*", r"румунськ\w*", r"румыни\w*", r"румынск\w*"],
    "MEX": [r"мексик\w*"],
}
# Chinese country names (simplified + traditional). CJK has no word boundaries: plain substrings.
_CJK_COUNTRIES: dict[str, str] = {
    "CHN": r"中国|中國|我国",          # 我国 "our country" = China in PRC press
    "USA": r"美国|美國",
    "UKR": r"乌克兰|烏克蘭",
    "ARG": r"阿根廷",
    "BRA": r"巴西",
    "VNM": r"越南",
    "IND": r"印度(?!尼西亚|尼西亞|洋)",   # not Indonesia / the Indian Ocean
    "URY": r"乌拉圭|烏拉圭",
    "MEX": r"墨西哥",
    "TUR": r"土耳其",
    "HUN": r"匈牙利",
    "ROU": r"罗马尼亚|羅馬尼亞",
    "SRB": r"塞尔维亚|塞爾維亞",
    "RUS": r"俄罗斯|俄羅斯",
    "DEU": r"德国|德國",
    "ITA": r"意大利|義大利",
    "ESP": r"西班牙",
    "FRA": r"法国|法國",
    "POL": r"波兰|波蘭",
    "NZL": r"新西兰|新西蘭|紐西蘭",
    "CAN": r"加拿大",
    "AUS": r"澳大利亚|澳大利亞|澳洲",
    "THA": r"泰国|泰國",
}
# Keywords that are also ordinary words: only counted when capitalised in the original text.
_CASE_SENSITIVE = {"turkey": "Turkey", "chile": "Chile", "polish": "Polish"}
# Phrases removed before country matching (food, US states, idioms).
_COUNTRY_EXCLUSIONS = _words([
    r"new mexico", r"french (?:toast|fries|dressing|press)", r"greek yog(?:h)?urts?", r"yogurt greco",
    r"(?:honey[- ]?)?(?:glazed|roast(?:ed)?|smoked|ground|thanksgiving) turkey",
    r"turkey (?:breast|sandwich\w*|recipe\w*|dinner|meatballs?|burgers?)",
    r"chile (?:peppers?|powder|flakes|lime|de arbol|relleno)", r"honey chile", r"indian summer", r"india pale ale",
    r"german chocolate", r"chinese (?:new year|five spice)",
    # continental qualifiers: "South/Latin American honey" is not the United States
    r"(?:south|latin|central|pan)[- ]american honey",
    # another country's FDA: only "fda" is removed, so the qualifier still tags its own country
    r"(?:" + "|".join(f"(?<={w}{s} )" for w in (
        "philippine", "philippines", "thai", "thailand", "taiwan", "taiwanese", "ghana", "ghanaian",
        "indonesian", "nigerian", "egyptian", "saudi", "korean", "jordan", "china", "chinese")
        for s in ("", "'s", "'")) + r")fda",
])
_COUNTRY_EXCLUSIONS_CI = re.compile(_COUNTRY_EXCLUSIONS.pattern, re.I)
_US_CASED = [
    re.compile(r"(?<![\w.])USA(?![\w])"),
    re.compile(r"(?<![\w.])U\.S\.(?:A\.)?"),
    re.compile(r"(?<=[a-zà-ù] )Usa(?![\w])"),           # Italian press: "dazi Usa", "negli Usa"
    re.compile(r"(?<![\w])Usa(?=-[A-Z])|(?<=[A-Za-z]-)Usa(?![\w])"),
]
_US_CAPS = re.compile(r"(?<![\w.$])US(?![\w$])")  # not "US$" (a currency, common in Argentine prices)


def _compile_countries() -> dict[str, re.Pattern]:
    out: dict[str, re.Pattern] = {}
    keys = set(COUNTRY_KEYWORDS) | set(_EXTRA_COUNTRY_KEYWORDS) | set(_COUNTRY_STEMS)
    for iso3 in keys:
        words = {fold(w) for w in COUNTRY_KEYWORDS.get(iso3, []) + _EXTRA_COUNTRY_KEYWORDS.get(iso3, [])}
        words -= set(_CASE_SENSITIVE)
        parts = [re.escape(w) for w in sorted(words, key=len, reverse=True)]
        parts += [fold(p) for p in _COUNTRY_STEMS.get(iso3, [])]
        if parts:
            out[iso3] = re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)")
    return out


_COUNTRY_RX = _compile_countries()
_CJK_COUNTRY_RX = {iso3: re.compile(p) for iso3, p in _CJK_COUNTRIES.items()}
_CASE_SENSITIVE_OWNER = {
    kw: iso3 for iso3, kws in COUNTRY_KEYWORDS.items() for kw in kws if kw in _CASE_SENSITIVE
}


def tag_countries(text: str) -> list[str]:
    """ISO3 codes mentioned in `text` (title + excerpt), in order of first mention."""
    if not text:
        return []
    folded = _COUNTRY_EXCLUSIONS.sub(" ", fold(text))
    hits: dict[str, int] = {}
    for iso3, rx in _COUNTRY_RX.items():
        m = rx.search(folded)
        if m:
            hits[iso3] = m.start()
    for iso3, rx in _CJK_COUNTRY_RX.items():
        m = rx.search(folded)
        if m and (iso3 not in hits or m.start() < hits[iso3]):
            hits[iso3] = m.start()
    cleaned_original = _COUNTRY_EXCLUSIONS_CI.sub(" ", unicodedata.normalize("NFC", text))
    for kw, cased in _CASE_SENSITIVE.items():
        iso3 = _CASE_SENSITIVE_OWNER.get(kw)
        if not iso3 or iso3 in hits:
            continue
        m = re.search(r"(?<!\w)" + re.escape(cased) + r"(?!\w)", cleaned_original)
        if m:
            hits[iso3] = len(folded) + m.start()
    if "USA" not in hits:
        for rx in _US_CASED:
            m = rx.search(text)
            if m:
                hits["USA"] = m.start()
                break
        else:
            # "US" in capitals, unless the whole text is shouting (e.g. "LET US")
            if any(c.islower() for c in text):
                m = _US_CAPS.search(text)
                if m:
                    hits["USA"] = m.start()
    return [k for k, _ in sorted(hits.items(), key=lambda kv: kv[1])]


def tag_topics(title: str, snippet: str | None = None) -> dict[str, float]:
    """Topic key -> strength (1.0 when found in the headline, 0.6 when only in the excerpt)."""
    t_title, t_snip = fold(title or ""), fold(snippet or "")
    u_title, u_snip = unicodedata.normalize("NFC", title or ""), unicodedata.normalize("NFC", snippet or "")
    out: dict[str, float] = {}
    for key, rx in _TOPIC_RX.items():
        if _topic_found(rx, t_title, u_title):
            out[key] = 1.0
        elif _topic_found(rx, t_snip, u_snip):
            out[key] = 0.6
    return out


def _topic_found(rx: tuple, folded: str, original: str) -> bool:
    words, raw, unfolded = rx
    return bool(words.search(folded) or (raw is not None and raw.search(folded))
                or (unfolded is not None and unfolded.search(original)))


# ---------------------------------------------------------------------------
# Relevance
# ---------------------------------------------------------------------------

BASE_SCORE = 20
HONEY_IN_TITLE_BONUS = 8
TOPIC_CAP = 60
SOURCE_BONUS = {"official": 5, "industry": 4, "trade_press": 2}


@dataclass
class Analysis:
    honey_terms: list[str]
    countries: list[str]
    topics: list[str]
    score: int
    reason: str
    factors: dict = field(default_factory=dict)

    @property
    def is_honey(self) -> bool:
        return bool(self.honey_terms)


def analyse(title: str, snippet: str | None = None, *, language: str | None = None,
            reliability: str | None = None) -> Analysis:
    """Gate + tags + relevance for a headline/excerpt pair (pure function)."""
    text = f"{title}\n{snippet or ''}"
    terms = honey_terms(text, language)
    countries = tag_countries(text)
    topic_strength = tag_topics(title, snippet)
    topics = [k for k in TOPICS if k in topic_strength]

    score = float(BASE_SCORE)
    honey_in_title = bool(honey_terms(title or "", language))
    if honey_in_title:
        score += HONEY_IN_TITLE_BONUS
    # strongest topic counts fully, the next one half, the rest a quarter (diminishing returns,
    # so multi-topic articles do not all saturate at 100)
    pts = sorted((TOPICS[k]["weight"] * s for k, s in topic_strength.items()), reverse=True)
    topic_points = sum(w * (1.0 if i == 0 else 0.5 if i == 1 else 0.25) for i, w in enumerate(pts))
    score += min(TOPIC_CAP, topic_points)

    origins = [c for c in countries if c in ORIGINS_OF_INTEREST]
    if origins:
        score += min(20, 10 + 5 * (len(origins) - 1))
    markets = [c for c in countries if c in HOME_MARKETS]
    if markets:
        score += 5
    folded = fold(text)
    eu = bool(_EU_FOLDED.search(folded) or _EU_CASED.search(text) or _EU_RAW.search(folded))
    if eu:
        score += 12 if set(topics) & {"policy", "tariffs", "import_restrictions", "trade", "adulteration"} else 3
    bulk = bool(_BULK.search(folded) or _BULK_RAW.search(folded))
    if bulk:
        score += 10
    src_bonus = SOURCE_BONUS.get(reliability or "", 0)
    score += src_bonus

    penalties = []
    for name, (rx, points) in _PENALTIES.items():
        if rx.search(folded):
            penalties.append(name)
            score -= points
    score_i = int(round(max(0.0, min(100.0, score))))

    parts = []
    if topics:
        parts.append("topics=" + ",".join(topics))
    if origins:
        parts.append("origins=" + ",".join(origins))
    if markets:
        parts.append("markets=" + ",".join(markets))
    if eu:
        parts.append("eu")
    if bulk:
        parts.append("bulk")
    if src_bonus:
        parts.append(f"source={reliability}")
    if penalties:
        parts.append("penalties=" + ",".join(penalties))
    if not honey_in_title:
        parts.append("honey_in_excerpt")
    reason = "; ".join(parts)[:500] or "honey"
    return Analysis(honey_terms=terms, countries=countries, topics=topics, score=score_i, reason=reason,
                    factors={"topic_strength": topic_strength, "origins": origins, "markets": markets, "eu": eu,
                             "bulk": bulk, "penalties": penalties, "honey_in_title": honey_in_title})


_REASON_LABELS = {
    "topics": {"it": "Temi", "en": "Topics"},
    "origins": {"it": "Origini di interesse", "en": "Origins of interest"},
    "markets": {"it": "Mercati Parodi", "en": "Parodi markets"},
    "eu": {"it": "Unione Europea", "en": "European Union"},
    "bulk": {"it": "Commercio all'ingrosso / sfuso", "en": "Bulk / wholesale trade"},
    "source": {"it": "Fonte", "en": "Source"},
    "penalties": {"it": "Penalizzato", "en": "Penalised"},
    "honey_in_excerpt": {"it": "Miele citato solo nell'estratto", "en": "Honey mentioned only in the excerpt"},
    "honey": {"it": "Notizia sul miele", "en": "Honey news"},
}
_PENALTY_LABELS = {
    "recipe": {"it": "ricetta/cucina", "en": "recipe/cooking"},
    "health": {"it": "salute/benessere", "en": "health/wellness"},
    "local": {"it": "storia locale/hobby", "en": "local/hobby story"},
}
_SOURCE_LABELS = {
    "official": {"it": "ufficiale", "en": "official"},
    "industry": {"it": "di settore", "en": "industry"},
    "trade_press": {"it": "stampa di settore", "en": "trade press"},
}


def explain_reason(reason: str | None, lang: str = "it") -> str | None:
    """Human-readable rendering of a stored `relevance_reason`. Unknown text is returned as is."""
    if not reason:
        return None
    lang = "en" if lang == "en" else "it"
    out = []
    for part in reason.split(";"):
        part = part.strip()
        if not part:
            continue
        key, _, value = part.partition("=")
        label = _REASON_LABELS.get(key)
        if label is None:
            out.append(part)
            continue
        vals = [v for v in value.split(",") if v]
        if key == "topics":
            names = [TOPICS[v][lang] if v in TOPICS else v for v in vals]
        elif key in ("origins", "markets"):
            names = [country_name(v, lang) for v in vals]
        elif key == "penalties":
            names = [_PENALTY_LABELS.get(v, {}).get(lang, v) for v in vals]
        elif key == "source":
            names = [_SOURCE_LABELS.get(v, {}).get(lang, v) for v in vals]
        else:
            names = []
        out.append(f"{label[lang]}: {', '.join(names)}" if names else label[lang])
    return " · ".join(out) or None


def relevance_level(score: int) -> str:
    return "high" if score >= 60 else "medium" if score >= 35 else "low"


def topic_list() -> list[dict]:
    return [{"key": k, "it": v["it"], "en": v["en"]} for k, v in TOPICS.items()]


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


_NUMBER = re.compile(r"\d+")
# Opposite words: a headline that says one and a near-identical headline that says the other
# report different facts (direction of a move, stage of a ruling). Folded, multilingual.
_RISE = {"rise", "rises", "rising", "rose", "up", "increase", "increases", "increased", "jump", "jumps", "surge",
         "surges", "climb", "climbs", "higher", "gain", "gains", "aumento", "aumentano", "aumenta", "rialzo",
         "crescita", "salgono", "sube", "suben", "alza", "sobe", "sobem", "steigen", "steigt"}
_FALL = {"fall", "falls", "falling", "fell", "down", "decrease", "decreases", "decreased", "decline", "declines",
         "drop", "drops", "plunge", "plunges", "lower", "slump", "slumps", "calo", "calano", "cala", "ribasso",
         "crollo", "scendono", "cae", "caen", "baja", "bajan", "cai", "caem", "queda", "sinken", "sinkt"}
_PRELIMINARY = {"preliminary", "preliminare", "preliminari", "preliminar", "provisional", "provvisorio",
                "provvisori", "proposed", "vorlaufig"}
_FINAL = {"final", "finale", "finali", "definitivo", "definitivi", "definitive", "definitiva", "endgultig"}
_CONTRAST_PAIRS = ((_RISE, _FALL), (_PRELIMINARY, _FINAL))


def _contrast(ta: set[str], tb: set[str]) -> bool:
    """True when the two token sets take opposite sides of a contrast pair (rise/fall,
    preliminary/final). Rewordings on the same side ("rise" vs "climb") are not a contrast."""
    for x, y in _CONTRAST_PAIRS:
        sa, sb = (bool(ta & x), bool(ta & y)), (bool(tb & x), bool(tb & y))
        if sa != sb and any(sa) and any(sb):
            return True
    return False


@lru_cache(maxsize=4096)
def _title_countries(title_norm: str) -> frozenset[str]:
    return frozenset(tag_countries(title_norm))


def _is_fuzzy_duplicate(a: str, b: str) -> bool:
    """`a`, `b`: normalised titles (see `normalise_title`)."""
    ta, tb = a.split(), b.split()
    if min(len(ta), len(tb)) < 4:
        return False
    if min(len(ta), len(tb)) / max(len(ta), len(tb)) < 0.5:
        return False
    if fuzz.token_set_ratio(a, b) < FUZZY_THRESHOLD:
        return False
    # Same wording but a different origin/market, different figures or the opposite direction /
    # stage is a different story ("... duties on honey from Vietnam" vs "... from Brazil").
    if _title_countries(a) != _title_countries(b):
        return False
    na, nb = set(_NUMBER.findall(a)), set(_NUMBER.findall(b))
    if na and nb and na != nb:
        return False
    return not _contrast(set(ta), set(tb))


def find_original(session: Session, title_norm: str, when: datetime, *, is_demo: bool = False,
                  exclude_id: int | None = None) -> NewsArticle | None:
    """First-seen, non-duplicate article telling the same story within ±DEDUP_WINDOW_DAYS."""
    if not title_norm:
        return None
    lo, hi = when - timedelta(days=DEDUP_WINDOW_DAYS), when + timedelta(days=DEDUP_WINDOW_DAYS)
    when_col = func.coalesce(NewsArticle.published_at, NewsArticle.collected_at)
    q = select(NewsArticle).where(
        NewsArticle.duplicate_of_id.is_(None), NewsArticle.is_demo.is_(is_demo), when_col >= lo, when_col <= hi,
    )
    if exclude_id is not None:
        q = q.where(NewsArticle.id != exclude_id)
    candidates = list(session.scalars(q.order_by(NewsArticle.id)))
    for c in candidates:
        if c.title_norm == title_norm:
            return c
    best, best_score = None, 0.0
    for c in candidates:
        if _is_fuzzy_duplicate(title_norm, c.title_norm):
            s = fuzz.token_set_ratio(title_norm, c.title_norm)
            if s > best_score:
                best, best_score = c, s
    return best


def _fill_excerpt(session: Session, article: NewsArticle, snippet: str | None, publisher: str | None) -> None:
    """An article first stored without an excerpt (GDELT gives headlines only) receives the
    publisher's own excerpt when the same URL later arrives from a feed that carries one.

    Only the gap is filled: url, title, source, publication date and publisher stay as first
    stored. Tags derived from the text are recomputed with the excerpt (countries and topics
    are merged, the score only goes up), scored with the stored source's reliability. An AI
    summary written from the headline alone ("the source provides only the headline") is no
    longer true, so it is dropped and the article is queued for enrichment again; the AI
    headline translations stay valid."""
    excerpt = clean_snippet(snippet, article.title, publisher)
    if not excerpt:
        return
    article.snippet = excerpt
    src = session.get(Source, article.source_id)
    r = analyse(article.title, excerpt, language=article.language, reliability=src.reliability if src else None)
    countries = list(article.countries or [])
    countries += [c for c in r.countries if c not in countries]
    article.countries = countries or None
    topics = set(article.topics or []) | set(r.topics)
    article.topics = [k for k in TOPICS if k in topics] or None
    if r.score > (article.relevance_score or 0):
        article.relevance_score, article.relevance_reason = r.score, r.reason
    if article.ai_processed_at is not None or article.summary_it or article.summary_en:
        article.summary_it = article.summary_en = None
        article.ai_processed_at = None


def ingest_article(
    session: Session,
    source: Source,
    *,
    url: str,
    title: str,
    published_at: date | datetime | str | None = None,
    snippet: str | None = None,
    image_url: str | None = None,
    publisher: str | None = None,
    language: str | None = None,
) -> tuple[NewsArticle | None, Outcome]:
    """Store one feed item. Returns (article, outcome); article is None when filtered."""
    publisher = strip_html(publisher)[:200] or None
    clean = clean_title(title, publisher)
    link = clean_url(url or "")
    if not clean or not link.startswith(("http://", "https://")):
        return None, "filtered"
    canonical = canonicalize_url(link)

    existing = session.scalars(select(NewsArticle).where(NewsArticle.canonical_url == canonical)).first()
    if existing is not None:
        # Fill gaps only (never overwrite what we stored first).
        if existing.image_url is None:
            existing.image_url = normalise_image_url(image_url) or first_image(snippet)
        if existing.publisher is None and publisher:
            existing.publisher = publisher
        if not existing.snippet:
            _fill_excerpt(session, existing, snippet, publisher)
        return existing, "unchanged"

    lang = normalise_language(language) or normalise_language(source.language)
    excerpt = clean_snippet(snippet, clean, publisher)
    result = analyse(clean, excerpt, language=lang, reliability=source.reliability)
    if not result.is_honey:
        return None, "filtered"

    pub = _to_naive_utc(published_at)
    now = utcnow()
    if pub is not None and pub > now + FUTURE_TOLERANCE:
        pub = None  # a date in the future is a feed error; leave it unknown rather than invent one
    is_demo = source.reliability == "demo" or source.key == "demo"
    title_norm = normalise_title(clean)

    article = NewsArticle(
        source_id=source.id, url=link[:1500], canonical_url=canonical, title=clean[:600], title_norm=title_norm,
        publisher=publisher, language=lang, published_at=pub, collected_at=now,
        image_url=normalise_image_url(image_url) or first_image(snippet), snippet=excerpt,
        countries=result.countries or None, topics=result.topics or None, relevance_score=result.score,
        relevance_reason=result.reason, is_demo=is_demo,
    )
    original = find_original(session, title_norm, pub or now, is_demo=is_demo)
    outcome: Outcome = "new"
    if original is not None:
        article.duplicate_of_id = original.id
        original.duplicate_count = (original.duplicate_count or 0) + 1
        outcome = "duplicate"
    session.add(article)
    session.flush()
    return article, outcome
