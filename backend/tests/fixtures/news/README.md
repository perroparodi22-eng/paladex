# News feed fixtures (RECONSTRUCTED — not captured from live sources)

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
