"""Headlines in other languages get an Italian machine translation when no AI provider is configured
(services/title_translate.py). The translation service is mocked: no test talks to it."""
from __future__ import annotations

import json
from datetime import timedelta

import httpx
import pytest
import respx
from sqlalchemy import select

from paladex.models import AppSetting, NewsArticle, Source, utcnow
from paladex.services import news as ns
from paladex.services import title_translate as tt


@pytest.fixture()
def on(db, monkeypatch):
    """The feature switched on (conftest switches it off for every other test)."""
    from paladex import config

    monkeypatch.setenv("PALADEX_TITLE_TRANSLATION", "true")
    config.get_settings.cache_clear()
    yield db
    config.get_settings.cache_clear()


def _src(db, key="news_rs_agropress_med") -> Source:
    return db.scalars(select(Source).where(Source.key == key)).one()


def _add(db, title, lang, days=1, key="news_rs_agropress_med", url=None) -> NewsArticle:
    a, outcome = ns.ingest_article(db, _src(db, key), url=url or f"https://x.example/{abs(hash(title))}", title=title,
                                   language=lang, published_at=utcnow() - timedelta(days=days))
    assert outcome == "new", (title, outcome)
    return a


def answer(text: str, *, by: str = "MT!", match: float = 0.85, status=200, quota=False, extra=()) -> dict:
    return {"responseData": {"translatedText": text, "match": match}, "quotaFinished": quota, "responseStatus": status,
            "matches": [*extra, {"translation": text, "created-by": by, "match": match}]}


SR = "Извоз српског меда у Кину подиже откупну цену за 50 одсто"
IT = "L'esportazione di miele serbo in Cina aumenta il prezzo di acquisto del 50%"


def test_only_the_machine_translation_of_the_exact_headline_is_taken():
    assert tt.pick_translation(answer(IT)) == IT
    assert tt.pick_translation(answer("Il miele &egrave; buono &#39;oggi&#39;")) == "Il miele è buono 'oggi'"
    # a similar sentence from someone's translation memory is not this headline...
    fuzzy = {"responseData": {"translatedText": "Il miele costa poco", "match": 0.62}, "responseStatus": 200,
             "matches": [{"translation": "Il miele costa poco", "created-by": "MateCat", "match": 0.62}]}
    assert tt.pick_translation(fuzzy) is None
    # ...an exact (100%) memory match is, and the machine translation is preferred to a fuzzy one listed first
    assert tt.pick_translation(answer("Esatto", by="MateCat", match=1)) == "Esatto"
    mixed = answer(IT, extra=[{"translation": "Altra frase", "created-by": "MateCat", "match": 0.7}])
    assert tt.pick_translation(mixed) == IT
    assert tt.pick_translation({"responseStatus": 403, "responseData": {"translatedText": "INVALID LANGUAGE PAIR"}}) is None
    for notice in (answer("MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS FOR TODAY."),
                   answer(IT, quota=True), answer("x", status=429)):
        with pytest.raises(tt.QuotaReached):
            tt.pick_translation(notice)


def test_a_translation_must_keep_the_headlines_numbers_and_say_something():
    assert tt.acceptable(SR, IT)
    assert not tt.acceptable(SR, "L'esportazione di miele serbo aumenta il prezzo del 5%")      # 50 became 5
    assert not tt.acceptable(SR, SR) and not tt.acceptable(SR, "") and not tt.acceptable(SR, None)
    assert not tt.acceptable("Med", "x" * 200)
    assert tt.is_machine("mymemory") and not tt.is_machine("anthropic:claude") and not tt.is_machine(None)


@respx.mock
def test_pending_headlines_are_translated_in_order_of_use_and_labelled(on, api):
    db = on
    spanish = _add(db, "Las exportaciones de miel argentina crecen 20%", "es", key="news_ar_infocampo_miel")
    serbian = _add(db, SR, "sr")
    slovenian_dull = _add(db, "Vabilo na občni zbor čebelarjev", "sl", key="news_si_czs")
    english = _add(db, "Honey prices firm as packers look for white honey", "en", key="news_bee_culture")
    italian = _add(db, "Il prezzo del miele sale", "it", key="news_it_terraevita_miele")
    db.commit()
    asked: list[str] = []

    def reply(request: httpx.Request) -> httpx.Response:
        q = request.url.params["q"]
        asked.append(request.url.params["langpair"])
        assert request.headers["user-agent"].startswith("Paladex/") and "de" not in request.url.params
        return httpx.Response(200, json=answer({SR: IT}.get(q, f"Traduzione di: {q}")))

    respx.get(tt.API_URL).mock(side_effect=reply)
    stats = tt.translate_pending(db, pause=0)
    # the unreadable languages first (the relevant article before the dull one), then Spanish, then English;
    # Italian is never asked
    assert asked == ["sr|it", "sl|it", "es|it", "en|it"] and stats["translated"] == 4 and stats["rejected"] == 0
    db.expire_all()
    assert db.get(NewsArticle, serbian.id).title_it == IT and db.get(NewsArticle, serbian.id).ai_model == "mymemory"
    assert db.get(NewsArticle, serbian.id).title == SR                       # the original is never touched
    assert db.get(NewsArticle, italian.id).title_it is None
    assert db.get(NewsArticle, slovenian_dull.id).title_it and db.get(NewsArticle, english.id).title_it
    state = db.get(AppSetting, tt.STATE_KEY).value
    assert state["chars"] == sum(len(a.title) for a in (spanish, serbian, slovenian_dull, english))

    # on screen: the Italian headline, said to be a machine translation, with the original at hand
    item = next(i for i in api.get("/api/news", params={"min_relevance": 0}).json()["items"] if i["id"] == serbian.id)
    assert item["display"]["it"] == {**item["display"]["it"], "title": IT, "title_is_ai": True, "title_by": "machine"}
    assert item["title"] == SR and item["display"]["en"]["title"] == SR and item["display"]["en"]["title_by"] is None
    # nothing is asked twice
    asked.clear()
    assert tt.translate_pending(db, pause=0)["translated"] == 0 and asked == []


@respx.mock
def test_the_daily_allowance_and_the_services_notice_stop_the_pass(on, monkeypatch):
    db = on
    rows = [_add(db, f"Извоз меда расте {i} пут ове године, кажу пчелари из Србије", "sr", days=i + 1) for i in range(6)]
    db.commit()
    route = respx.get(tt.API_URL).mock(side_effect=lambda r: httpx.Response(
        200, json=answer("Tradotto: " + r.url.params["q"])))
    monkeypatch.setattr(tt, "DAILY_CHARS_ANONYMOUS", len(rows[0].title) * 2 + 5)
    assert tt.translate_pending(db, pause=0)["translated"] == 2 and route.call_count == 2      # budget for two
    assert tt.translate_pending(db, pause=0)["translated"] == 0 and route.call_count == 2      # same day: nothing more
    # a new day; this time the service itself says the allowance is used up after one headline
    state = dict(db.get(AppSetting, tt.STATE_KEY).value)
    state["day"] = "2000-01-01"
    db.get(AppSetting, tt.STATE_KEY).value = state
    db.commit()
    monkeypatch.setattr(tt, "DAILY_CHARS_ANONYMOUS", 4500)
    replies = iter([httpx.Response(200, json=answer("Tradotto ancora 3")),
                    httpx.Response(200, json=answer("MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS FOR TODAY."))])
    route.mock(side_effect=lambda r: next(replies))
    stats = tt.translate_pending(db, pause=0)
    assert stats["quota_reached"] is True and stats["translated"] <= 1
    assert all("MYMEMORY" not in (a.title_it or "") for a in db.scalars(select(NewsArticle)))
    before = route.call_count
    assert tt.translate_pending(db, pause=0)["quota_reached"] is True and route.call_count == before


@respx.mock
def test_rejected_answers_are_not_stored_nor_asked_again_and_network_trouble_is_retried(on):
    db = on
    a = _add(db, "Цена меда порасла за 50 одсто у Србији", "sr")
    db.commit()
    route = respx.get(tt.API_URL).mock(return_value=httpx.Response(200, json=answer("Il prezzo del miele è salito del 5%")))
    stats = tt.translate_pending(db, pause=0)
    assert stats == {**stats, "translated": 0, "rejected": 1} and db.get(NewsArticle, a.id).title_it is None
    assert tt.translate_pending(db, pause=0)["rejected"] == 0 and route.call_count == 1
    b = _add(db, "Пчелари траже веће подстицаје", "sr")
    db.commit()
    route.mock(side_effect=httpx.ConnectError("offline"))
    assert tt.translate_pending(db, pause=0)["translated"] == 0
    route.mock(return_value=httpx.Response(200, json=answer("Gli apicoltori chiedono incentivi più alti")))
    assert tt.translate_pending(db, pause=0)["translated"] == 1                    # asked again once back online
    assert db.get(NewsArticle, b.id).title_it == "Gli apicoltori chiedono incentivi più alti"


def test_chinese_and_japanese_headlines_are_short_and_write_numbers_their_own_way():
    # a compact script: the Italian is several times longer
    assert tt.acceptable("熊本地震被災の養蜂園 鶴居産ハチミツが復興の希望に 過去最多の収穫量",
                         "Il miele prodotto dall'apicoltura Tsurui, colpita dal terremoto di Kumamoto, diventa una "
                         "speranza per la ricostruzione: raccolto record")
    assert not tt.acceptable("蜂蜜", "x" * 200)
    # full-width digits, tenths ("３割" is 30%), ten-thousands ("10万" is 100,000)
    assert tt.acceptable("銀座ビル屋上、養蜂始め２０年 蜂蜜年２．８トン", "Sul tetto di Ginza, 20 anni di apicoltura: 2,8 tonnellate di miele")
    assert tt.acceptable("ハチミツの収量が例年の３割に", "La produzione di miele scende al 30% del solito")
    assert tt.acceptable("無届けなら「10万円以下の過料」も", "Senza notifica, multa fino a 100.000 yen")
    assert not tt.acceptable("無届けなら「10万円以下の過料」も", "Senza notifica, multa fino a 10.000 yen")
    assert tt.acceptable("蜂蜜出口增长12.5万吨", "Le esportazioni di miele crescono di 125.000 tonnellate")
    assert not tt.acceptable("蜂蜜出口增长12.5万吨", "Le esportazioni di miele crescono di 12,5 tonnellate")
    # Indian English: lakh (100,000) and crore (10 million)
    lakh = "India doubles honey production to 1.5 lakh metric tonnes, exports triple: PM Modi"
    assert tt.acceptable(lakh, "L'India raddoppia la produzione di miele a 150.000 tonnellate, le esportazioni triplicano: PM Modi")
    assert not tt.acceptable(lakh, "L'India raddoppia la produzione di miele a 15.000 tonnellate, le esportazioni triplicano")
    assert tt.acceptable("Honey mission gets Rs 500 crore", "La missione del miele riceve 5 miliardi di rupie") is False
    assert tt.acceptable("Honey mission gets Rs 500 crore", "La missione del miele riceve 5.000.000.000 di rupie")


@respx.mock
def test_headlines_rejected_under_older_checks_are_asked_again_once(on):
    db = on
    a = _add(db, "ハチミツの収量が例年の３割に", "ja")
    db.add(AppSetting(key=tt.STATE_KEY, value={"day": "2026-11-15", "chars": 4500, "quota_reached": False, "failed": [a.id]}))
    db.commit()
    route = respx.get(tt.API_URL).mock(return_value=httpx.Response(200, json=answer("La produzione di miele scende al 30% del solito")))
    assert tt.translate_pending(db, pause=0)["translated"] == 1 and route.call_count == 1
    state = db.get(AppSetting, tt.STATE_KEY).value
    assert state["rules"] == tt.RULES and state["failed"] == []
    # with the current checks a rejected headline is still not asked twice
    b = _add(db, "蜂蜜出口增长12.5万吨", "zh")
    db.commit()
    route.mock(return_value=httpx.Response(200, json=answer("Le esportazioni di miele crescono di 12,5 tonnellate")))
    assert tt.translate_pending(db, pause=0)["rejected"] == 1
    assert tt.translate_pending(db, pause=0)["rejected"] == 0 and route.call_count == 2
    assert db.get(AppSetting, tt.STATE_KEY).value["failed"] == [b.id]


@respx.mock
def test_off_by_setting_off_with_an_ai_provider_and_the_optional_email(db, monkeypatch):
    from paladex import config

    _add(db, SR, "sr")
    db.commit()
    route = respx.get(tt.API_URL).mock(return_value=httpx.Response(200, json=answer(IT)))
    assert tt.translate_pending(db, pause=0) == {"enabled": False, "translated": 0, "rejected": 0, "chars": 0,
                                                 "quota_reached": False} and route.call_count == 0
    monkeypatch.setenv("PALADEX_TITLE_TRANSLATION", "true")
    monkeypatch.setenv("PALADEX_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("PALADEX_ANTHROPIC_API_KEY", "test-key")
    config.get_settings.cache_clear()
    assert tt.translate_pending(db, pause=0)["enabled"] is False and route.call_count == 0     # the AI translates
    monkeypatch.setenv("PALADEX_LLM_PROVIDER", "none")
    monkeypatch.setenv("PALADEX_TITLE_TRANSLATION_EMAIL", "owner@example.org")
    config.get_settings.cache_clear()
    assert tt.translate_pending(db, pause=0)["translated"] == 1
    assert route.calls.last.request.url.params["de"] == "owner@example.org"
    assert json.loads(route.calls.last.response.content)["responseStatus"] == 200
    config.get_settings.cache_clear()
