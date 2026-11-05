"""Honey exporters and importers by company (/api/companies...).

    GET /companies          per country: what official company-level information exists (official
                            figures / official list, names only / not published / exists but not
                            accessible / not checked yet), the authority, the reason, and how many
                            companies Paladex holds
    GET /companies/{iso3}   one country: its availability and the lists, with provenance: exporters and
                            importers, every figure as published (exact value, band, or none)

Rules (the brief of the Companies page): only official or authoritative public sources that publish
company-level information; nothing inferred or ranked from news, marketing or commercial aggregators.
A list without figures is shown in alphabetical order, never ranked. A value band is shown as a band.
Every list carries its source, period and what the figure is.

``AVAILABILITY`` is the research record (checked live on 2026-11-05 unless stated): a country's entry
says what its authorities publish and why nothing more is shown. It is reference text, not collected
data; the lists themselves come only from ``company_records``.
"""
from __future__ import annotations

import re
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, cast, func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Country, Source
from ..models_companies import CompanyRecord, CompanyRole, MeasureKind
from .common import demo_clause, freshness, iso, source_brief

router = APIRouter(prefix="/companies", tags=["companies"])

CHECKED_ON = "2026-11-05"

# Status vocabulary, from the most to the least useful.
FIGURES = "figures"            # official company-level figures (value, band, volume or rank)
REGISTER = "register"          # official list or register: names only, never ranked
NONE = "not_published"         # the authorities publish no company-level information
UNAVAILABLE = "unavailable"    # an official list exists but cannot be used (login, broken links)
UNVERIFIED = "unverified"      # not researched yet
STATUS_ORDER = [FIGURES, REGISTER, UNAVAILABLE, NONE, UNVERIFIED]

EU_MEMBERS = (
    "AUT", "BEL", "BGR", "HRV", "CYP", "CZE", "DNK", "EST", "FIN", "FRA", "DEU", "GRC", "HUN", "IRL",
    "ITA", "LVA", "LTU", "LUX", "MLT", "NLD", "POL", "PRT", "ROU", "SVK", "SVN", "ESP", "SWE",
)
EU_AUTHORITIES = {
    "ITA": "ISTAT (Istituto nazionale di statistica)", "DEU": "Destatis (Statistisches Bundesamt)",
    "FRA": "Direction générale des douanes et droits indirects (DGDDI)",
    "ESP": "Agencia Tributaria (Departamento de Aduanas)", "NLD": "CBS (Centraal Bureau voor de Statistiek)",
}
EU_URL = "https://ec.europa.eu/eurostat/web/international-trade-in-goods"
TRACES_NOTE = {
    "it": ("Per esportare miele nell'UE uno stabilimento deve figurare nell'elenco che il paese invia alla Commissione "
           "europea (regolamento delegato (UE) 2022/2292, modificato dal 2023/2652); quell'elenco (TRACES) si apre "
           "solo con un account EU Login, quindi Paladex non lo usa."),
    "en": ("To export honey to the EU an establishment must be on the list its country sends to the European "
           "Commission (Delegated Regulation (EU) 2022/2292, amended by 2023/2652); that list (TRACES) opens only "
           "with an EU Login account, so Paladex does not use it."),
}


def _entry(status: str, authority: str, url: str | None, reason_it: str, reason_en: str, *,
           sources: tuple[str, ...] = (), roles: tuple[str, ...] = (), checked: str | None = CHECKED_ON) -> dict:
    return {"status": status, "authority": authority, "url": url, "reason_it": reason_it, "reason_en": reason_en,
            "source_keys": list(sources), "roles": list(roles), "checked_on": checked}


AVAILABILITY: dict[str, dict] = {
    "URY": _entry(
        FIGURES, "Uruguay XXI – Sistema de Información Estadística (dati Dirección Nacional de Aduanas)",
        "https://herramientas.uruguayxxi.gub.uy/sistema_de_estadistica/",
        "Uruguay XXI, l'agenzia governativa per le esportazioni, pubblica le esportazioni di miele (NCM 0409) di "
        "ogni azienda: valore FOB esatto in dollari per anno, dai dati della dogana. Per le importazioni non esiste "
        "una vista per azienda.",
        "Uruguay XXI, the government export agency, publishes the honey exports (NCM 0409) of every company: exact "
        "FOB value in US dollars per year, from customs data. There is no company view for imports.",
        sources=("uy_sie_honey_exporters",), roles=(CompanyRole.EXPORTER.value,)),
    "GBR": _entry(
        REGISTER, "HM Revenue & Customs (HMRC) – UK Trade Info, \"Find UK traders\"",
        "https://www.uktradeinfo.com/find-uk-traders/",
        "La dogana britannica pubblica ogni mese i nomi e la località delle aziende che hanno importato o esportato "
        "miele (codice 04090000). Per legge non pubblica quantità né valori: è un elenco di nomi, non una classifica.",
        "UK customs publish every month the names and location of the businesses that imported or exported honey "
        "(code 04090000). By law they publish no quantities or values: a list of names, not a ranking.",
        sources=("uk_hmrc_honey_traders",), roles=(CompanyRole.IMPORTER.value, CompanyRole.EXPORTER.value)),
    "BRA": _entry(
        NONE, "MDIC / SECEX (Secretaria de Comércio Exterior)",
        "https://www.gov.br/mdic/pt-br/assuntos/comercio-exterior/estatisticas/perguntas-frequentes-faq",
        "Il ministero (MDIC) dichiara che non pubblica né fornisce elenchi di aziende esportatrici o importatrici, né "
        "dati che le rivelino (segreto fiscale: decreto 11.544/2023, art. 13; Codice tributario, art. 198). Tra le "
        "sue statistiche (dati aperti, Comex Stat) non c'è alcun elenco di aziende.",
        "The ministry (MDIC) states that it neither publishes nor provides lists of exporting or importing companies, "
        "nor data that would reveal them (tax secrecy: Decree 11,544/2023, art. 13; Tax Code, art. 198). Its "
        "statistics (open data, Comex Stat) contain no list of companies."),
    "ARG": _entry(
        NONE, "INDEC (statistiche del commercio estero); SENASA (stabilimenti apistici)",
        "https://www.argentina.gob.ar/node/179376",
        "L'INDEC pubblica il commercio per prodotto e paese, mai per azienda (segreto statistico, legge 17.622): "
        "nasconde perfino i paesi con meno di tre esportatori. Il SENASA autorizza gli stabilimenti che esportano "
        "miele, ma pubblica solo la procedura, non l'elenco.",
        "INDEC publishes trade by product and country, never by company (statistical secrecy, Law 17,622): it even "
        "masks destinations with fewer than three exporters. SENASA authorises the establishments that export honey "
        "but publishes only the procedure, not the list."),
    "CHL": _entry(
        UNAVAILABLE, "Servicio Nacional de Aduanas; SAG (Servicio Agrícola y Ganadero)",
        "https://www.sag.gob.cl/ambitos-de-accion/listas-de-establecimientos-apicolas-autorizados-para-exportar-la-ue",
        "I dati aperti della dogana non hanno il campo esportatore. Il SAG tiene l'elenco degli stabilimenti "
        "autorizzati a esportare miele nell'UE, ma i tre elenchi linkati dalla sua pagina rispondono «pagina non "
        "trovata».",
        "Customs open data have no exporter field. SAG keeps the list of establishments authorised to export honey to "
        "the EU, but the three lists linked from its page answer 'page not found'."),
    "USA": _entry(
        NONE, "U.S. Census Bureau; U.S. Customs and Border Protection (CBP)",
        "https://www.census.gov/foreign-trade/index.html",
        "Il Census pubblica il commercio per prodotto e paese; i dati delle singole aziende sono riservati per legge "
        "(Title 13, U.S. Code). I manifesti di carico della CBP sono pubblici per legge (19 CFR 103.31) ma si "
        "ottengono solo tramite rivenditori commerciali: Paladex non li usa.",
        "The Census Bureau publishes trade by product and country; company data are confidential by law (Title 13, "
        "U.S. Code). CBP cargo manifests are public by law (19 CFR 103.31) but are obtained only through commercial "
        "resellers: Paladex does not use them."),
    "CHE": _entry(
        NONE, "Ufficio federale della dogana e della sicurezza dei confini (UDSC) – Swiss-Impex",
        "https://www.bazg.admin.ch/en/foreign-trade-statistics",
        "Le statistiche svizzere del commercio estero (Swiss-Impex) sono pubblicate per voce di tariffa e paese; "
        "nessun dato per azienda è pubblicato.",
        "Swiss foreign trade statistics (Swiss-Impex) are published by tariff number and country; no company-level "
        "data are published."),
    "NOR": _entry(
        NONE, "Statistisk sentralbyrå (SSB, Statistics Norway)",
        "https://www.ssb.no/en/utenriksokonomi/utenrikshandel/statistikk/utenrikshandel-med-varer",
        "Le statistiche norvegesi del commercio estero sono pubblicate per prodotto e paese, mai per azienda: i dati "
        "delle singole imprese sono riservati per legge (legge sulla statistica, § 7).",
        "Norwegian foreign trade statistics are published by product and country, never by company: individual "
        "company data are confidential by law (Statistics Act, section 7)."),
}

_EU_REASON_IT = ("Le statistiche ufficiali del commercio estero sono pubblicate per prodotto e paese partner, mai per "
                 "azienda: i dati delle singole imprese sono riservati per legge (regolamenti (CE) n. 223/2009 e (UE) "
                 "2019/2152). Registri pubblici di confezionatori o esportatori di miele: non verificati.")
_EU_REASON_EN = ("Official foreign trade statistics are published by product and partner country, never by company: "
                 "individual company data are confidential by law (Regulations (EC) No 223/2009 and (EU) 2019/2152). "
                 "Public registers of honey packers or exporters: not checked.")
for _iso in EU_MEMBERS:
    AVAILABILITY[_iso] = _entry(
        NONE, EU_AUTHORITIES.get(_iso, "Istituto nazionale di statistica / Eurostat"), EU_URL, _EU_REASON_IT, _EU_REASON_EN)

# Main honey origins outside Europe and South America (checked live on 2026-11-05). For each, the list
# of establishments it sends to the EU exists (TRACES_NOTE) but opens only with EU Login.
AVAILABILITY.update({
    "IND": _entry(
        REGISTER, "Export Inspection Council of India (EIC) – Ministero del Commercio e dell'Industria",
        "https://eicindia.gov.in/offerings/commodity-wise-facilities?tab=animal",
        "L'Export Inspection Council pubblica l'elenco degli stabilimenti autorizzati a lavorare miele per "
        "l'esportazione (27 al 5 novembre 2026, 16 dei quali autorizzati anche per l'Unione europea), con numero e "
        "scadenza dell'autorizzazione: un elenco di nomi, non una classifica. Nessun dato per azienda sulle quantità "
        "o i valori esportati. Le iscrizioni degli esportatori all'APEDA non sono state verificate.",
        "The Export Inspection Council publishes the list of establishments approved to process honey for export (27 "
        "on 5 November 2026, 16 of them approved for the European Union too), with approval number and validity: a "
        "list of names, not a ranking. No company-level export quantities or values. Exporter registrations with "
        "APEDA were not checked.",
        sources=("in_eic_honey_establishments",), roles=(CompanyRole.REGISTERED_EXPORTER.value,)),
    "CAN": _entry(
        REGISTER, "Innovation, Science and Economic Development Canada (ISED) – Canadian Importers Database",
        "https://www.ised-isde.canada.ca/app/ixb/cid-bdic/productReport.html?hsCode=040900",
        "Il governo canadese (ISED, dati della dogana) pubblica ogni anno i principali importatori di miele (HS "
        "040900): le aziende che insieme fanno fino all'80% del valore importato, con città e provincia, senza valori "
        "per azienda (25 nel 2024). Per le esportazioni nessun elenco ufficiale di aziende: Statistics Canada pubblica "
        "per prodotto e paese; il registro delle licenze alimentari della CFIA risponde «410 Gone».",
        "The Canadian government (ISED, customs data) publishes every year the major honey importers (HS 040900): the "
        "companies that together account for up to 80% of the import value, with city and province, without values "
        "per company (25 in 2024). For exports there is no official company list: Statistics Canada publishes by "
        "product and country; CFIA's food licence registry answers '410 Gone'.",
        sources=("ca_cid_honey_importers",), roles=(CompanyRole.IMPORTER.value,)),
    "CHN": _entry(
        UNAVAILABLE, "General Administration of Customs of China (GACC)", "http://www.customs.gov.cn/",
        "Gli esportatori di miele devono essere registrati presso la dogana cinese (GACC, registro delle imprese di "
        "produzione di alimenti per l'esportazione), che compila anche l'elenco per l'UE. I siti della GACC non "
        "rispondono dalla rete di sviluppo (nome a dominio non risolto il 5 novembre 2026): non verificato oltre. "
        "Le statistiche doganali sono pubblicate per prodotto e paese. " + TRACES_NOTE["it"],
        "Honey exporters must be registered with Chinese customs (GACC, register of export food production "
        "enterprises), which also compiles the list for the EU. GACC's websites do not answer from the development "
        "network (domain not resolved on 5 November 2026): not checked further. Customs statistics are published by "
        "product and country. " + TRACES_NOTE["en"]),
    "VNM": _entry(
        UNAVAILABLE, "Ministero dell'Agricoltura e dell'Ambiente – servizi veterinari e qualità (già DAH e NAFIQAD)",
        "https://www.nafiqad.gov.vn/",
        "Gli stabilimenti che esportano miele nell'UE sono iscritti dalle autorità veterinarie vietnamite nell'elenco "
        "inviato alla Commissione. I siti delle autorità (nafiqad.gov.vn, cucthuy.gov.vn, vfa.gov.vn) non rispondono "
        "dalla rete di sviluppo (5 novembre 2026): non verificato se pubblichino un elenco proprio. " + TRACES_NOTE["it"],
        "The establishments exporting honey to the EU are entered by the Vietnamese veterinary authorities in the list "
        "sent to the Commission. The authorities' websites (nafiqad.gov.vn, cucthuy.gov.vn, vfa.gov.vn) do not answer "
        "from the development network (5 November 2026): not checked whether they publish a list of their own. "
        + TRACES_NOTE["en"]),
    "UKR": _entry(
        UNAVAILABLE, "Derzhprodspozhyvsluzhba (State Service of Ukraine on Food Safety and Consumer Protection)",
        "https://dpss.gov.ua/news/z-30-lystopada-zminiuiutsia-pravyla-eksportu-medu-do-krain-ies",
        "Dal 30 novembre 2024 esporta miele nell'UE solo chi è nell'elenco che il servizio veterinario ucraino invia "
        "alla Commissione; il servizio pubblica le regole ma non l'elenco. Il suo registro pubblico delle strutture "
        "degli operatori alimentari (agro-id.gov.ua) riguarda tutte le imprese alimentari, non gli esportatori. "
        "Le statistiche del commercio estero non sono pubblicate per azienda. " + TRACES_NOTE["it"],
        "Since 30 November 2024 only establishments on the list the Ukrainian food-safety service sends to the "
        "Commission may export honey to the EU; the service publishes the rules but not the list. Its public register "
        "of food business facilities (agro-id.gov.ua) covers all food businesses, not exporters. Foreign trade "
        "statistics are not published by company. " + TRACES_NOTE["en"]),
    "MEX": _entry(
        UNAVAILABLE, "SENASICA (Servicio Nacional de Sanidad, Inocuidad y Calidad Agroalimentaria)",
        "https://www.datos.gob.mx/dataset/empresas_habilitadas_exportacion",
        "Il SENASICA pubblica come dato aperto le «Empresas habilitadas para exportación» (ragione sociale, paese di "
        "destinazione e merce di origine animale; aggiornamento giugno 2025), ma il file e l'API del portale rispondono "
        "«Access Denied» (403) dalla rete di sviluppo: non è stato possibile verificare se comprenda il miele. Da "
        "riprovare dalla rete di produzione. " + TRACES_NOTE["it"],
        "SENASICA publishes as open data the 'Empresas habilitadas para exportación' (company name, destination country "
        "and animal product; June 2025 update), but the file and the portal API answer 'Access Denied' (403) to the "
        "development network: it could not be checked whether it covers honey. To retry from the production network. "
        + TRACES_NOTE["en"]),
    "TUR": _entry(
        UNAVAILABLE, "Ministero dell'Agricoltura e delle Foreste – Direzione generale Alimenti e Controllo (GKGM)",
        "https://www.tarimorman.gov.tr/GKGM/Link/46/Ithalat-Ihracat",
        "Il ministero pubblica le procedure di esportazione dei prodotti animali, non un elenco degli esportatori di "
        "miele o degli stabilimenti autorizzati. L'istituto di statistica (TÜİK) pubblica per prodotto e paese, mai per "
        "azienda. " + TRACES_NOTE["it"],
        "The ministry publishes the export procedures for animal products, not a list of honey exporters or approved "
        "establishments. The statistics institute (TÜİK) publishes by product and country, never by company. "
        + TRACES_NOTE["en"]),
    "THA": _entry(
        UNAVAILABLE, "Department of Livestock Development (DLD) – Ministero dell'Agricoltura e delle Cooperative",
        "https://certify.dld.go.th/",
        "Il DLD certifica gli stabilimenti che esportano miele; il suo sito delle certificazioni non pubblica un elenco "
        "per il miele e il sito principale blocca gli accessi automatici (protezione anti-bot). " + TRACES_NOTE["it"],
        "DLD certifies the establishments exporting honey; its certification website publishes no honey list and its "
        "main website blocks automated access (bot protection). " + TRACES_NOTE["en"]),
    "NZL": _entry(
        UNAVAILABLE, "Ministry for Primary Industries (MPI)",
        "https://www.mpi.govt.nz/export/food/honey-and-bee-products/registers-and-lists",
        "Il ministero (MPI) tiene registri pubblici: gli esportatori registrati per i prodotti animali (anche su "
        "data.govt.nz) e gli stabilimenti di prodotti apistici approvati per singoli mercati, senza quantità né valori. "
        "Il sito dell'MPI e il catalogo data.govt.nz rispondono alle richieste automatiche con una pagina anti-bot "
        "(Imperva): Paladex non li può leggere. " + TRACES_NOTE["it"],
        "The ministry (MPI) keeps public registers: the exporters registered for animal products (also on "
        "data.govt.nz) and the bee-product premises approved for individual markets, without quantities or values. "
        "MPI's website and the data.govt.nz catalogue answer automated requests with a bot-protection page (Imperva): "
        "Paladex cannot read them. " + TRACES_NOTE["en"]),
    "AUS": _entry(
        UNAVAILABLE, "Department of Agriculture, Fisheries and Forestry (DAFF)",
        "https://micor.agriculture.gov.au/npg/european_union/edible_apiculture_products",
        "Chi esporta miele nell'UE deve essere uno stabilimento registrato presso il dipartimento (DAFF) e inserito "
        "nell'elenco UE. I siti del dipartimento (agriculture.gov.au, micor) non rispondono dalla rete di sviluppo "
        "(5 novembre 2026): non verificato se il registro degli stabilimenti sia pubblico. " + TRACES_NOTE["it"],
        "Honey exporters to the EU must be establishments registered with the department (DAFF) and on the EU list. "
        "The department's websites (agriculture.gov.au, micor) do not answer from the development network "
        "(5 November 2026): not checked whether its establishment register is public. " + TRACES_NOTE["en"]),
    "SRB": _entry(
        UNAVAILABLE, "Uprava za veterinu (Direzione veterinaria) – Ministero dell'Agricoltura",
        "https://www.vet.minpolj.gov.rs/registri/",
        "I registri pubblicati dalla Direzione veterinaria (identificazione, canili, rifugi, sperimentazione) non "
        "comprendono gli stabilimenti autorizzati all'esportazione; l'istituto di statistica non pubblica dati per "
        "azienda. " + TRACES_NOTE["it"],
        "The registers published by the Veterinary Directorate (identification, kennels, shelters, animal testing) do "
        "not include the establishments approved for export; the statistical office publishes no company data. "
        + TRACES_NOTE["en"]),
    "MDA": _entry(
        UNAVAILABLE, "ANSA (Agenția Națională pentru Siguranța Alimentelor)",
        "https://www.ansa.gov.md/import-export.html",
        "L'ANSA autorizza i produttori di miele che esportano nell'UE e li iscrive nell'elenco UE. L'unico elenco che "
        "pubblica («întreprinderi autorizate ... import/export», file Word) risale a febbraio 2020, non contiene "
        "operatori del miele e riporta dati personali: non usato. " + TRACES_NOTE["it"],
        "ANSA authorises the honey producers that export to the EU and has them entered in the EU list. The only list "
        "it publishes ('enterprises authorised ... import/export', a Word file) dates from February 2020, contains no "
        "honey operator and carries personal data: not used. " + TRACES_NOTE["en"]),
})


def availability_for(iso3: str) -> dict:
    """The research entry of a country; a country never researched is 'unverified'."""
    return AVAILABILITY.get(iso3) or _entry(
        UNVERIFIED, "—", None, "Non ancora verificato da Paladex: nessun elenco di aziende mostrato.",
        "Not yet checked by Paladex: no company list is shown.", checked=None)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def _current(db: Session):
    C = CompanyRecord
    return select(C).where(C.is_current.is_(True), demo_clause(C, db))


def _counts(db: Session) -> dict[str, dict]:
    """{iso3: {role: companies, "latest_period": label}} over current records."""
    C = CompanyRecord
    out: dict[str, dict] = defaultdict(dict)
    # One company = the source's own identifier when it gives one (HMRC trader number, EIC approval
    # number), else the name.
    who = func.coalesce(cast(func.json_extract(C.extra, "$.trader_id"), String),
                        func.json_extract(C.extra, "$.register_no"), C.company_name)
    q = (select(C.country_iso3, C.role, who, func.max(C.period_end), func.max(C.period_label))
         .where(C.is_current.is_(True), demo_clause(C, db)).group_by(C.country_iso3, C.role, who))
    names: dict[tuple[str, str], int] = defaultdict(int)
    for iso3, role, _name, end, label in db.execute(q):
        names[(iso3, role)] += 1
        d = out[iso3]
        if end and (d.get("_end") is None or end > d["_end"]):
            d["_end"], d["latest_period"] = end, label
    for (iso3, role), n in names.items():
        out[iso3].setdefault("companies", {})[role] = n
    for d in out.values():
        d.pop("_end", None)
    return out


def _source_info(src: Source | None) -> dict | None:
    if src is None:
        return None
    return {**source_brief(src), "freshness": freshness(src), "expected_update": src.expected_update,
            "expected_update_en": src.expected_update_en, "terms_note": src.terms_note,
            "latest_period_label": src.latest_period_label, "last_success_at": iso(src.last_success_at)}


def _country_ref(c: Country) -> dict:
    return {"iso3": c.iso3, "name_it": c.name_it, "name_en": c.name_en, "region": c.region, "priority": bool(c.priority)}


@router.get("")
def companies_overview(db: Session = Depends(get_db)):
    countries = {c.iso3: c for c in db.scalars(select(Country))}
    counts = _counts(db)
    rows = []
    for iso3 in sorted(set(AVAILABILITY) | set(counts)):
        c = countries.get(iso3)
        if c is None:
            continue
        a = availability_for(iso3)
        n = counts.get(iso3, {})
        rows.append({**_country_ref(c), **a, "companies": n.get("companies", {}), "latest_period": n.get("latest_period")})
    rows.sort(key=lambda r: (STATUS_ORDER.index(r["status"]), not r["priority"], r["name_it"]))
    keys = {k for r in rows for k in r["source_keys"]}
    sources = [_source_info(s) for s in db.scalars(select(Source).where(Source.key.in_(keys)).order_by(Source.key))]
    return {
        "checked_on": CHECKED_ON,
        "countries": rows,
        "status_counts": {s: sum(1 for r in rows if r["status"] == s) for s in STATUS_ORDER},
        "sources": sources,
    }


def _period(r: CompanyRecord) -> dict:
    extra = r.extra or {}
    months = extra.get("months_covered")
    return {"label": r.period_label, "start": iso(r.period_start), "end": iso(r.period_end), "frequency": r.frequency,
            "data_status": r.data_status, "months_covered": months, "running_year": bool(extra.get("running_year"))}


def _figures_list(rows: list[CompanyRecord], src: Source | None) -> dict:
    """Companies x periods with the published figure (exact value or band). Sorted by the latest
    complete period's value (the source's own figure), then by the newest one; rank = position in that
    complete period, among the companies with a value in it."""
    periods: dict[str, dict] = {}
    by_company: dict[str, dict] = {}
    totals: dict[str, float] = {}
    for r in rows:
        periods.setdefault(r.period_label, _period(r))
        c = by_company.setdefault(r.company_name, {"name": r.company_name, "location": r.location, "values": {}})
        cell = {"value": r.value, "value_min": r.value_min, "value_max": r.value_max, "volume_kg": r.volume_kg,
                "data_status": r.data_status, "revision": r.revision}
        total = (r.extra or {}).get("national_total_usd")
        if total:
            totals[r.period_label] = total
            if r.value is not None:
                cell["share_pct"] = round(100 * r.value / total, 1)
        c["values"][r.period_label] = cell
    ordered = sorted(periods.values(), key=lambda p: p["start"])
    complete = [p["label"] for p in ordered if not p["running_year"] and p["data_status"] != "provisional"]
    ref = complete[-1] if complete else (ordered[-1]["label"] if ordered else None)
    newest = ordered[-1]["label"] if ordered else None

    def val(c: dict, label: str | None) -> float:
        cell = c["values"].get(label) if label else None
        if not cell:
            return -1.0
        return cell["value"] if cell["value"] is not None else (cell["value_min"] or 0.0)

    companies = sorted(by_company.values(), key=lambda c: (-val(c, ref), -val(c, newest), c["name"]))
    rank = 0
    for c in companies:
        if ref and ref in c["values"]:
            rank += 1
            c["rank_in_ref"] = rank
        else:
            c["rank_in_ref"] = None
    first = rows[0]
    return {
        "periods": ordered, "ref_period": ref, "national_totals": totals, "companies": companies,
        "currency": first.currency, "value_basis": first.value_basis,
    }


def _register_key(r: CompanyRecord):
    """One company of a list: the source's own identifier when it gives one (HMRC trader number, EIC
    approval number), else the name."""
    extra = r.extra or {}
    return extra.get("trader_id") or extra.get("register_no") or r.company_name


def _register_list(rows: list[CompanyRecord]) -> dict:
    """Names only: one entry per company with the periods it is listed in; alphabetical, never ranked."""
    by: dict[str, dict] = {}
    for r in rows:
        key = str(_register_key(r))
        e = by.setdefault(key, {"name": r.company_name, "location": r.location, "periods": [], "_end": r.period_end})
        e["periods"].append(r.period_label)
        if r.period_end >= e["_end"]:
            e["_end"], e["name"], e["location"] = r.period_end, r.company_name, r.location
    companies = []
    for e in by.values():
        e.pop("_end")
        e["periods"] = sorted(set(e["periods"]))
        e["latest_period"] = e["periods"][-1]
        companies.append(e)
    # Alphabetical, ignoring leading quotes or punctuation ("'PRIFYSGOL ABERYSTWYTH'" under P).
    companies.sort(key=lambda e: (re.sub(r"^[^0-9A-Za-z]+", "", e["name"]).casefold(), e["location"] or ""))
    labels = sorted({r.period_label for r in rows})
    # The unit of `periods`: "M" (HMRC months), "A" (CID years), "register" (EIC: months seen listed).
    frequency = max(rows, key=lambda r: r.period_end).frequency
    return {"periods": labels, "first_period": labels[0], "latest_period": labels[-1], "frequency": frequency,
            "companies": companies}


@router.get("/{iso3}")
def companies_country(iso3: str, db: Session = Depends(get_db)):
    code = iso3.upper()
    c = db.get(Country, code)
    if c is None:
        raise HTTPException(404, f"Unknown country {iso3!r}")
    rows = list(db.scalars(_current(db).where(CompanyRecord.country_iso3 == code)
                           .order_by(CompanyRecord.source_id, CompanyRecord.role, CompanyRecord.period_start)))
    sources = {s.id: s for s in db.scalars(select(Source).where(Source.id.in_({r.source_id for r in rows})))}
    groups: dict[tuple[int, str, str, str], list[CompanyRecord]] = defaultdict(list)
    for r in rows:
        groups[(r.source_id, r.role, r.hs_code, r.measure_kind)].append(r)
    role_order = [CompanyRole.EXPORTER.value, CompanyRole.IMPORTER.value, CompanyRole.REGISTERED_EXPORTER.value]
    lists = []
    for (sid, role, hs, kind), rs in sorted(groups.items(), key=lambda kv: (role_order.index(kv[0][1]), kv[0][0])):
        src = sources.get(sid)
        newest = max(rs, key=lambda r: (r.period_end, r.collected_at))
        body = _register_list(rs) if kind == MeasureKind.NONE.value else _figures_list(rs, src)
        lists.append({
            "role": role, "hs_code": hs, "measure_kind": kind, "source": _source_info(src),
            "source_url": newest.source_url, "web_url": (newest.extra or {}).get("web_ui") or (src.homepage if src else None),
            "published_at": iso(max((r.published_at for r in rs if r.published_at), default=None)),
            "collected_at": iso(max(r.collected_at for r in rs)), "last_seen_at": iso(max(r.last_seen_at for r in rs)),
            "reliability": newest.reliability, "is_demo": any(r.is_demo for r in rs), "notes": newest.notes,
            "company_count": len({_register_key(r) for r in rs}),
            **body,
        })
    return {"country": _country_ref(c), "availability": availability_for(code), "checked_on": CHECKED_ON,
            "lists": lists}
