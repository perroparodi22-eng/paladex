# News fixtures

## Real captures (`real_*`)

Downloaded from the live sources on 2026-11-04 (UTC) by Paladex's own HTTP client or curl
with the Paladex user agent. Only the number of `<item>` elements was reduced, to keep the
files small: every kept item, and the channel header, is byte-for-byte as served.

| File | URL | Kept |
|------|-----|------|
| `real_ec_agri_news.xml` | https://agriculture.ec.europa.eu/node/2/rss_en (European Commission, DG AGRI news; RSS link of https://agriculture.ec.europa.eu/media/news_en) | 4 of 30 items (none about honey) |
| `real_beeculture.xml` | https://beeculture.com/feed/ (`www.` redirects here) | 3 of 10 items (two carry the audio "Click Here if you listened ... Read along below!" prompt) |
| `real_apimondia.xml` | https://apimondia.org/feed/ (`www.` redirects here) | 3 of 10 items (the Brazil "beehives" item, the Dubai congress item, the Romania/Moldova visit) |
| `real_american_bee_journal.xml` | https://americanbeejournal.com/feed/ | 2 of 10 items (Sioux Honey plant; "garbage containers" column) |
| `real_gdelt_honey_italian.json` | https://api.gdeltproject.org/api/v2/doc/doc?query=honey%20sourcelang%3Aitalian&mode=ArtList&format=json&maxrecords=75&sort=DateDesc&timespan=7d (18:52 UTC) | complete (2 articles; `miele sourcelang:italian` returned `{}` 10 minutes earlier) |
| `real_gdelt_throttle.txt` | GDELT DOC API, HTTP 429 answer to a request sent 120 s after the previous answer (18:54 UTC; `server: GDELT Server`, no Retry-After) | complete |

## Reconstructed fixtures (NOT captured from live sources)

These files were written by hand while building `paladex/collectors/news_feeds.py` in a
sandbox without internet access. They reproduce the documented *structure* of each feed
family; every headline, excerpt, outlet name, URL and date in them is synthetic test
content and must never be shown to a user or loaded into a real database.

| File | Format reproduced |
|------|-------------------|
| `google_news_en.xml` | Google News RSS search feed (`news.google.com/rss/search?q=...&hl=en-US&gl=US&ceid=US:en`): `<title>` = "Headline - Outlet", `<link>`/`<guid>` = `news.google.com/rss/articles/...?oc=5`, `<description>` = HTML `<a href>` + `<font>` outlet (sometimes an `<ol>` cluster of related headlines), `<source url="...">Outlet</source>`. One item uses the older format where the description links the publisher's real URL. |
| `rss2_wordpress.xml` | WordPress RSS 2.0 (`/feed/`): `content:encoded`, `dc:creator`, `media:content`, `<enclosure>`, `<img>` in the description, "The post ... appeared first on ..." boilerplate, `utm_*` tracking parameters in links. |
| `atom.xml` | Atom 1.0 (`<feed xmlns="http://www.w3.org/2005/Atom">`): `<link rel="alternate">`, `<summary type="html">`, `<content type="html">`, `<published>`/`<updated>`, `media:thumbnail`. |
| `malformed_rss.xml` | RSS 2.0 with an unescaped `&` and an unclosed tag (feedparser sets `bozo` but still recovers the items). |
| `not_a_feed.html` | An HTML page (e.g. a cookie wall) returned instead of a feed. |

Dates are in late October / early November 2026; tests pin "now" to 2026-11-02 so the
age filters behave deterministically.
