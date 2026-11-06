"""Controlled vocabularies.

These are the core of the "never mix different kinds of numbers" rule: every price row
carries a PriceType, every number carries a DataStatus and a Reliability.
Stored as plain strings in SQLite so the database stays readable.
"""
from __future__ import annotations

from enum import StrEnum


class PriceType(StrEnum):
    """What a price actually measures. These are NOT interchangeable."""

    WHOLESALE_BULK = "wholesale_bulk"          # trade quotation for bulk honey (drums/IBC), e.g. USDA, Italian price lists
    PRODUCER = "producer"                      # paid to beekeepers / farm-gate (FAO producer prices, USDA "paid to beekeepers")
    IMPORT_UNIT_VALUE = "import_unit_value"    # customs value / net weight on imports (CIF) — derived, not a quote
    EXPORT_UNIT_VALUE = "export_unit_value"    # customs value / net weight on exports (FOB) — derived, not a quote
    RETAIL = "retail"                          # consumer shelf price
    OTHER = "other"


class TradeFlow(StrEnum):
    IMPORT = "import"
    EXPORT = "export"
    RE_IMPORT = "re_import"
    RE_EXPORT = "re_export"


class DataStatus(StrEnum):
    """How current / how firm a number is."""

    LIVE = "live"                    # fetched from a source that updates continuously (rare for honey)
    PUBLISHED = "published"          # official published figure for a closed period
    PROVISIONAL = "provisional"      # published but flagged as provisional / subject to revision
    ESTIMATE = "estimate"            # an estimate by the publisher (e.g. FAO imputed, forecast)
    FORECAST = "forecast"
    AI_ASSESSMENT = "ai_assessment"  # produced by our own AI — never a source fact
    USER_ENTERED = "user_entered"    # typed in by the user (supplier quotes)
    DEMO = "demo"                    # demonstration data — never real


class Reliability(StrEnum):
    OFFICIAL = "official"            # government / intergovernmental statistics
    INDUSTRY = "industry"            # industry body / observatory / chamber of commerce price list
    TRADE_PRESS = "trade_press"      # magazines, news
    AGGREGATOR = "aggregator"        # search-engine feeds
    USER = "user"
    AI = "ai"
    DEMO = "demo"


class SourceKind(StrEnum):
    API = "api"
    RSS = "rss"
    PDF = "pdf"
    HTML = "html"
    BULK_FILE = "bulk_file"
    MANUAL = "manual"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"              # some items failed to parse
    NO_CHANGE = "no_change"          # reached the source, nothing new
    FAILED = "failed"
    OFFLINE = "offline"              # no internet: skipped, cached data still shown
    SKIPPED = "skipped"              # e.g. missing API key / disabled


class Variety(StrEnum):
    POLYFLORA = "polyflora"          # multifloral / millefiori / wildflower / multiflora
    ACACIA = "acacia"                # Robinia pseudoacacia (black locust)
    ORANGE_BLOSSOM = "orange_blossom"  # agrumi / citrus / azahar
    CHESTNUT = "chestnut"
    LAVENDER = "lavender"
    DANDELION = "dandelion"
    SUNFLOWER = "sunflower"
    EUCALYPTUS = "eucalyptus"
    CLOVER = "clover"
    LINDEN = "linden"                # tiglio / lime
    RAPESEED = "rapeseed"            # colza
    BUCKWHEAT = "buckwheat"
    HONEYDEW = "honeydew"            # melata
    MANUKA = "manuka"
    ORGANIC_POLYFLORA = "organic_polyflora"
    UNSPECIFIED = "unspecified"      # source gives no variety (e.g. HS 0409 trade, FAO totals)
    OTHER = "other"


class AlertType(StrEnum):
    PRICE_CHANGE = "price_change"
    NEW_REPORT = "new_report"
    NEWS_KEYWORD = "news_keyword"
    REGULATION = "regulation"
    TRADE_CHANGE = "trade_change"


class QualityIssueType(StrEnum):
    STALE = "stale"                  # source has not updated within its expected frequency
    MISSING = "missing"              # expected series/period missing
    OUTLIER = "outlier"              # value far from series history
    DISCREPANCY = "discrepancy"      # two sources disagree for the same thing
    PARSE_WARNING = "parse_warning"
    COLLECTION_FAILED = "collection_failed"
    USER_FLAG = "user_flag"          # a person marked a figure as doubtful (services/corrections.py)


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
