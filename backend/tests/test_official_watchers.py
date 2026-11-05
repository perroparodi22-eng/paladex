"""Tests for the origin-country official notice watchers (paladex/collectors/official_watchers.py):
``br_mapa_honey`` (MAPA news + DOU), ``ar_senasa_honey`` (SENASA news, Plan CREHA Lista EAR,
Boletín Oficial) and ``in_dgft_honey`` (DGFT notifications, minimum export price).

All fixtures in tests/fixtures/official_watchers/ are RECONSTRUCTED from documentation (see the
README there): every page, notice, number, price and date is illustrative, not a real record.
"""
from __future__ import annotations

import ast
import dataclasses
import importlib.util
import re
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from paladex.collectors import official_watchers as ow
from paladex.collectors.registry import IMPORT_ERRORS, all_collectors, get_collector
from paladex.models import AppSetting, RawDocument, RegulationItem, Source
from paladex.reference.countries import countries as reference_countries

FIX = Path(__file__).parent / "fixtures" / "official_watchers"
TODAY = date(2026, 11, 4)                    # a Wednesday; the latest Boletín Oficial fixture is 04/11/2026
PDF = "application/pdf"
KEYS = ("br_mapa_honey", "ar_senasa_honey", "in_dgft_honey")

MAPA_ART = "https://www.gov.br/agricultura/pt-br/assuntos/noticias/"
MAPA_LIST = r"^https://www\.gov\.br/agricultura/pt-br/assuntos/noticias$"
MAPA_P2 = r"^https://www\.gov\.br/agricultura/pt-br/assuntos/noticias\?b_start"
DOU = r"^https://www\.in\.gov\.br/consulta/-/buscar/dou\?q="
DOU_MEL, DOU_APICOLA, DOU_APICULTURA = DOU + "%22mel%22", DOU + "%22ap%C3%ADcola%22", DOU + "%22apicultura%22"
SENASA_LIST = r"^https://www\.argentina\.gob\.ar/senasa/noticias$"
EAR_FILES = "https://www.argentina.gob.ar/sites/default/files/"
BO = "https://www.boletinoficial.gob.ar"
BO_LATEST = r"^https://www\.boletinoficial\.gob\.ar/seccion/primera$"
DGFT_PDF = "https://content.dgft.gov.in/Website/dgftprod/fixture-{n}/Noti%20{n}%20English.pdf"

ART_LISTA_UE = "brasil-apresenta-a-uniao-europeia-plano-para-reinclusao-na-lista-ilustrativo"
ART_PESCADO = "uniao-europeia-atualiza-lista-de-estabelecimentos-de-pescado-ilustrativo"
ART_APICULTURA = "mapa-lanca-programa-de-boas-praticas-na-apicultura-ilustrativo"
ART_EXPORTACOES = "exportacoes-de-mel-natural-crescem-no-terceiro-trimestre-ilustrativo"
ART_PNCRC = "mapa-publica-resultados-do-pncrc-para-mel-e-pescado-ilustrativo"
DOU_PORTARIA = "portaria-sda/mapa-n-9.901-de-30-de-outubro-de-2026-ilustrativa-999000001"
DOU_IN = "instrucao-normativa-sda/mapa-n-9.904-de-20-de-outubro-de-2026-ilustrativa-999000004"


def mapa_ref(slug: str) -> str:
    return f"mapa:/agricultura/pt-br/assuntos/noticias/{slug}"


MAPA_EXPECTED = {
    mapa_ref(ART_EXPORTACOES), mapa_ref(ART_LISTA_UE), mapa_ref(ART_PNCRC), mapa_ref(ART_APICULTURA),
    f"dou:{DOU_PORTARIA}", f"dou:{DOU_IN}",
}
SENASA_EXPECTED = {
    "senasa:/noticias/el-senasa-certifico-un-nuevo-embarque-de-miel-a-granel-ilustrativo",
    "senasa:/noticias/se-autorizaron-nuevos-barnices-libres-de-bisfenol-ilustrativo",
    "senasa:/noticias/resultados-del-plan-creha-en-productos-apicolas-ilustrativo",
    "SENASA Lista EAR 2026 N°91",
    "BO-AR primera 999101",
}
DGFT_EXPECTED = {"DGFT Notification No. 94/2026-27", "DGFT Notification No. 91/2026-27", "DGFT Notification No. 93/2025-26"}
EXPECTED = {"br_mapa_honey": MAPA_EXPECTED, "ar_senasa_honey": SENASA_EXPECTED, "in_dgft_honey": DGFT_EXPECTED}


def fx(name: str) -> bytes:
    return (FIX / name).read_bytes()


def fx_text(name: str) -> str:
    return fx(name).decode("utf-8")


def _routes(base: dict, override: dict | None) -> dict:
    """Overrides first: the first matching route wins."""
    routes = dict(override or {})
    for k, v in base.items():
        routes.setdefault(k, v)
    return routes


def mapa_routes(override: dict | None = None, *, articles: bool = True) -> dict:
    base = {
        MAPA_P2: fx("mapa_noticias_p2.html"),
        MAPA_LIST: fx("mapa_noticias_p1.html"),
        DOU_MEL: fx("dou_busca_mel.html"),
        DOU_APICOLA: fx("dou_busca_apicola.html"),
        DOU_APICULTURA: fx("dou_busca_apicultura.html"),
    }
    if articles:
        base = {
            MAPA_ART + ART_LISTA_UE: fx("mapa_noticia_lista_ue.html"),
            MAPA_ART + ART_PESCADO: fx("mapa_noticia_lista_ue_pescado.html"),
            MAPA_ART + ART_APICULTURA: fx("mapa_noticia_apicultura.html"),
            **base,
        }
    return _routes(base, override)


def senasa_routes(override: dict | None = None, *, details: bool = True) -> dict:
    base = {
        SENASA_LIST: fx("senasa_noticias.html"),
        BO_LATEST: fx("bo_primera.html"),
    }
    if details:
        base.update({
            ow.SENASA_CREHA_URL: fx("senasa_creha.html"),
            EAR_FILES + "ear_91-26_producto.pdf": (200, fx("ear_91-26_producto.pdf"), PDF),
            EAR_FILES + "ear_90-26_producto.pdf": (200, fx("ear_90-26_producto.pdf"), PDF),
            BO + "/detalleAviso/primera/999101/20261104": fx("bo_aviso_999101.html"),
            BO + "/detalleAviso/primera/999102/20261104": fx("bo_aviso_999102.html"),
            BO + "/detalleAviso/primera/999090/20261102": fx("bo_aviso_999090.html"),
            BO + "/seccion/primera/20261102": fx("bo_primera_20261102.html"),
            BO + "/seccion/primera/20261103": (404, b"<html><title>No encontrado</title></html>"),
        })
    return _routes(base, override)


def dgft_routes(override: dict | None = None, *, pdfs: bool = True) -> dict:
    base = {ow.DGFT_LIST_URL: fx("dgft_notifications.html")}
    if pdfs:
        base.update({
            DGFT_PDF.format(n=94): (200, fx("dgft_notif_94_2026-27.pdf"), PDF),
            DGFT_PDF.format(n=91): (200, fx("dgft_notif_91_2026-27.pdf"), PDF),
            DGFT_PDF.format(n=93): (200, fx("dgft_notif_93_2025-26.pdf"), PDF),
        })
    return _routes(base, override)


ROUTES = {"br_mapa_honey": mapa_routes, "ar_senasa_honey": senasa_routes, "in_dgft_honey": dgft_routes}


@pytest.fixture()
def pin_today(monkeypatch):
    def _pin(d: date):
        monkeypatch.setattr(ow, "today", lambda: d)
    _pin(TODAY)
    return _pin


def _src(s, key: str) -> Source:
    return s.scalars(select(Source).where(Source.key == key)).one()


def _items(s, key: str) -> dict[str, RegulationItem]:
    src = _src(s, key)
    return {r.reference: r for r in s.scalars(select(RegulationItem).where(RegulationItem.source_id == src.id))}


def _state(s, key: str) -> dict:
    row = s.get(AppSetting, f"collector_state:{key}")
    return dict(row.value) if row else {}


def _raw_urls(s, key: str) -> list[str]:
    return list(s.scalars(select(RawDocument.url).where(RawDocument.source_id == _src(s, key).id)))


def _seed_state(session_factory, key: str, value: dict) -> None:
    with session_factory() as s:
        s.add(AppSetting(key=f"collector_state:{key}", value=value))


def _without(routes: dict, *needles: str) -> dict:
    return {k: v for k, v in routes.items() if not any(n in (k if isinstance(k, str) else k[1]) for n in needles)}


# ===========================================================================
# Registry, metadata, fixtures
# ===========================================================================


def test_collectors_registered_as_official_keyless_regulation_sources():
    all_collectors(refresh=True)
    assert "paladex.collectors.official_watchers" not in IMPORT_ERRORS
    expected = {"br_mapa_honey": ("BRA", "pt"), "ar_senasa_honey": ("ARG", "es"), "in_dgft_honey": ("IND", "en")}
    for key, (iso3, lang) in expected.items():
        c = get_collector(key)
        assert c is not None, key
        assert c.reliability == "official" and c.category == "regulation" and c.kind == "html"
        assert c.requires_key is None and c.default_enabled is True
        assert (c.country_iso3, c.language) == (iso3, lang)
        assert c.schedule["trigger"] == "cron"
        assert c.expected_update and c.expected_update_en and c.expected_max_age_days
        assert "PAGE WATCHER" in c.terms_note and "clear message" in c.terms_note


def test_sources_are_stored_with_official_reliability(session_factory, db):
    with session_factory() as s:
        for key in KEYS:
            src = _src(s, key)
            assert src.reliability == "official" and src.category == "regulation", key


def test_fixture_readme_says_reconstructed_and_lists_every_fixture():
    readme = (FIX / "README.md").read_text(encoding="utf-8")
    assert "RECONSTRUCTED" in readme and "reconstructed from documentation" in readme
    assert "illustrative" in readme.lower() and "invented" in readme
    for f in sorted(FIX.iterdir()):
        if f.name != "README.md" and not f.name.startswith(("__", ".")):
            assert f"`{f.name}`" in readme, f"{f.name} is not described in README.md"


@pytest.mark.parametrize("name", sorted(p.name for p in FIX.glob("*.html")))
def test_every_html_fixture_is_marked_reconstructed(name):
    head = fx_text(name).splitlines()[1:3]
    comment = re.search(r"<!--(.*?)-->", "\n".join(fx_text(name).splitlines()[1:]), re.DOTALL).group(1)
    assert head[0].startswith("<!-- RECONSTRUCTED")
    assert "README.md" in comment and ("illustrative" in comment.lower())


@pytest.mark.parametrize("name", sorted(p.name for p in FIX.glob("*.pdf")))
def test_every_pdf_fixture_is_marked_illustrative(name):
    text = ow.pdf_text(fx(name))
    assert "ILLUSTRATIVE TEST FIXTURE - NOT A REAL DOCUMENT" in "\n".join(text.splitlines()[:4])


def test_build_fixtures_reproduces_the_committed_pdfs(tmp_path):
    pytest.importorskip("fpdf")
    spec = importlib.util.spec_from_file_location("ow_build_fixtures", FIX / "build_fixtures.py")
    bf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bf)
    bf.HERE = tmp_path
    built = {"ear_91-26_producto.pdf": bf.EAR_91, "ear_90-26_producto.pdf": bf.EAR_90,
             "dgft_notif_91_2026-27.pdf": bf.DGFT_91, "dgft_notif_93_2025-26.pdf": bf.DGFT_93,
             "dgft_notif_94_2026-27.pdf": bf.DGFT_94}
    assert set(built) == {p.name for p in FIX.glob("*.pdf")}
    for name, lines in built.items():
        bf.write_pdf(name, lines)
        assert (tmp_path / name).read_bytes() == fx(name), f"{name} differs from build_fixtures.py"


# ===========================================================================
# Keyword filters in the local language
# ===========================================================================


@pytest.mark.parametrize("text,labels", [
    ("Exportações de mel natural crescem", ["mel"]),
    ("MÉIS de abelhas sem ferrão", ["mel"]),
    ("Produtos APÍCOLAS destinados à exportação", ["apícola"]),
    ("Programa de boas práticas na apicultura", ["apicultura"]),
    ("O programa orienta apicultores", ["apicultor"]),
    ("Exportação de mel (NCM 0409.00.00)", ["mel", "NCM 0409"]),
    ("Fim da lua de mel no mercado de café", []),           # idiom: honeymoon
    ("A melhoria da produtividade compensa", []),
    ("Registro do estabelecimento de João Melo Ltda.", []),
    ("Doce de caramelo e melado", []),
])
def test_honey_keywords_portuguese(text, labels):
    assert ow.HONEY_PT.matches(text) == labels


@pytest.mark.parametrize("text,labels", [
    ("Nuevo embarque de miel a granel", ["miel"]),
    ("Exportaciones de MIELES diferenciadas", ["miel"]),
    ("Controles en productos apícolas", ["apícola"]),
    ("Registro Nacional de Productores Apícolas y apicultores", ["apícola", "apicultor"]),
    ("Plan de apicultura", ["apicultura"]),
    ("posición arancelaria 0409", ["NCM 0409"]),
    ("NCM 0409.00.00", ["NCM 0409"]),
    ("Fin de la luna de miel para los precios del maíz", []),
    ("Ensayo sobre mielina y mieloma", []),
    ("Miller y Cía. S.A.", []),
])
def test_honey_keywords_spanish(text, labels):
    assert ow.HONEY_ES.matches(text) == labels


@pytest.mark.parametrize("text,labels", [
    ("Extension of Minimum Export Price (MEP) on export of Natural Honey", ["honey"]),
    ("Amendment in export policy under ITC (HS) Code 04090000", ["ITC-HS 0409"]),
    ("Export policy of goods under HS 0409", ["ITC-HS 0409"]),
    ("Import policy of live honey bees (Apis mellifera)", []),
    ("Honey-bee colonies for pollination", []),
    ("Honeybee health programme", []),
    ("Honeydew melons: export policy", []),
    ("Amendment in import policy of Almonds under ITC (HS) Code 0802", []),
])
def test_honey_keywords_english(text, labels):
    assert ow.HONEY_EN.matches(text) == labels


def test_keyword_matching_spans_several_texts_and_ignores_none():
    assert ow.HONEY_PT.matches("Título sem palavra-chave", None, "Seção: Apicultura") == ["apicultura"]
    assert ow.HONEY_ES.matches(None, "", None) == []


@pytest.mark.parametrize("text,lang,expected", [
    ("Publicado em 29/10/2026 10h05", "pt", date(2026, 10, 29)),
    ("3 de novembro de 2026", "pt", date(2026, 11, 3)),
    ("1º de março de 2027", "pt", date(2027, 3, 1)),
    ("Martes 03 de noviembre de 2026", "es", date(2026, 11, 3)),
    ("2026-11-02T15:20:00-03:00", "es", date(2026, 11, 2)),   # regression: ISO timestamps were not read
    ("publicado 2026-11-02", "pt", date(2026, 11, 2)),
    ("ref. 12026-11-02", "pt", None),
    ("Dated: 28th October, 2026", "en", date(2026, 10, 28)),
    ("extended till 30.06.2027", "en", date(2027, 6, 30)),
    ("June 30, 2027", "en", date(2027, 6, 30)),
    ("31/02/2026", "pt", None),                              # impossible date: not guessed
    ("Safra 2026/27", "pt", None),
    ("", "en", None),
])
def test_parse_local_date(text, lang, expected):
    assert ow.parse_local_date(text, lang) == expected


def test_find_dates_returns_every_date_in_order():
    found = ow.find_dates("valid up to 31.03.2026 with effect from 01.12.2025", "en")
    assert [d for _, d in found] == [date(2026, 3, 31), date(2025, 12, 1)]


def test_topics_and_doc_type_rules():
    assert ow.topics_of("Brasil apresenta à União Europeia plano para reinclusão na lista", "pt") == ["eu_listing"]
    assert ow.topics_of("Resultados do PNCRC: resíduos em mel", "pt") == ["residues"]
    assert ow.topics_of("Certificación dentro del cupo arancelario", "es") == ["export"]
    assert ow.topics_of("Lista EAR: oxitetraciclina en miel", "es") == ["residues"]
    assert "mep" in ow.topics_of("Minimum Export Price (MEP) on Natural Honey", "en")
    assert ow.doc_type_for(["mep", "export", "residues"], normative=True) == "price_floor"
    assert ow.doc_type_for(["eu_listing", "residues"], normative=False) == "export_rule"
    assert ow.doc_type_for(["residues", "export"], normative=False) == "residue_alert"
    assert ow.doc_type_for(["export"], normative=False) == "export_rule"
    assert ow.doc_type_for([], normative=True) == "regulation"
    assert ow.doc_type_for([], normative=False) == "notice"


def test_eu_listing_candidate_needs_the_eu_and_a_listing_word():
    assert ow.is_eu_listing_pt("União Europeia atualiza lista de estabelecimentos")
    assert ow.is_eu_listing_pt("Missão ao bloco europeu", "respostas sobre antimicrobianos")
    assert not ow.is_eu_listing_pt("União Europeia e Mercosul assinam acordo")
    assert not ow.is_eu_listing_pt("Lista de preços da soja")


def test_canonical_url_and_url_reference():
    base = "https://www.gov.br/agricultura/pt-br/assuntos/noticias"
    assert ow.canonical_url("/agricultura/pt-br/assuntos/noticias/x-y/view#top", base) == base + "/x-y"
    assert ow.canonical_url("http://WWW.GOV.BR/a/?utm_source=t&id=3&fbclid=z", base) == "https://www.gov.br/a?id=3"
    for bad in ("javascript:void(0)", "mailto:a@b.c", "#anchor", "", None, "ftp://host/x"):
        assert ow.canonical_url(bad, base) is None
    assert ow.url_reference("mapa", base + "/abc") == "mapa:/agricultura/pt-br/assuntos/noticias/abc"
    long_ref = ow.url_reference("mapa", base + "/" + "x" * 400)
    assert len(long_ref) <= 200 and long_ref.startswith("mapa:/agricultura/")
    assert long_ref == ow.url_reference("mapa", base + "/" + "x" * 400)          # stable


# ===========================================================================
# Brazil: MAPA news listing and articles
# ===========================================================================


def _mapa_page(name: str, url: str = ow.MAPA_NEWS_URL) -> ow.ListingPage:
    return ow.parse_listing(fx(name), url, item_url_re=ow.MAPA_ITEM_RE, lang="pt", label="MAPA news")


def test_mapa_listing_page_one():
    page = _mapa_page("mapa_noticias_p1.html")
    by = {i.url.rsplit("/", 1)[-1]: i for i in page.items}
    assert list(by) == [ART_EXPORTACOES, ART_LISTA_UE, ART_PESCADO, "safra-de-soja-deve-atingir-novo-recorde-ilustrativo",
                        "fim-da-lua-de-mel-no-mercado-de-cafe-ilustrativo", ART_PNCRC]
    assert "campanha-de-vacinacao-de-rebanhos-ilustrativo" not in by        # "Mais lidas", outside #content-core
    first = by[ART_EXPORTACOES]
    assert first.title == "Exportações de mel natural crescem no terceiro trimestre (ilustrativo)"
    assert first.published_at == date(2026, 11, 3)
    assert first.section == "Mercado externo"
    assert first.description.startswith("Texto ilustrativo de teste: os embarques de mel")   # leading date stripped
    assert by[ART_PNCRC].published_at == date(2026, 10, 30)
    assert page.next_url == "https://www.gov.br/agricultura/pt-br/assuntos/noticias?b_start:int=30"
    assert page.problems == []


def test_mapa_listing_page_two_canonical_view_url_and_undated_item():
    page = _mapa_page("mapa_noticias_p2.html", ow.MAPA_NEWS_URL + "?b_start:int=30")
    urls = [i.url for i in page.items]
    assert MAPA_ART + ART_APICULTURA in urls                          # ".../view" suffix dropped
    assert all(not u.endswith("/view") for u in urls)
    undated = next(i for i in page.items if i.url.endswith(ART_APICULTURA))
    assert undated.published_at is None and undated.section == "Apicultura"
    assert page.next_url is None                                      # "« Anterior" points back, not forward


def test_mapa_listing_drift_raises_and_names_the_url():
    with pytest.raises(ow.SchemaDrift) as e:
        _mapa_page("mapa_noticias_drift.html")
    assert ow.MAPA_NEWS_URL in str(e.value) and "layout" in str(e.value)


def test_listing_without_any_date_is_drift():
    undated = re.sub(r'<span class="data">[^<]*</span>\s*-\s*', "", fx_text("mapa_noticias_p1.html"))
    page = ow.parse_listing(undated, ow.MAPA_NEWS_URL, item_url_re=ow.MAPA_ITEM_RE, lang="pt", label="MAPA news")
    assert len(page.items) >= 3 and not any(i.published_at for i in page.items)
    with pytest.raises(ow.SchemaDrift, match="readable date"):
        ow.check_listing_dates(page, "MAPA news")


def test_listing_items_only_outside_main_area_are_reported():
    html = ("<html><body><main><a href='/agricultura/pt-br'>Início</a></main><div id='lista'>"
            "<a href='https://www.gov.br/agricultura/pt-br/assuntos/noticias/mel-exportado-ilustrativo'>"
            "Mel exportado em outubro (ilustrativo)</a> <span class='data'>02/11/2026</span></div></body></html>")
    page = ow.parse_listing(html, ow.MAPA_NEWS_URL, item_url_re=ow.MAPA_ITEM_RE, lang="pt", label="MAPA news")
    assert [i.published_at for i in page.items] == [date(2026, 11, 2)]
    assert any("outside the main content area" in p for p in page.problems)


def test_mapa_articles():
    ue = ow.parse_article(fx("mapa_noticia_lista_ue.html"), "pt")
    assert ue.published_at == date(2026, 11, 2)                        # article:published_time
    assert ue.description.startswith("Texto ilustrativo de teste: missão técnica")
    assert ow.HONEY_PT.matches(ue.text) == ["mel"]
    assert "Notícias" not in ue.text                                   # header navigation dropped
    api = ow.parse_article(fx("mapa_noticia_apicultura.html"), "pt")
    assert api.published_at == date(2026, 10, 29)                      # "Publicado em", not "Atualizado em"
    fish = ow.parse_article(fx("mapa_noticia_lista_ue_pescado.html"), "pt")
    assert ow.HONEY_PT.matches(fish.text) == []


# ===========================================================================
# Brazil: Diário Oficial da União search
# ===========================================================================


def test_dou_search_results():
    acts, problems = ow.parse_dou_search(fx("dou_busca_mel.html"))
    assert problems == []
    by = {a.url_title: a for a in acts}
    portaria = by[DOU_PORTARIA]
    assert portaria.title == "PORTARIA SDA/MAPA Nº 9.901, DE 30 DE OUTUBRO DE 2026 (ilustrativa)"
    assert portaria.published_at == date(2026, 11, 3) and portaria.art_type == "Portaria"
    assert portaria.url == "https://www.in.gov.br/web/dou/-/" + DOU_PORTARIA
    assert "<span" not in portaria.excerpt and "exportação de mel e produtos apícolas" in portaria.excerpt
    assert portaria.is_mapa and (portaria.edition, portaria.page, portaria.section) == ("210", "12", "DO1")
    despacho = by["despacho-n-9.902-de-29-de-outubro-de-2026-ilustrativo-999000002"]
    assert ow.HONEY_PT.matches(despacho.title, despacho.excerpt) == []          # "Melo" is a name
    anvisa = by["resolucao-re-n-9.903-de-28-de-outubro-de-2026-ilustrativa-999000003"]
    assert ow.HONEY_PT.matches(anvisa.title, anvisa.excerpt) == ["mel"] and not anvisa.is_mapa


def test_dou_empty_result_is_valid():
    assert ow.parse_dou_search(fx("dou_busca_apicultura.html")) == ([], [])


def test_dou_drift_raises_and_names_the_url():
    url = "https://www.in.gov.br/consulta/-/buscar/dou?q=%22mel%22&s=do1"
    with pytest.raises(ow.SchemaDrift) as e:
        ow.parse_dou_search(fx("dou_busca_drift.html"), url)
    assert url in str(e.value) and ow.DOU_SCRIPT_ID in str(e.value)


@pytest.mark.parametrize("payload,match", [
    ("not json", "not JSON"),
    ('{"items": []}', "jsonArray"),
    ('{"jsonArray": [{"foo": 1}, {"title": "x"}]}', "none of the 2 results"),
])
def test_dou_malformed_results_are_drift(payload, match):
    html = f'<html><script id="{ow.DOU_SCRIPT_ID}" type="application/json">{payload}</script></html>'.encode()
    with pytest.raises(ow.SchemaDrift, match=match):
        ow.parse_dou_search(html)


def test_dou_bad_rows_are_skipped_with_a_problem():
    rows = ('{"jsonArray": [{"urlTitle": "../etc", "title": "X"}, {"urlTitle": "portaria-1", "title": "PORTARIA 1",'
            ' "pubDate": "ontem", "hierarchyList": ["Ministério da Agricultura e Pecuária"]}]}')
    html = f'<html><script id="{ow.DOU_SCRIPT_ID}">{rows}</script></html>'.encode()
    acts, problems = ow.parse_dou_search(html)
    assert [a.url_title for a in acts] == ["portaria-1"] and acts[0].published_at is None and acts[0].is_mapa
    assert len(problems) == 2 and "not a date" in problems[1]


def test_dou_window():
    assert ow.dou_window(None, TODAY) == "ano"
    assert ow.dou_window("2026-11-03", TODAY) == "semana"
    assert ow.dou_window("2026-10-20", TODAY) == "mes"
    assert ow.dou_window("2026-08-01", TODAY) == "ano"
    assert ow.dou_window("2026-11-03", TODAY, force=True) == "ano"


# ===========================================================================
# Argentina: SENASA news, Plan CREHA "Lista EAR", Boletín Oficial
# ===========================================================================


def test_senasa_listing():
    page = ow.parse_listing(fx("senasa_noticias.html"), ow.SENASA_NEWS_URL, item_url_re=ow.SENASA_ITEM_RE, lang="es",
                            label="SENASA news")
    assert len(page.items) == 5 and page.problems == [] and page.next_url is None
    first = page.items[0]
    assert first.url == "https://www.argentina.gob.ar/noticias/el-senasa-certifico-un-nuevo-embarque-de-miel-a-granel-ilustrativo"
    assert first.published_at == date(2026, 11, 3)                     # <time datetime>
    assert first.title.startswith("El SENASA certificó un nuevo embarque de miel a granel")
    assert first.description.startswith("Texto ilustrativo de prueba: el embarque se certificó")
    honey = [i.url.rsplit("/", 1)[-1] for i in page.items if ow.HONEY_ES.matches(i.title, i.description, i.section)]
    assert honey == ["el-senasa-certifico-un-nuevo-embarque-de-miel-a-granel-ilustrativo",
                     "se-autorizaron-nuevos-barnices-libres-de-bisfenol-ilustrativo",
                     "resultados-del-plan-creha-en-productos-apicolas-ilustrativo"]      # "luna de miel" is not honey


def test_creha_ear_links():
    links, pdfs = ow.find_ear_links(fx("senasa_creha.html"), ow.SENASA_CREHA_URL)
    assert pdfs == 4                                                   # two plan/summary PDFs are not EAR lists
    assert [(lk.number, lk.year, lk.listed_date, lk.reference) for lk in links] == [
        (91, 2026, date(2026, 10, 15), "SENASA Lista EAR 2026 N°91"),
        (90, 2026, date(2026, 9, 10), "SENASA Lista EAR 2026 N°90"),
    ]
    assert links[0].url == EAR_FILES + "ear_91-26_producto.pdf"
    assert links[0].title == "Lista EAR Año 2026 N°91 - por producto"


def test_ear_link_number_from_text_when_the_file_name_is_opaque():
    html = '<ul><li><a href="/sites/default/files/documento-final.pdf">Lista EAR Año 2027 N° 3</a></li></ul>'
    (link,), pdfs = ow.find_ear_links(html, ow.SENASA_CREHA_URL)
    assert (link.number, link.year, link.reference, pdfs) == (3, 2027, "SENASA Lista EAR 2027 N°03", 1)


def test_ear_pdfs():
    ear91 = ow.parse_ear_pdf(fx("ear_91-26_producto.pdf"))
    assert ear91.text_ok and ear91.list_date == date(2026, 10, 15)
    assert ear91.honey_rows == [
        "Miel | Oxitetraciclina | 18 µg/kg | No permitido | 02/09/2026 | RENAPA 99-000001",
        "Miel | Fenol | 25 µg/kg | 10 µg/kg | 09/09/2026 | RENAPA 99-000002",
    ]
    ear90 = ow.parse_ear_pdf(fx("ear_90-26_producto.pdf"))
    assert ear90.text_ok and ear90.honey_rows == [] and ear90.list_date == date(2026, 9, 10)
    assert ow.parse_ear_pdf(b"<html>error</html>") == ow.EarPdf(text_ok=False, honey_rows=[], list_date=None)


def test_boletin_section_page():
    avisos = {a.aviso_id: a for a in ow.parse_bo_section(fx("bo_primera.html"))}
    assert list(avisos) == ["999101", "999102", "999103", "999104"]
    sagyp = avisos["999101"]
    assert sagyp.pub_date == date(2026, 11, 4) and sagyp.rubro == "Resoluciones"
    assert sagyp.organism == "MINISTERIO DE ECONOMÍA. SECRETARÍA DE AGRICULTURA, GANADERÍA Y PESCA"
    assert (sagyp.norm, sagyp.gde) == ("Resolución 991/2026", "RESOL-2026-991-APN-SAGYP#MEC")
    assert sagyp.url == BO + "/detalleAviso/primera/999101/20261104"
    assert sagyp.title == "MINISTERIO DE ECONOMÍA. SECRETARÍA DE AGRICULTURA, GANADERÍA Y PESCA — Resolución 991/2026"
    assert avisos["999104"].rubro == "Avisos Oficiales" and avisos["999104"].gde is None
    assert ow.BoAviso.from_state(sagyp.to_state()) == sagyp
    assert ow.BoAviso.from_state({"id": "x"}) is None and ow.BoAviso.from_state("junk") is None


def test_boletin_drift_raises_and_names_the_url():
    with pytest.raises(ow.SchemaDrift) as e:
        ow.parse_bo_section(fx("bo_primera_drift.html"), url=BO + "/seccion/primera")
    assert BO + "/seccion/primera" in str(e.value) and "detalleAviso" in str(e.value)
    assert ow.parse_bo_section(fx("bo_primera_drift.html"), require=False) == []


def test_boletin_notice_pages():
    text, in_container = ow.parse_bo_detail(fx("bo_aviso_999101.html"))
    assert in_container and text.startswith("RESOL-2026-991-APN-SAGYP#MEC")
    assert "Boletín Oficial Primera sección" not in text                  # navigation not in the body
    assert ow.HONEY_ES.matches(text) == ["miel", "NCM 0409"]
    assert ow.HONEY_ES.matches(ow.parse_bo_detail(fx("bo_aviso_999102.html"))[0]) == []
    text, in_container = ow.parse_bo_detail(b"<html><body><main><p>" + b"Texto sobre miel. " * 10 + b"</p></main></body></html>")
    assert not in_container and "miel" in text


def test_boletin_catchup_days():
    assert ow.bo_catchup_days(None, TODAY) == []                       # first run: no back-fill
    assert ow.bo_catchup_days(TODAY, TODAY) == []
    assert ow.bo_catchup_days(date(2026, 10, 30), TODAY) == [date(2026, 11, 2), date(2026, 11, 3)]   # weekend skipped
    assert ow.BO_CATCHUP_DAYS == 5
    assert ow.bo_catchup_days(date(2026, 10, 1), TODAY) == [                # only the most recent 5 business days
        date(2026, 10, 28), date(2026, 10, 29), date(2026, 10, 30), date(2026, 11, 2), date(2026, 11, 3)]


# ===========================================================================
# India: DGFT notifications and minimum export price
# ===========================================================================


def test_dgft_notifications_table():
    rows, problems = ow.parse_dgft_notifications(fx("dgft_notifications.html"), ow.DGFT_LIST_URL)
    assert problems == []
    assert [(r.number, r.notified_on, r.year) for r in rows] == [
        ("94/2026-27", date(2026, 11, 2), "2026-27"), ("91/2026-27", date(2026, 10, 28), "2026-27"),
        ("90/2026-27", date(2026, 10, 20), "2026-27"), ("89/2026-27", date(2026, 10, 15), "2026-27"),
        ("88/2026-27", date(2026, 10, 10), "2026-27"), ("93/2025-26", date(2025, 11, 28), "2025-26"),
    ]
    assert rows[1].pdf_url == DGFT_PDF.format(n=91)
    assert rows[1].description == "Extension of Minimum Export Price (MEP) on export of Natural Honey (illustrative)"
    # honey only: not the almonds, not the onion MEP, not live honey bees
    assert [r.number for r in rows if ow.dgft_is_honey(r)] == ["94/2026-27", "91/2026-27", "93/2025-26"]


def test_dgft_table_without_header_is_read_by_content():
    html = ("<table><tr><td>1</td><td>No. 7/2026-27</td><td>Minimum Export Price on Natural Honey (illustrative)</td>"
            "<td>05/05/2026</td><td><a href='/files/n7.pdf'>PDF</a></td></tr></table>")
    (row,), problems = ow.parse_dgft_notifications(html, ow.DGFT_LIST_URL)
    assert (row.number, row.notified_on, row.pdf_url, problems) == (
        "07/2026-27", date(2026, 5, 5), "https://www.dgft.gov.in/files/n7.pdf", [])
    assert row.description.startswith("Minimum Export Price") and ow.dgft_is_honey(row)


def test_dgft_drift_raises():
    with pytest.raises(ow.SchemaDrift) as e:
        ow.parse_dgft_notifications(fx("dgft_notifications_drift.html"), ow.DGFT_LIST_URL)
    assert ow.DGFT_LIST_URL in str(e.value)
    undated = re.sub(r"<td>\d\d/\d\d/\d{4}</td>", "<td>-</td>", fx_text("dgft_notifications.html"))
    with pytest.raises(ow.SchemaDrift, match="readable date"):
        ow.parse_dgft_notifications(undated, ow.DGFT_LIST_URL)
    unnumbered = re.sub(r"<td>\d\d/\d{4}-\d\d</td>", "<td>n/a</td>", fx_text("dgft_notifications.html"))
    with pytest.raises(ow.SchemaDrift, match="notification number"):
        ow.parse_dgft_notifications(unnumbered, ow.DGFT_LIST_URL)


def test_mep_extension_pdf():
    terms = ow.parse_mep_terms(ow.pdf_text(fx("dgft_notif_91_2026-27.pdf")), date(2026, 10, 28))
    assert terms.mep_usd_per_t == 1111.0 and terms.basis == "FOB"
    assert terms.valid_until == date(2027, 6, 30)                       # written twice, in two formats
    assert terms.effective_date == date(2026, 10, 28)
    assert terms.effective_basis == "with immediate effect (notification date)"
    assert terms.problems == [] and "US$ 1,111 per MT FOB" in terms.excerpt


def test_mep_revision_pdf_takes_the_new_price():
    terms = ow.parse_mep_terms(ow.pdf_text(fx("dgft_notif_93_2025-26.pdf")), date(2025, 11, 28))
    assert terms.mep_values_found == [1234.0, 1111.0]
    assert terms.mep_usd_per_t == 1111.0                               # "from US$ 1,234 ... to US$ 1,111"
    assert terms.valid_until == date(2026, 3, 31)
    assert (terms.effective_date, terms.effective_basis) == (date(2025, 12, 1), "with effect from")
    assert terms.problems == []


def test_export_policy_pdf_has_no_price():
    terms = ow.parse_mep_terms(ow.pdf_text(fx("dgft_notif_94_2026-27.pdf")), date(2026, 11, 2))
    assert terms.mep_usd_per_t is None and terms.mep_values_found == [] and terms.valid_until is None
    assert terms.effective_date == date(2026, 11, 2) and terms.basis is None


@pytest.mark.parametrize("text,mep,until,problem", [
    ("The MEP is US$ 2.5 per kg FOB.", 2500.0, None, None),                          # per kg -> per tonne
    ("MEP of USD 1500/MT and US$ 1700 per MT for organic honey.", None, None, "several minimum export prices"),
    ("MEP of USD 1500/MT valid till 30.06.2026 and till 31.12.2026.", 1500.0, None, "several validity dates"),
    ("MEP valid till 30.06.2026 is hereby extended up to 31.03.2027.", None, date(2027, 3, 31), None),
    ("No price is stated here.", None, None, None),
])
def test_mep_terms_only_unambiguous_values(text, mep, until, problem):
    terms = ow.parse_mep_terms(text, None)
    assert terms.mep_usd_per_t == mep and terms.valid_until == until
    if problem:
        assert any(problem in p for p in terms.problems)
    else:
        assert terms.problems == []


def test_mep_effective_date_wef_abbreviation():
    # Regression: "w.e.f." (the usual DGFT abbreviation of "with effect from") was not recognised.
    terms = ow.parse_mep_terms("The MEP of US$ 1,234 per MT shall apply w.e.f. 01.04.2027 till 30.09.2027.", None)
    assert (terms.effective_date, terms.effective_basis) == (date(2027, 4, 1), "with effect from")
    assert terms.valid_until == date(2027, 9, 30)
    assert ow.parse_mep_terms("with immediate effect", None).effective_date is None    # no notification date


# ===========================================================================
# End to end (offline, respx)
# ===========================================================================


def test_mapa_end_to_end(run_with_routes, session_factory, pin_today):
    res = run_with_routes("br_mapa_honey", mapa_routes())
    assert res["status"] == "success" and res["error"] is None and res["warnings"] == [], res
    assert res["new"] == len(MAPA_EXPECTED)
    with session_factory() as s:
        items = _items(s, "br_mapa_honey")
        assert set(items) == MAPA_EXPECTED
        for r in items.values():
            assert (r.jurisdiction, r.countries, r.summary_it, r.summary_is_ai) == ("BR", ["BRA"], None, False)
            assert r.summary_en is None                                # Portuguese is never translated
            assert r.extra["language"] == "pt" and r.extra["watcher"] == "html_page"

        exp = items[mapa_ref(ART_EXPORTACOES)]
        assert exp.url == MAPA_ART + ART_EXPORTACOES and exp.published_at == date(2026, 11, 3)
        assert exp.doc_type == "notice" and exp.extra["keywords"] == ["mel"] and exp.extra["matched_in"] == "listing"
        assert exp.extra["section"] == "Mercado externo"
        assert exp.extra["summary_original"].startswith("Texto ilustrativo de teste: os embarques de mel")

        ue = items[mapa_ref(ART_LISTA_UE)]                             # honey only in the article body
        assert ue.extra["matched_in"] == "article" and ue.extra["topics"] == ["eu_listing"]
        assert ue.doc_type == "export_rule" and ue.published_at == date(2026, 11, 2)
        assert "exportações de mel" in ue.extra["excerpt_original"]

        assert items[mapa_ref(ART_PNCRC)].doc_type == "residue_alert"
        apic = items[mapa_ref(ART_APICULTURA)]                         # undated in the listing
        assert apic.published_at == date(2026, 10, 29) and apic.extra["date_source"] == "article"

        portaria = items[f"dou:{DOU_PORTARIA}"]                        # in two DOU queries, stored once
        assert portaria.status == "published" and portaria.doc_type == "export_rule"
        assert portaria.url == "https://www.in.gov.br/web/dou/-/" + DOU_PORTARIA
        assert portaria.extra["art_type"] == "Portaria" and portaria.extra["search"] == {"q": '"mel"', "window": "ano"}
        assert portaria.extra["issuing_body"].startswith("Ministério da Agricultura e Pecuária")
        assert items[f"dou:{DOU_IN}"].doc_type == "residue_alert"

        state = _state(s, "br_mapa_honey")
        assert state["mapa_news_complete"] == state["dou_complete"] == TODAY.isoformat()
        assert list(state["mapa_news_body_checked"]) == [MAPA_ART + ART_PESCADO]
        src = _src(s, "br_mapa_honey")
        assert src.latest_published_at == date(2026, 11, 3) and src.last_run_status == "success"


def test_senasa_end_to_end(run_with_routes, session_factory, pin_today):
    res = run_with_routes("ar_senasa_honey", senasa_routes())
    assert res["status"] == "success" and res["warnings"] == [], res
    with session_factory() as s:
        items = _items(s, "ar_senasa_honey")
        assert set(items) == SENASA_EXPECTED
        for r in items.values():
            assert (r.jurisdiction, r.countries, r.summary_en, r.summary_it) == ("AR", ["ARG"], None, None)
            assert r.extra["language"] == "es"

        cert = items["senasa:/noticias/el-senasa-certifico-un-nuevo-embarque-de-miel-a-granel-ilustrativo"]
        assert cert.published_at == date(2026, 11, 3) and cert.doc_type == "export_rule"
        assert cert.extra["keywords"] == ["miel"]
        assert items["senasa:/noticias/resultados-del-plan-creha-en-productos-apicolas-ilustrativo"].doc_type == "residue_alert"

        ear = items["SENASA Lista EAR 2026 N°91"]
        assert ear.doc_type == "residue_alert" and ear.published_at == date(2026, 10, 15)
        assert ear.url == ear.extra["pdf_url"] == EAR_FILES + "ear_91-26_producto.pdf"
        assert ear.extra["honey_row_count"] == 2 and ear.extra["honey_rows"][0].startswith("Miel | Oxitetraciclina")
        assert (ear.extra["list_number"], ear.extra["list_year"], ear.extra["honey_mentioned"]) == (91, 2026, True)

        bo = items["BO-AR primera 999101"]
        assert bo.url == BO + "/detalleAviso/primera/999101/20261104" and bo.published_at == TODAY
        assert bo.status == "published" and bo.doc_type == "export_rule"
        assert (bo.extra["norm"], bo.extra["gde_number"], bo.extra["rubro"]) == (
            "Resolución 991/2026", "RESOL-2026-991-APN-SAGYP#MEC", "Resoluciones")
        assert bo.extra["keywords"] == ["miel", "NCM 0409"] and "cupo" in bo.extra["excerpt_original"]

        raw = _raw_urls(s, "ar_senasa_honey")
        assert BO + "/detalleAviso/primera/999102/20261104" in raw      # opened (agriculture body), no honey
        assert not any(x in u for u in raw for x in ("999103", "999104"))   # health/tax notices never opened
        assert EAR_FILES + "ear_90-26_producto.pdf" in raw
        assert not any("plan_creha" in u or "resumen_resultados" in u for u in raw)

        state = _state(s, "ar_senasa_honey")
        assert state["ear_files"] == {EAR_FILES + "ear_91-26_producto.pdf": "stored",
                                      EAR_FILES + "ear_90-26_producto.pdf": "no_honey"}
        assert state["bo_rejected"] == ["999102"] and state["bo_pending"] == []
        assert state["bo_last_edition"] == state["ear_checked"] == TODAY.isoformat()


def test_dgft_end_to_end_minimum_export_price(run_with_routes, session_factory, pin_today):
    res = run_with_routes("in_dgft_honey", dgft_routes())
    assert res["status"] == "success" and res["warnings"] == [] and res["new"] == 3, res
    with session_factory() as s:
        items = _items(s, "in_dgft_honey")
        assert set(items) == DGFT_EXPECTED
        for r in items.values():
            assert (r.jurisdiction, r.countries, r.status) == ("IN", ["IND"], "published")
            assert r.extra["terms_parsed"] is True and r.extra["language"] == "en"

        ext = items["DGFT Notification No. 91/2026-27"]
        assert ext.doc_type == "price_floor" and ext.url == DGFT_PDF.format(n=91)
        assert ext.title == "Extension of Minimum Export Price (MEP) on export of Natural Honey (illustrative)"
        assert ext.published_at == date(2026, 10, 28) and ext.effective_date == date(2026, 10, 28)
        assert ext.extra["mep_usd_per_t"] == 1111.0 and ext.extra["valid_until"] == "2027-06-30"
        assert (ext.extra["mep_currency"], ext.extra["mep_unit"], ext.extra["mep_basis"]) == ("USD", "t", "FOB")
        assert ext.extra["effective_basis"] == "with immediate effect (notification date)"
        assert ext.extra["raw_document_id"] and ext.extra["notification_number"] == "91/2026-27"
        assert "US$ 1,111 per MT FOB" in ext.summary_en                # official English text, verbatim

        rev = items["DGFT Notification No. 93/2025-26"]
        assert rev.doc_type == "price_floor" and rev.extra["mep_usd_per_t"] == 1111.0
        assert rev.extra["mep_values_found"] == [1234.0, 1111.0] and rev.extra["valid_until"] == "2026-03-31"
        assert rev.effective_date == date(2025, 12, 1) and rev.extra["effective_basis"] == "with effect from"

        policy = items["DGFT Notification No. 94/2026-27"]
        assert policy.doc_type == "export_rule" and policy.effective_date == date(2026, 11, 2)
        assert not {"mep_usd_per_t", "valid_until", "mep_currency"} & set(policy.extra)

        raw = _raw_urls(s, "in_dgft_honey")
        assert not any(f"fixture-{n}/" in u for u in raw for n in (88, 89, 90))     # non-honey PDFs never fetched
        assert _src(s, "in_dgft_honey").latest_published_at == date(2026, 11, 2)


def test_all_watchers_use_iso2_jurisdiction_and_origin_iso3(run_with_routes, session_factory, pin_today):
    for key in KEYS:
        run_with_routes(key, ROUTES[key]())
    iso2 = {c["iso3"]: c["iso2"] for c in reference_countries()}
    with session_factory() as s:
        rows = list(s.scalars(select(RegulationItem)))
    assert len(rows) == sum(len(v) for v in EXPECTED.values())
    for r in rows:
        assert re.fullmatch(r"[A-Z]{2}", r.jurisdiction)              # same style as "EU", "US"
        assert len(r.countries) == 1 and r.jurisdiction == iso2[r.countries[0]]
    assert {r.jurisdiction for r in rows} == {"BR", "AR", "IN"}


def test_watcher_rows_through_the_regulations_api(api, run_with_routes, pin_today):
    for key in KEYS:
        run_with_routes(key, ROUTES[key]())
    d = api.get("/api/regulations", params={"jurisdiction": "br,ar,in", "page_size": 100}).json()
    assert d["total"] == sum(len(v) for v in EXPECTED.values())
    for it in d["items"]:
        assert it["reliability"] == "official" and it["source"]["key"] in KEYS
        assert it["summary_is_ai"] is False and it["data_status"] == "published"
    facets = {f["key"] for f in d["facets"]["jurisdictions"]}
    assert {"BR", "AR", "IN"} <= facets
    india = api.get("/api/regulations", params={"country": "IND"}).json()
    assert {i["reference"] for i in india["items"]} == DGFT_EXPECTED
    mep = next(i for i in india["items"] if i["reference"] == "DGFT Notification No. 91/2026-27")
    assert mep["doc_type"] == "price_floor" and mep["effective_date"] == "2026-10-28"


# ---------------------------------------------------------------------------
# Idempotence and de-duplication
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key,second_routes", [
    ("br_mapa_honey", lambda: mapa_routes(articles=False)),     # articles must not be opened again
    ("ar_senasa_honey", lambda: senasa_routes(details=False)),  # nor the CREHA page (weekly), PDFs or notices
    ("in_dgft_honey", lambda: dgft_routes(pdfs=False)),         # nor the notification PDFs
])
def test_second_run_is_idempotent_and_fetches_only_listings(key, second_routes, run_with_routes, session_factory,
                                                            pin_today):
    first = run_with_routes(key, ROUTES[key]())
    assert first["status"] == "success", first
    with session_factory() as s:
        before = {ref: (r.id, r.collected_at) for ref, r in _items(s, key).items()}
    second = run_with_routes(key, second_routes())
    assert second["status"] == "no_change" and second["new"] == 0 and second["error"] is None, second
    assert second["warnings"] == []
    with session_factory() as s:
        after = {ref: (r.id, r.collected_at) for ref, r in _items(s, key).items()}
    assert after == before and set(after) == EXPECTED[key]


def test_forced_run_reparses_but_adds_nothing(run_with_routes, session_factory, pin_today):
    for key in KEYS:
        run_with_routes(key, ROUTES[key]())
        forced = run_with_routes(key, ROUTES[key](), force=True)
        assert forced["new"] == 0 and forced["status"] == "no_change", forced
    with session_factory() as s:
        assert len(list(s.scalars(select(RegulationItem)))) == sum(len(v) for v in EXPECTED.values())


def test_same_item_on_two_listing_pages_is_stored_once(run_with_routes, session_factory, pin_today):
    assert ART_EXPORTACOES.encode() in fx("mapa_noticias_p1.html") and ART_EXPORTACOES.encode() in fx("mapa_noticias_p2.html")
    run_with_routes("br_mapa_honey", mapa_routes())
    with session_factory() as s:
        refs = [r for r in _items(s, "br_mapa_honey") if ART_EXPORTACOES in r]
        urls = [r.url for r in _items(s, "br_mapa_honey").values()]
    assert refs == [mapa_ref(ART_EXPORTACOES)]
    assert len(urls) == len(set(urls)) and not any(u.endswith("/view") for u in urls)


def test_two_renderings_of_one_ear_list_are_stored_once(run_with_routes, session_factory, pin_today):
    creha = fx_text("senasa_creha.html").replace(
        "</ul>\n  </div>",
        '<li><a href="/sites/default/files/ear_91-26_establecimiento.pdf">Lista EAR Año 2026 N°91 - por '
        'establecimiento</a> (15/10/2026)</li></ul>\n  </div>')
    assert "establecimiento.pdf" in creha
    res = run_with_routes("ar_senasa_honey", senasa_routes({ow.SENASA_CREHA_URL: creha.encode()}))
    assert res["status"] == "success", res                         # the second rendering is never downloaded
    with session_factory() as s:
        ears = [r for r in _items(s, "ar_senasa_honey") if r.startswith("SENASA Lista EAR")]
        assert ears == ["SENASA Lista EAR 2026 N°91"]
        assert not any("establecimiento" in u for u in _raw_urls(s, "ar_senasa_honey"))


def test_dgft_row_listed_twice_is_stored_once(run_with_routes, session_factory, pin_today):
    html = fx_text("dgft_notifications.html")
    row = re.search(r"<tr><td>2</td>.*?</tr>", html).group(0)
    res = run_with_routes("in_dgft_honey", dgft_routes({ow.DGFT_LIST_URL: html.replace(row, row + row).encode()}))
    assert res["new"] == 3 and res["status"] == "success", res
    with session_factory() as s:
        assert set(_items(s, "in_dgft_honey")) == DGFT_EXPECTED


def test_ear_list_rechecked_weekly(run_with_routes, session_factory, pin_today):
    run_with_routes("ar_senasa_honey", senasa_routes())
    pin_today(TODAY + timedelta(days=ow.EAR_CHECK_DAYS))
    # The CREHA page is read again; the known list and the no-honey list are not downloaded again.
    res = run_with_routes("ar_senasa_honey", senasa_routes({
        EAR_FILES + "ear_91-26_producto.pdf": (500, b""), EAR_FILES + "ear_90-26_producto.pdf": (500, b"")}))
    assert res["status"] == "no_change" and res["warnings"] == [], res
    with session_factory() as s:
        assert _state(s, "ar_senasa_honey")["ear_checked"] == (TODAY + timedelta(days=ow.EAR_CHECK_DAYS)).isoformat()


def test_dou_window_narrows_after_a_complete_run(run_with_routes, session_factory, pin_today):
    run_with_routes("br_mapa_honey", mapa_routes())
    pin_today(TODAY + timedelta(days=1))
    weekly = {q + ".*exactDate=semana": v for q, v in mapa_routes().items() if q.startswith(DOU)}
    other = {q: v for q, v in mapa_routes().items() if not q.startswith(DOU)}
    res = run_with_routes("br_mapa_honey", {**weekly, **other})  # an "ano" request would find no route: offline
    assert res["status"] == "no_change", res


# ---------------------------------------------------------------------------
# Boletín Oficial catch-up and backlog
# ---------------------------------------------------------------------------


def test_boletin_catches_up_missed_editions(run_with_routes, session_factory, pin_today):
    _seed_state(session_factory, "ar_senasa_honey", {"bo_last_edition": "2026-10-30", "ear_checked": TODAY.isoformat()})
    res = run_with_routes("ar_senasa_honey", senasa_routes())
    assert res["status"] == "success" and res["warnings"] == [], res        # 03/11 answered 404: one holiday is normal
    with session_factory() as s:
        items = _items(s, "ar_senasa_honey")
        missed = items["BO-AR primera 999090"]
        assert missed.published_at == date(2026, 11, 2) and missed.doc_type == "residue_alert"
        assert missed.url == BO + "/detalleAviso/primera/999090/20261102"
        assert "SENASA Lista EAR 2026 N°91" not in items                    # EAR checked "today": not due
        assert not any("999091" in u for u in _raw_urls(s, "ar_senasa_honey"))   # transport ministry not opened
        assert _state(s, "ar_senasa_honey")["bo_last_edition"] == TODAY.isoformat()


def test_boletin_warns_when_no_missed_edition_can_be_read(run_with_routes, session_factory, pin_today):
    _seed_state(session_factory, "ar_senasa_honey", {"bo_last_edition": "2026-10-30", "ear_checked": TODAY.isoformat()})
    res = run_with_routes("ar_senasa_honey", senasa_routes({BO + "/seccion/primera/20261102": (404, b"")}))
    assert res["status"] == "partial", res
    assert any("none of the 2 missed editions" in w and "unverified" in w for w in res["warnings"])


def test_boletin_backlog_is_kept_in_state(run_with_routes, session_factory, pin_today, monkeypatch):
    monkeypatch.setattr(ow, "BO_MAX_DETAILS", 1)
    run_with_routes("ar_senasa_honey", senasa_routes())
    with session_factory() as s:
        state = _state(s, "ar_senasa_honey")
        assert [p["id"] for p in state["bo_pending"]] == ["999102"] and state["bo_rejected"] == []
    res = run_with_routes("ar_senasa_honey", senasa_routes())
    assert res["status"] == "no_change", res
    with session_factory() as s:
        state = _state(s, "ar_senasa_honey")
        assert state["bo_pending"] == [] and state["bo_rejected"] == ["999102"]


def test_boletin_unreadable_notice_is_retried_then_dropped(run_with_routes, session_factory, pin_today):
    broken = senasa_routes({BO + "/detalleAviso/primera/999101/20261104": (500, b"")})
    for attempt in range(1, ow.MAX_PDF_ATTEMPTS + 1):
        res = run_with_routes("ar_senasa_honey", broken)
        assert res["status"] == "partial" and any("999101" in w for w in res["warnings"]), res
        with session_factory() as s:
            pending = _state(s, "ar_senasa_honey")["bo_pending"]
            assert [(p["id"], p["attempts"]) for p in pending] == ([("999101", attempt)] if attempt < ow.MAX_PDF_ATTEMPTS else [])
    with session_factory() as s:
        assert "BO-AR primera 999101" not in _items(s, "ar_senasa_honey")


# ---------------------------------------------------------------------------
# Lista EAR and article problems
# ---------------------------------------------------------------------------


def test_scanned_ear_list_is_stored_unchecked_with_a_note(run_with_routes, session_factory, pin_today):
    res = run_with_routes("ar_senasa_honey", senasa_routes({
        EAR_FILES + "ear_91-26_producto.pdf": (200, b"%PDF-1.4\n%scan\n%%EOF", PDF)}))
    assert res["status"] == "partial" and any("no text could be read" in w for w in res["warnings"]), res
    with session_factory() as s:
        ear = _items(s, "ar_senasa_honey")["SENASA Lista EAR 2026 N°91"]
        assert ear.published_at == date(2026, 10, 15)                    # the date listed on the CREHA page
        assert "honey_mentioned" not in ear.extra and "honey_rows" not in ear.extra   # nothing claimed
        assert ear.extra["note"] == "PDF text could not be read; open the official list"


def test_ear_list_that_cannot_be_downloaded_is_retried(run_with_routes, session_factory, pin_today):
    res = run_with_routes("ar_senasa_honey", senasa_routes({EAR_FILES + "ear_91-26_producto.pdf": (500, b"")}))
    assert res["status"] == "partial" and any("retried next run" in w for w in res["warnings"]), res
    with session_factory() as s:
        assert "SENASA Lista EAR 2026 N°91" not in _items(s, "ar_senasa_honey")
        assert "ear_checked" not in _state(s, "ar_senasa_honey")          # not marked done for the week
    run_with_routes("ar_senasa_honey", senasa_routes())
    with session_factory() as s:
        assert "SENASA Lista EAR 2026 N°91" in _items(s, "ar_senasa_honey")


def test_eu_listing_article_that_cannot_be_read_is_retried(run_with_routes, session_factory, pin_today):
    res = run_with_routes("br_mapa_honey", mapa_routes({MAPA_ART + ART_LISTA_UE: (404, b"")}))
    assert res["status"] == "partial" and any(ART_LISTA_UE in w for w in res["warnings"]), res
    with session_factory() as s:
        assert mapa_ref(ART_LISTA_UE) not in _items(s, "br_mapa_honey")
        assert MAPA_ART + ART_LISTA_UE not in _state(s, "br_mapa_honey")["mapa_news_body_checked"]
    run_with_routes("br_mapa_honey", mapa_routes())
    with session_factory() as s:
        assert _items(s, "br_mapa_honey")[mapa_ref(ART_LISTA_UE)].extra["matched_in"] == "article"


# ---------------------------------------------------------------------------
# DGFT PDF problems
# ---------------------------------------------------------------------------


def test_dgft_pdf_that_is_not_a_pdf_is_retried_then_stored_without_terms(run_with_routes, session_factory, pin_today):
    ref = "DGFT Notification No. 91/2026-27"
    routes = dgft_routes({DGFT_PDF.format(n=91): (200, b"<html><body>Service unavailable</body></html>", "text/html")})
    for attempt in range(1, ow.MAX_PDF_ATTEMPTS):
        res = run_with_routes("in_dgft_honey", routes)
        assert res["status"] == "partial" and any(f"retried next run ({attempt}/" in w for w in res["warnings"]), res
        with session_factory() as s:
            assert ref not in _items(s, "in_dgft_honey")
            assert _state(s, "in_dgft_honey")["pdf_attempts"] == {ref: attempt}
    res = run_with_routes("in_dgft_honey", routes)
    assert any("stored without its terms" in w for w in res["warnings"]), res
    with session_factory() as s:
        r = _items(s, "in_dgft_honey")[ref]
        assert r.doc_type == "price_floor"                               # the official title names the MEP
        assert r.extra["terms_parsed"] is False and r.extra["pdf_error"].startswith("not a PDF")
        assert "mep_usd_per_t" not in r.extra and "valid_until" not in r.extra and r.effective_date is None
        assert _state(s, "in_dgft_honey")["pdf_attempts"] == {}


@pytest.mark.parametrize("tesseract,warning", [
    (None, "OCR is not installed (install Tesseract"),
    ("/usr/bin/tesseract", "scanned PDF, OCR failed"),
])
def test_dgft_scanned_pdf_is_stored_without_terms(run_with_routes, session_factory, pin_today, monkeypatch,
                                                  tesseract, warning):
    monkeypatch.setattr(ow.ocr, "available", lambda: tesseract)
    res = run_with_routes("in_dgft_honey", dgft_routes({DGFT_PDF.format(n=91): (200, b"%PDF-1.4\n%damaged\n%%EOF", PDF)}))
    assert res["status"] == "partial" and any(warning in w and "MEP terms not read" in w
                                              for w in res["warnings"]), res
    with session_factory() as s:
        r = _items(s, "in_dgft_honey")["DGFT Notification No. 91/2026-27"]
        assert r.extra["terms_parsed"] is False and "mep_usd_per_t" not in r.extra and r.summary_en is None
        assert "terms_text_source" not in r.extra and "ocr_engine" not in r.extra


def test_dgft_ambiguous_price_is_left_empty(run_with_routes, session_factory, pin_today, monkeypatch):
    monkeypatch.setattr(ow, "pdf_text", lambda content: "Minimum Export Price (MEP) on Natural Honey: US$ 1,234 per MT "
                                                         "for drums and US$ 1,345 per MT for bulk containers.")
    res = run_with_routes("in_dgft_honey", dgft_routes())
    assert any("several minimum export prices" in w for w in res["warnings"]), res
    with session_factory() as s:
        r = _items(s, "in_dgft_honey")["DGFT Notification No. 91/2026-27"]
        assert "mep_usd_per_t" not in r.extra and r.extra["mep_values_found"] == [1234.0, 1345.0]
        assert r.doc_type == "price_floor"


# ---------------------------------------------------------------------------
# Start-up probes: drift fails loudly, other feeds still stored
# ---------------------------------------------------------------------------


def test_boletin_drift_fails_the_run_but_keeps_the_other_feeds(run_with_routes, session_factory, pin_today):
    res = run_with_routes("ar_senasa_honey", senasa_routes({BO_LATEST: fx("bo_primera_drift.html")}))
    assert res["status"] == "failed", res
    assert res["error"].startswith("Boletín Oficial (primera sección): Boletín Oficial: no notice link")
    assert BO + "/seccion/primera" in res["error"]                    # names the URL
    with session_factory() as s:
        items = _items(s, "ar_senasa_honey")
        assert set(items) == SENASA_EXPECTED - {"BO-AR primera 999101"}   # SENASA news and EAR committed
        state = _state(s, "ar_senasa_honey")
        assert "bo_last_edition" not in state and state["ear_checked"] == TODAY.isoformat()
        assert BO + "/seccion/primera" in _raw_urls(s, "ar_senasa_honey")   # the drifted page is archived
        src = _src(s, "ar_senasa_honey")
        assert src.last_run_status == "failed"


def test_mapa_news_drift_fails_the_run_but_keeps_the_dou(run_with_routes, session_factory, pin_today):
    res = run_with_routes("br_mapa_honey", mapa_routes({MAPA_LIST: fx("mapa_noticias_drift.html")}))
    assert res["status"] == "failed" and res["error"].startswith("MAPA news (gov.br): MAPA news (gov.br): no item link")
    assert ow.MAPA_NEWS_URL in res["error"]
    with session_factory() as s:
        assert set(_items(s, "br_mapa_honey")) == {f"dou:{DOU_PORTARIA}", f"dou:{DOU_IN}"}
        assert "mapa_news_complete" not in _state(s, "br_mapa_honey")


def test_dou_drift_fails_the_run_but_keeps_the_news(run_with_routes, session_factory, pin_today):
    res = run_with_routes("br_mapa_honey", mapa_routes({DOU_APICOLA: fx("dou_busca_drift.html")}))
    assert res["status"] == "failed", res
    assert "Diário Oficial da União (DOU search): DOU search (https://www.in.gov.br/consulta/-/buscar/dou?q=" in res["error"]
    with session_factory() as s:
        items = _items(s, "br_mapa_honey")
        assert {r for r in items if r.startswith("mapa:")} == {r for r in MAPA_EXPECTED if r.startswith("mapa:")}
        assert "dou_complete" not in _state(s, "br_mapa_honey")


def test_listing_without_dates_fails_loudly(run_with_routes, session_factory, pin_today):
    undated = re.sub(r'<time datetime="[^"]*">[^<]*</time>', "", fx_text("senasa_noticias.html"))
    res = run_with_routes("ar_senasa_honey", senasa_routes({SENASA_LIST: undated.encode()}))
    assert res["status"] == "failed" and "SENASA news (argentina.gob.ar)" in res["error"]
    assert "readable date" in res["error"]
    with session_factory() as s:
        assert not any(r.startswith("senasa:") for r in _items(s, "ar_senasa_honey"))   # undated items never stored


def test_creha_page_without_pdfs_is_drift(run_with_routes, session_factory, pin_today):
    res = run_with_routes("ar_senasa_honey", senasa_routes({ow.SENASA_CREHA_URL: b"<html><body><main><p>Sin documentos"
                                                                                  b"</p></main></body></html>"}))
    assert res["status"] == "failed" and "SENASA Plan CREHA (Lista EAR)" in res["error"] and "no PDF link" in res["error"]
    with session_factory() as s:
        assert "ear_checked" not in _state(s, "ar_senasa_honey")         # re-checked on the next run


def test_creha_page_without_ear_lists_warns(run_with_routes, session_factory, pin_today):
    creha = re.sub(r'<li><a href="/sites/default/files/ear_[^"]*">[^<]*</a>[^<]*</li>', "", fx_text("senasa_creha.html"))
    res = run_with_routes("ar_senasa_honey", senasa_routes({ow.SENASA_CREHA_URL: creha.encode()}))
    assert res["status"] == "partial" and any("none is a 'Lista EAR'" in w for w in res["warnings"]), res


def test_dgft_drift_fails_the_run_and_stores_nothing(run_with_routes, session_factory, pin_today):
    res = run_with_routes("in_dgft_honey", dgft_routes({ow.DGFT_LIST_URL: fx("dgft_notifications_drift.html")}))
    assert res["status"] == "failed" and "DGFT notifications: no table row found on " + ow.DGFT_LIST_URL in res["error"]
    with session_factory() as s:
        assert _items(s, "in_dgft_honey") == {}


@pytest.mark.parametrize("key", KEYS)
def test_unreachable_hosts_mean_offline(key, run_with_routes):
    res = run_with_routes(key, {})
    assert res["status"] == "offline" and "Cannot reach" in res["error"], res


def test_one_unreachable_host_is_a_partial_run(run_with_routes, session_factory, pin_today):
    res = run_with_routes("br_mapa_honey", _without(mapa_routes(), "in\\.gov\\.br"))
    assert res["status"] == "partial" and res["error"] is None, res
    assert any(w.startswith("Diário Oficial da União (DOU search): host unreachable (Cannot reach www.in.gov.br")
               and "retried on the next run" in w for w in res["warnings"]), res
    with session_factory() as s:
        assert {r for r in _items(s, "br_mapa_honey")} == {r for r in MAPA_EXPECTED if r.startswith("mapa:")}
        assert "dou_complete" not in _state(s, "br_mapa_honey")          # the DOU window is read again


def test_boletin_oficial_unreachable_keeps_the_senasa_results(run_with_routes, session_factory, pin_today):
    # Live run, Nov 2026: www.boletinoficial.gob.ar reset every connection from the sandbox
    # ("[Errno 104] Connection reset by peer") and the whole SENASA run was marked failed.
    res = run_with_routes("ar_senasa_honey", _without(senasa_routes(), "boletinoficial"))
    assert res["status"] == "partial" and res["error"] is None, res
    assert any(w.startswith("Boletín Oficial (primera sección): host unreachable (Cannot reach "
                            "www.boletinoficial.gob.ar") for w in res["warnings"]), res
    with session_factory() as s:
        assert set(_items(s, "ar_senasa_honey")) == SENASA_EXPECTED - {"BO-AR primera 999101"}
        assert "bo_last_edition" not in _state(s, "ar_senasa_honey")    # nothing marked as read


def test_unreachable_feed_plus_a_drifted_feed_still_fails(run_with_routes, session_factory, pin_today):
    routes = _without(senasa_routes({ow.SENASA_CREHA_URL: b"<html><body><p>moved</p></body></html>"}), "boletinoficial")
    res = run_with_routes("ar_senasa_honey", routes)
    assert res["status"] == "failed", res
    assert "no PDF link at all" in res["error"] and "Cannot reach www.boletinoficial.gob.ar" in res["error"]


# ---------------------------------------------------------------------------
# Regression tests for defects fixed in the module
# ---------------------------------------------------------------------------


def test_undated_item_waits_for_its_date_when_the_article_budget_is_spent(run_with_routes, session_factory, pin_today,
                                                                          monkeypatch):
    # Regression: an honey item without a date in the listing was stored undated, for good
    # (append-only), when the per-run article budget was spent, although its page states the date.
    monkeypatch.setattr(ow, "MAX_ARTICLE_FETCHES", 1)
    res = run_with_routes("br_mapa_honey", mapa_routes())
    assert any("2 article(s) to check were postponed" in w for w in res["warnings"]), res
    with session_factory() as s:
        assert mapa_ref(ART_APICULTURA) not in _items(s, "br_mapa_honey")
        assert all(r.published_at for r in _items(s, "br_mapa_honey").values())
    run_with_routes("br_mapa_honey", mapa_routes())                     # the fish EU-list article uses the budget
    res = run_with_routes("br_mapa_honey", mapa_routes())
    assert res["status"] == "success" and res["new"] == 1 and res["warnings"] == [], res
    with session_factory() as s:
        r = _items(s, "br_mapa_honey")[mapa_ref(ART_APICULTURA)]
        assert r.published_at == date(2026, 10, 29) and r.extra["date_source"] == "article"
        assert _state(s, "br_mapa_honey")["mapa_news_complete"] == TODAY.isoformat()


def test_undated_item_is_not_stored_while_its_article_cannot_be_read(run_with_routes, session_factory, pin_today):
    # Regression: same defect when the article page failed to download.
    res = run_with_routes("br_mapa_honey", mapa_routes({MAPA_ART + ART_APICULTURA: (500, b"")}))
    assert res["status"] == "partial" and any(ART_APICULTURA in w and "retried next run" in w for w in res["warnings"])
    with session_factory() as s:
        assert mapa_ref(ART_APICULTURA) not in _items(s, "br_mapa_honey")
        assert "mapa_news_complete" not in _state(s, "br_mapa_honey")
    run_with_routes("br_mapa_honey", mapa_routes())
    with session_factory() as s:
        assert _items(s, "br_mapa_honey")[mapa_ref(ART_APICULTURA)].published_at == date(2026, 10, 29)


def test_postponed_work_keeps_the_feed_in_backfill_mode(run_with_routes, session_factory, pin_today, monkeypatch):
    # Regression: the feed was marked complete even with postponed work, so the next run read only
    # the first `pages` pages and items postponed on a back-fill page were never processed.
    monkeypatch.setattr(ow, "MAPA_NEWS", dataclasses.replace(ow.MAPA_NEWS, pages=1, backfill_pages=2))
    monkeypatch.setattr(ow, "MAX_ARTICLE_FETCHES", 1)
    pages: list[str] = []
    real = ow.parse_listing
    monkeypatch.setattr(ow, "parse_listing", lambda content, url, **kw: pages.append(url) or real(content, url, **kw))
    _seed_state(session_factory, "br_mapa_honey", {"mapa_news_complete": "2026-11-01"})

    run_with_routes("br_mapa_honey", mapa_routes())                      # complete before: 1 page; work postponed
    assert len(pages) == 1
    with session_factory() as s:
        assert "mapa_news_complete" not in _state(s, "br_mapa_honey")
    for _ in range(2):                                                   # back-fill pages until nothing is left
        run_with_routes("br_mapa_honey", mapa_routes())
    assert len(pages) == 1 + 2 + 2
    with session_factory() as s:
        assert set(_items(s, "br_mapa_honey")) == MAPA_EXPECTED
        assert _state(s, "br_mapa_honey")["mapa_news_complete"] == TODAY.isoformat()
    pages.clear()
    run_with_routes("br_mapa_honey", mapa_routes())
    assert len(pages) == 1                                               # complete again: normal run


def test_a_crashing_feed_does_not_skip_the_others(run_with_routes, session_factory, pin_today, monkeypatch):
    # Regression: an unexpected exception (a parser bug) in the first feed skipped the other feeds.
    real = ow._store
    calls = {"news": 0}

    def flaky(ctx, **kw):
        real(ctx, **kw)
        if kw["reference"].startswith("mapa:"):
            calls["news"] += 1
            if calls["news"] == 2:
                raise TypeError("boom after a partial write")

    monkeypatch.setattr(ow, "_store", flaky)
    res = run_with_routes("br_mapa_honey", mapa_routes())
    assert res["status"] == "failed" and "MAPA news (gov.br): TypeError: boom after a partial write" in res["error"]
    assert res["new"] == 2                                                # only the committed DOU acts count
    with session_factory() as s:
        assert set(_items(s, "br_mapa_honey")) == {f"dou:{DOU_PORTARIA}", f"dou:{DOU_IN}"}  # crashed feed rolled back
        state = _state(s, "br_mapa_honey")
        assert "dou_complete" in state and "mapa_news_complete" not in state


# ---------------------------------------------------------------------------
# Nothing is invented: known events come only from the official pages
# ---------------------------------------------------------------------------

# Real events named in docs/research/official_*.json. They must never be written in the module:
# the watchers collect them from the official pages at run time.
KNOWN_EVENT_STRINGS = (
    "1400", "1,400", "1.400",               # the Indian MEP (US$ per tonne)
    "09/2026-27", "52/2025-26", "45/2024-25",   # DGFT notifications that set or extended it
    "2026-12-31", "31.12.2026", "31st December, 2026", "31 Dec 2026",   # its expiry
    "2026/1189",                            # the EU regulation that de-listed Brazil
    "2026-09-03", "3 Sep 2026",             # ... and its date of effect
    "50/2026", "61/2026",                   # SAGyP resolutions (Mercosur-EU quota, retail protocol)
    "45,000", "45000",                      # the quota ceiling
    "341394", "500584", "504035",           # official page ids cited in the research
)


def test_module_hard_codes_no_known_event():
    source = Path(ow.__file__).read_text(encoding="utf-8")
    for s in KNOWN_EVENT_STRINGS:
        assert s not in source, f"{s!r} is written in official_watchers.py"
    numbers = {n.value for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Constant)
               and isinstance(n.value, (int, float)) and not isinstance(n.value, bool)}
    assert not numbers & {1400, 45000}


def test_every_stored_value_comes_from_a_fixture_page(run_with_routes, session_factory, pin_today):
    for key in KEYS:
        run_with_routes(key, ROUTES[key]())
    corpus = "\n".join(fx_text(p.name) for p in FIX.glob("*.html"))
    corpus += "\n".join(ow.pdf_text(fx(p.name)) for p in FIX.glob("*.pdf"))
    with session_factory() as s:
        rows = list(s.scalars(select(RegulationItem)))
    for r in rows:
        ident = {"mapa": r.reference.rsplit("/", 1)[-1], "senasa": r.reference.rsplit("/", 1)[-1],
                 "dou": r.reference.removeprefix("dou:"), "SENASA Lista EAR": r.url.rsplit("/", 1)[-1],
                 "BO-AR": r.reference.rsplit(" ", 1)[-1], "DGFT": r.reference.rsplit(" ", 1)[-1]}
        token = next(v for k, v in ident.items() if r.reference.startswith(k))
        assert token in corpus, r.reference
        assert r.title.split(" — ")[-1] in corpus or r.title in corpus, r.title
        for v in r.extra.get("honey_rows", []):
            assert v in corpus
    meps = {r.extra["mep_usd_per_t"] for r in rows if r.extra.get("mep_usd_per_t")}
    assert meps == {1111.0} and "US$ 1,111 per MT" in corpus
    assert {r.extra.get("valid_until") for r in rows if r.extra.get("valid_until")} == {"2027-06-30", "2026-03-31"}
    blob = "\n".join(f"{r.title} {r.extra} {r.summary_en}" for r in rows)
    for s in KNOWN_EVENT_STRINGS:
        assert s not in blob


@pytest.mark.parametrize("key,routes", [
    ("in_dgft_honey", lambda: dgft_routes({ow.DGFT_LIST_URL: re.sub(
        r"<tr><td>\d</td><td>(?:94|91|93)/.*?</tr>", "", fx_text("dgft_notifications.html")).encode()})),
    ("br_mapa_honey", lambda: mapa_routes({
        MAPA_LIST: fx("mapa_noticias_drift.html").replace(
            b'<div id="app"', b'<a href="https://www.gov.br/agricultura/pt-br/assuntos/noticias/safra-de-soja-'
                              b'ilustrativo">Safra de soja 2026/27 (ilustrativo)</a> 02/11/2026 <div id="app"'),
        **{q: fx("dou_busca_apicultura.html") for q in (DOU_MEL, DOU_APICOLA, DOU_APICULTURA)}})),
    ("ar_senasa_honey", lambda: senasa_routes({
        SENASA_LIST: re.sub(r'<div class="col-xs-12[^"]*">\s*<a href="/noticias/(?!campana)[^"]*".*?</a>\s*</div>', "",
                            fx_text("senasa_noticias.html"), flags=re.DOTALL).encode(),
        ow.SENASA_CREHA_URL: fx_text("senasa_creha.html").replace("ear_91-26", "ear_90-26").encode(),
        BO_LATEST: fx_text("bo_primera.html").replace("AGRICULTURA, GANADERÍA Y PESCA", "TRANSPORTE").encode()})),
])
def test_no_honey_on_the_pages_means_nothing_stored(key, routes, run_with_routes, session_factory, pin_today):
    res = run_with_routes(key, routes())
    assert res["status"] == "no_change" and res["new"] == 0 and res["error"] is None, res
    with session_factory() as s:
        assert _items(s, key) == {}
