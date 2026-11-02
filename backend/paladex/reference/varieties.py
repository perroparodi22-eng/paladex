"""Honey variety vocabulary and normalisation (EN / IT / ES / DE / FR / PT / RO / UK-latin).

`normalize_variety(raw)` returns (Variety, organic_flag). Unknown text -> Variety.OTHER,
empty -> Variety.UNSPECIFIED. The raw text is always stored next to the normalised value.
"""
from __future__ import annotations

import re
import unicodedata

from ..enums import Variety

LABELS: dict[str, dict[str, str]] = {
    Variety.POLYFLORA: {"it": "Millefiori", "en": "Multifloral (polyflora)"},
    Variety.ACACIA: {"it": "Acacia", "en": "Acacia"},
    Variety.ORANGE_BLOSSOM: {"it": "Agrumi / Fiori d'arancio", "en": "Orange blossom"},
    Variety.CHESTNUT: {"it": "Castagno", "en": "Chestnut"},
    Variety.LAVENDER: {"it": "Lavanda", "en": "Lavender"},
    Variety.DANDELION: {"it": "Tarassaco", "en": "Dandelion"},
    Variety.SUNFLOWER: {"it": "Girasole", "en": "Sunflower"},
    Variety.EUCALYPTUS: {"it": "Eucalipto", "en": "Eucalyptus"},
    Variety.CLOVER: {"it": "Trifoglio", "en": "Clover"},
    Variety.LINDEN: {"it": "Tiglio", "en": "Linden"},
    Variety.RAPESEED: {"it": "Colza", "en": "Rapeseed"},
    Variety.BUCKWHEAT: {"it": "Grano saraceno", "en": "Buckwheat"},
    Variety.HONEYDEW: {"it": "Melata", "en": "Honeydew"},
    Variety.MANUKA: {"it": "Manuka", "en": "Mānuka"},
    Variety.ORGANIC_POLYFLORA: {"it": "Millefiori biologico", "en": "Organic multifloral"},
    Variety.UNSPECIFIED: {"it": "Non specificata", "en": "Not specified"},
    Variety.OTHER: {"it": "Altra", "en": "Other"},
}

# The nine varieties the business tracks first (UI default order).
CORE_VARIETIES: list[str] = [
    Variety.POLYFLORA, Variety.ACACIA, Variety.ORANGE_BLOSSOM, Variety.CHESTNUT, Variety.LAVENDER,
    Variety.DANDELION, Variety.SUNFLOWER, Variety.EUCALYPTUS, Variety.CLOVER,
]

# Order matters: more specific patterns first.
_PATTERNS: list[tuple[str, Variety]] = [
    (r"\bmanuka\b", Variety.MANUKA),
    (r"\b(acacia|acacie|robinia|black locust|locust|akazie|acacia honey|salcam|salcâm|bagrem)\b", Variety.ACACIA),
    (r"\b(orange blossom|orange|agrumi|arancio|arancia|zagara|citrus|citrique|azahar|naranjo|azahar de naranjo|flor de laranjeira|laranjeira)\b", Variety.ORANGE_BLOSSOM),
    (r"\b(chestnut|castagno|castagna|castano|castaño|kastanie|chataignier|châtaignier|castanheiro)\b", Variety.CHESTNUT),
    (r"\b(lavender|lavanda|lavandin|lavande|lavendel|lavanda de)\b", Variety.LAVENDER),
    (r"\b(dandelion|tarassaco|taraxacum|diente de leon|diente de león|löwenzahn|lowenzahn|pissenlit)\b", Variety.DANDELION),
    (r"\b(sunflower|girasole|girasol|tournesol|sonnenblume|floarea soarelui|soniashnyk)\b", Variety.SUNFLOWER),
    (r"\b(eucalyptus|eucalipto|eukalyptus|eucalypt)\b", Variety.EUCALYPTUS),
    (r"\b(clover|trifoglio|trebol|trébol|trevo|klee|trefle|trèfle|sweet clover|alfalfa clover)\b", Variety.CLOVER),
    (r"\b(linden|lime tree|tiglio|tilo|tilleul|linde|basswood|tei)\b", Variety.LINDEN),
    (r"\b(rapeseed|rape|canola|colza|raps|rapita|mustard)\b", Variety.RAPESEED),
    (r"\b(buckwheat|grano saraceno|saraceno|alforfon|sarrasin|buchweizen)\b", Variety.BUCKWHEAT),
    (r"\b(honeydew|melata|mielato|forest honey|bosque|waldhonig|pine honey|pino|fir)\b", Variety.HONEYDEW),
    (r"\b(polyflora|polyfloral|multifloral|multiflora|multifiore|multi floral|millefiori|mille fiori|wildflower|wild flower|"
     r"mixed flower|multiflower|polifloral|poliflora|milflores|mil flores|toutes fleurs|blutenhonig|blütenhonig|silvestre|"
     r"pradera|meadow|pampa|pampas|silvestre|polyflower|poly flora|light amber honey)\b", Variety.POLYFLORA),
]

_ORGANIC = re.compile(r"\b(organic|biologico|bio|orgánico|organico|ecologico|ecológico|biologique|öko|oko)\b")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    return re.sub(r"\s+", " ", s).strip()


def normalize_variety(raw: str | None) -> tuple[str, bool]:
    if not raw or not raw.strip():
        return Variety.UNSPECIFIED.value, False
    text = _norm(raw)
    organic = bool(_ORGANIC.search(text))
    for pattern, variety in _PATTERNS:
        if re.search(pattern, text):
            if organic and variety == Variety.POLYFLORA:
                return Variety.ORGANIC_POLYFLORA.value, True
            return variety.value, organic
    return Variety.OTHER.value, organic


def variety_label(v: str, lang: str = "it") -> str:
    return LABELS.get(v, {}).get(lang, v)


# USDA uses colour grades for bulk honey without a floral source.
USDA_COLORS = ["water white", "extra white", "white", "extra light amber", "light amber", "amber", "dark amber", "dark"]


def detect_color_grade(raw: str | None) -> str | None:
    if not raw:
        return None
    t = _norm(raw)
    for c in sorted(USDA_COLORS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(c)}\b", t):
            return c
    # Abbreviations only when the whole cell is the abbreviation ("la" is also a Spanish/Italian article).
    abbreviations = {"ela": "extra light amber", "la": "light amber", "ew": "extra white", "ww": "water white"}
    return abbreviations.get(t.replace(".", ""))
