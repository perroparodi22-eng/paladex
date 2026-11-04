"""Honey production regions (Milestone 5: harvest & weather).

Each region has 1-4 representative points (lat/lon) at which the weather collector
(`collectors/weather.py`, NASA POWER) reads monthly temperature and precipitation, plus curated
BACKGROUND CONTEXT: main honey types and the usual flowering / harvest months.

The context is general industry knowledge, curated by hand and NOT collected data: the UI shows
it labelled as "contesto" (never as a fact from a source). The months are indicative windows for
the main honey flows; real seasons move from year to year and between districts. Only the
flowering months are used by the rule-based "drought watch" / "wet season" flags (see
`api/harvest.py`), and the rules state that openly.

Points are chosen in the main beekeeping districts of each region, inland, at least one NASA POWER
grid cell (0.5° x 0.625°) apart, so no two points ask the service for the same data.

Keys are stable identifiers: they are part of the stored weather series keys
("<point key>|YYYY-MM"), so a point must never be renamed; move or retire it instead.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Point:
    key: str            # unique across all regions, e.g. "ARG-BA-azul"
    name: str           # place name (as used locally)
    lat: float
    lon: float


@dataclass(frozen=True)
class Region:
    key: str                          # e.g. "ARG-BA"
    country_iso3: str
    name_it: str
    name_en: str
    points: tuple[Point, ...]
    varieties_it: tuple[str, ...]     # main honey types (context)
    varieties_en: tuple[str, ...]
    flowering_months: tuple[int, ...]  # 1-12, main nectar / honeydew flow (context)
    harvest_months: tuple[int, ...]    # 1-12, usual extraction window (context)
    note_it: str = ""
    note_en: str = ""

    @property
    def hemisphere(self) -> str:
        lat = sum(p.lat for p in self.points) / len(self.points)
        return "S" if lat < 0 else "N"


def months(start: int, end: int) -> tuple[int, ...]:
    """Inclusive month window, wrapping over the new year: months(10, 3) -> (10, 11, 12, 1, 2, 3)."""
    if not (1 <= start <= 12 and 1 <= end <= 12):
        raise ValueError("months are 1-12")
    out, m = [], start
    while True:
        out.append(m)
        if m == end:
            return tuple(out)
        m = m % 12 + 1


def _p(key: str, name: str, lat: float, lon: float) -> Point:
    return Point(key, name, lat, lon)


# Shared variety wordings (IT / EN)
_PAMPA_IT = ("Millefiori della Pampa (trifoglio, erba medica, girasole)", "Eucalipto")
_PAMPA_EN = ("Pampas multifloral (clover, alfalfa, sunflower)", "Eucalyptus")
_CAATINGA_IT = ("Millefiori della caatinga (spesso biologico)", "Marmeleiro", "Anacardio (cajueiro)")
_CAATINGA_EN = ("Caatinga multifloral (often organic)", "Marmeleiro", "Cashew (cajueiro)")
_PLAINS_IT = ("Trifoglio", "Erba medica", "Colza (canola)", "Girasole")
_PLAINS_EN = ("Clover", "Alfalfa", "Canola", "Sunflower")
_DANUBE_IT = ("Acacia", "Girasole", "Colza", "Tiglio", "Millefiori")
_DANUBE_EN = ("Acacia (black locust)", "Sunflower", "Rapeseed", "Linden", "Multifloral")
_UKR_IT = ("Girasole", "Colza", "Acacia", "Tiglio", "Grano saraceno", "Millefiori")
_UKR_EN = ("Sunflower", "Rapeseed", "Acacia (black locust)", "Linden", "Buckwheat", "Multifloral")
_YUC_IT = ("Tajonal", "Dzidzilché", "Millefiori della penisola")
_YUC_EN = ("Tajonal", "Dzidzilché", "Peninsula multifloral")
_PRAIRIE_IT = ("Colza (canola)", "Trifoglio", "Erba medica")
_PRAIRIE_EN = ("Canola", "Clover", "Alfalfa")
_EU_CENTRAL_IT = ("Colza", "Acacia", "Tiglio", "Grano saraceno", "Millefiori")
_EU_CENTRAL_EN = ("Rapeseed", "Acacia (black locust)", "Linden", "Buckwheat", "Multifloral")

REGIONS: tuple[Region, ...] = (
    # ------------------------------------------------------------------ South America
    Region("ARG-BA", "ARG", "Buenos Aires (provincia)", "Buenos Aires province",
           (_p("ARG-BA-azul", "Azul", -36.78, -59.86), _p("ARG-BA-pehuajo", "Pehuajó", -35.81, -61.90),
            _p("ARG-BA-tresarroyos", "Tres Arroyos", -38.38, -60.28)),
           _PAMPA_IT, _PAMPA_EN, months(10, 3), months(12, 4),
           "Prima provincia apistica argentina: miele chiaro esportato in fusti da 300 kg.",
           "Argentina's leading beekeeping province: light honey exported in 300 kg drums."),
    Region("ARG-ER", "ARG", "Entre Ríos", "Entre Ríos",
           (_p("ARG-ER-villaguay", "Villaguay", -31.87, -59.03), _p("ARG-ER-gualeguaychu", "Gualeguaychú", -33.01, -58.52)),
           ("Millefiori", "Eucalipto", "Agrumi (zona di Concordia)", "Trifoglio e lotus"),
           ("Multifloral", "Eucalyptus", "Citrus (Concordia area)", "Clover and lotus"), months(9, 3), months(11, 4)),
    Region("ARG-SF", "ARG", "Santa Fe", "Santa Fe",
           (_p("ARG-SF-rafaela", "Rafaela", -31.25, -61.49), _p("ARG-SF-reconquista", "Reconquista", -29.15, -59.65)),
           ("Millefiori", "Flora nativa del nord (algarrobo)", "Trifoglio ed erba medica"),
           ("Multifloral", "Northern native flora (algarrobo)", "Clover and alfalfa"), months(9, 3), months(11, 4)),
    Region("ARG-CB", "ARG", "Córdoba", "Córdoba",
           (_p("ARG-CB-riocuarto", "Río Cuarto", -33.13, -64.35), _p("ARG-CB-villamaria", "Villa María", -32.41, -63.24)),
           _PAMPA_IT, _PAMPA_EN, months(10, 3), months(12, 4)),
    Region("ARG-LP", "ARG", "La Pampa", "La Pampa",
           (_p("ARG-LP-generalpico", "General Pico", -35.66, -63.76), _p("ARG-LP-santarosa", "Santa Rosa", -36.62, -64.29)),
           ("Millefiori della Pampa", "Flora nativa (caldén, jarilla)"), ("Pampas multifloral", "Native flora (caldén, jarilla)"),
           months(10, 3), months(12, 4)),
    Region("URY-LIT", "URY", "Uruguay (litorale e centro)", "Uruguay (west and centre)",
           (_p("URY-paysandu", "Paysandú", -32.32, -58.08), _p("URY-mercedes", "Mercedes (Soriano)", -33.25, -58.03),
            _p("URY-durazno", "Durazno", -33.38, -56.52)),
           ("Millefiori di prateria", "Eucalipto", "Trifoglio e lotus"), ("Grassland multifloral", "Eucalyptus", "Clover and lotus"),
           months(9, 3), months(11, 4), "Miele chiaro in gran parte destinato all'export.", "Light honey, mostly exported."),
    Region("BRA-PI", "BRA", "Piauí", "Piauí",
           (_p("BRA-PI-picos", "Picos", -7.08, -41.47), _p("BRA-PI-saoraimundo", "São Raimundo Nonato", -9.02, -42.70)),
           _CAATINGA_IT, _CAATINGA_EN, months(1, 6), months(2, 7),
           "Fioritura legata alla stagione delle piogge del semiarido: una siccità la riduce subito.",
           "Flowering follows the semi-arid rainy season: a drought cuts it at once."),
    Region("BRA-CE", "BRA", "Ceará", "Ceará",
           (_p("BRA-CE-limoeiro", "Limoeiro do Norte", -5.15, -38.10), _p("BRA-CE-crato", "Crato", -7.23, -39.41)),
           _CAATINGA_IT, _CAATINGA_EN, months(2, 6), months(3, 7)),
    Region("BRA-PR", "BRA", "Paraná", "Paraná",
           (_p("BRA-PR-prudentopolis", "Prudentópolis", -25.21, -50.98), _p("BRA-PR-ortigueira", "Ortigueira", -24.21, -50.95)),
           ("Millefiori", "Eucalipto", "Flora nativa della foresta atlantica"), ("Multifloral", "Eucalyptus", "Atlantic forest flora"),
           months(8, 3), months(10, 4)),
    Region("BRA-SC", "BRA", "Santa Catarina", "Santa Catarina",
           (_p("BRA-SC-lages", "Lages", -27.82, -50.33), _p("BRA-SC-chapeco", "Chapecó", -27.10, -52.62)),
           ("Millefiori", "Eucalipto", "Melata di bracatinga (altopiano, anni alterni)"),
           ("Multifloral", "Eucalyptus", "Bracatinga honeydew (highlands, alternate years)"), months(9, 3), months(11, 4)),
    Region("BRA-RS", "BRA", "Rio Grande do Sul", "Rio Grande do Sul",
           (_p("BRA-RS-santamaria", "Santa Maria", -29.69, -53.81), _p("BRA-RS-vacaria", "Vacaria", -28.51, -50.93)),
           ("Millefiori", "Eucalipto", "Uva-do-japão (autunno)"), ("Multifloral", "Eucalyptus", "Japanese raisin tree (autumn)"),
           months(9, 3), months(11, 4)),
    Region("BRA-MG", "BRA", "Minas Gerais", "Minas Gerais",
           (_p("BRA-MG-lavras", "Lavras", -21.25, -45.00), _p("BRA-MG-montesclaros", "Montes Claros", -16.73, -43.86)),
           ("Millefiori (assa-peixe)", "Eucalipto", "Caffè"), ("Multifloral (assa-peixe)", "Eucalyptus", "Coffee"),
           months(4, 9), months(5, 10)),
    Region("CHL-CS", "CHL", "Cile centro-meridionale", "South-central Chile",
           (_p("CHL-talca", "Talca", -35.43, -71.66), _p("CHL-losangeles", "Los Ángeles", -37.47, -72.35),
            _p("CHL-temuco", "Temuco", -38.74, -72.60)),
           ("Millefiori di flora nativa (quillay, ulmo, tevo)",), ("Native-flora multifloral (quillay, ulmo, tevo)",),
           months(9, 2), months(12, 3)),
    # ------------------------------------------------------------------ Mexico
    Region("MEX-YUC", "MEX", "Yucatán", "Yucatán",
           (_p("MEX-YUC-merida", "Mérida", 20.97, -89.62), _p("MEX-YUC-tizimin", "Tizimín", 21.14, -88.15)),
           _YUC_IT, _YUC_EN, months(11, 5), months(2, 6),
           "Raccolto nella stagione secca; la stagione delle piogge (giugno-ottobre) è di riposo.",
           "Harvest in the dry season; the rainy season (June-October) is the rest period."),
    Region("MEX-CAM", "MEX", "Campeche", "Campeche",
           (_p("MEX-CAM-hopelchen", "Hopelchén", 19.75, -89.85), _p("MEX-CAM-escarcega", "Escárcega", 18.61, -90.74)),
           _YUC_IT, _YUC_EN, months(11, 5), months(2, 6)),
    Region("MEX-JAL", "MEX", "Jalisco", "Jalisco",
           (_p("MEX-JAL-autlan", "Autlán", 19.77, -104.37), _p("MEX-JAL-tepatitlan", "Tepatitlán", 20.82, -102.76)),
           ("Millefiori d'autunno (aceitilla, acahual)",), ("Autumn multifloral (aceitilla, acahual)",),
           months(9, 12), months(10, 1), "Fioritura dopo le piogge estive.", "Flowering after the summer rains."),
    Region("MEX-VER", "MEX", "Veracruz", "Veracruz",
           (_p("MEX-VER-martinez", "Martínez de la Torre", 20.07, -97.06), _p("MEX-VER-coatepec", "Coatepec", 19.45, -96.96)),
           ("Fiori d'arancio", "Caffè", "Millefiori"), ("Orange blossom", "Coffee", "Multifloral"), months(2, 5), months(3, 6)),
    # ------------------------------------------------------------------ USA, Canada
    Region("USA-ND", "USA", "Dakota del Nord", "North Dakota",
           (_p("USA-ND-jamestown", "Jamestown", 46.91, -98.71), _p("USA-ND-minot", "Minot", 48.23, -101.29)),
           _PLAINS_IT, _PLAINS_EN, months(6, 8), months(7, 9),
           "Primo stato produttore degli Stati Uniti.", "Leading US honey-producing state."),
    Region("USA-SD", "USA", "Dakota del Sud", "South Dakota",
           (_p("USA-SD-huron", "Huron", 44.36, -98.21), _p("USA-SD-aberdeen", "Aberdeen", 45.46, -98.49)),
           _PLAINS_IT, _PLAINS_EN, months(6, 8), months(7, 9)),
    Region("USA-MT", "USA", "Montana", "Montana",
           (_p("USA-MT-billings", "Billings", 45.78, -108.50), _p("USA-MT-kalispell", "Kalispell", 48.20, -114.31)),
           ("Trifoglio", "Erba medica", "Millefiori"), ("Clover", "Alfalfa", "Multifloral"), months(6, 8), months(7, 9)),
    Region("USA-CA", "USA", "California", "California",
           (_p("USA-CA-fresno", "Fresno", 36.74, -119.79), _p("USA-CA-riverside", "Riverside", 33.95, -117.40)),
           ("Fiori d'arancio", "Salvia", "Grano saraceno selvatico", "Erba medica"),
           ("Orange blossom", "Sage", "Wild buckwheat", "Alfalfa"), months(2, 7), months(4, 8),
           "A febbraio gran parte degli alveari è impegnata nell'impollinazione dei mandorli.",
           "In February most colonies are busy with almond pollination."),
    Region("USA-FL", "USA", "Florida", "Florida",
           (_p("USA-FL-lakewales", "Lake Wales", 27.90, -81.59), _p("USA-FL-wewahitchka", "Wewahitchka", 30.11, -85.20)),
           ("Fiori d'arancio", "Tupelo", "Palmetto"), ("Orange blossom", "Tupelo", "Saw palmetto"), months(2, 6), months(3, 7)),
    Region("USA-TX", "USA", "Texas", "Texas",
           (_p("USA-TX-waco", "Waco", 31.55, -97.15), _p("USA-TX-uvalde", "Uvalde", 29.21, -99.79)),
           ("Mesquite", "Huajillo", "Cotone", "Millefiori"), ("Mesquite", "Huajillo", "Cotton", "Multifloral"),
           months(3, 7), months(5, 8)),
    Region("CAN-AB", "CAN", "Alberta", "Alberta",
           (_p("CAN-AB-grandeprairie", "Grande Prairie", 55.17, -118.80), _p("CAN-AB-reddeer", "Red Deer", 52.27, -113.81)),
           _PRAIRIE_IT, _PRAIRIE_EN, months(6, 8), months(7, 9), "Prima provincia produttrice del Canada.",
           "Canada's leading honey-producing province."),
    Region("CAN-SK", "CAN", "Saskatchewan", "Saskatchewan",
           (_p("CAN-SK-saskatoon", "Saskatoon", 52.13, -106.67), _p("CAN-SK-nipawin", "Nipawin", 53.37, -104.00)),
           _PRAIRIE_IT, _PRAIRIE_EN, months(6, 8), months(7, 9)),
    Region("CAN-MB", "CAN", "Manitoba", "Manitoba",
           (_p("CAN-MB-dauphin", "Dauphin", 51.15, -100.05), _p("CAN-MB-portage", "Portage la Prairie", 49.97, -98.29)),
           _PRAIRIE_IT, _PRAIRIE_EN, months(6, 8), months(7, 9)),
    # ------------------------------------------------------------------ Ukraine, Danube & Balkans
    Region("UKR-VIN", "UKR", "Oblast di Vinnycja", "Vinnytsia oblast",
           (_p("UKR-VIN-vinnytsia", "Vinnytsia", 49.23, 28.47),), _UKR_IT, _UKR_EN, months(4, 8), months(5, 9)),
    Region("UKR-POL", "UKR", "Oblast di Poltava", "Poltava oblast",
           (_p("UKR-POL-poltava", "Poltava", 49.59, 34.55),), _UKR_IT, _UKR_EN, months(4, 8), months(5, 9)),
    Region("UKR-KIR", "UKR", "Oblast di Kirovohrad", "Kirovohrad oblast",
           (_p("UKR-KIR-kropyvnytskyi", "Kropyvnytskyi", 48.51, 32.26),), _UKR_IT, _UKR_EN, months(4, 8), months(5, 9)),
    Region("UKR-DNI", "UKR", "Oblast di Dnipropetrovsk", "Dnipropetrovsk oblast",
           (_p("UKR-DNI-dnipro", "Dnipro", 48.46, 35.05),), _UKR_IT, _UKR_EN, months(4, 8), months(5, 9)),
    Region("UKR-ODE", "UKR", "Oblast di Odesa (nord)", "Odesa oblast (north)",
           (_p("UKR-ODE-podilsk", "Podilsk", 47.75, 29.53),), _UKR_IT, _UKR_EN, months(4, 8), months(5, 9)),
    Region("UKR-ZAK", "UKR", "Transcarpazia", "Zakarpattia",
           (_p("UKR-ZAK-mukachevo", "Mukachevo", 48.44, 22.72),), ("Acacia", "Tiglio", "Millefiori di montagna"),
           ("Acacia (black locust)", "Linden", "Mountain multifloral"), months(4, 7), months(5, 8)),
    Region("HUN", "HUN", "Ungheria (Grande Pianura, Nyírség, Somogy)", "Hungary (Great Plain, Nyírség, Somogy)",
           (_p("HUN-kecskemet", "Kecskemét", 46.91, 19.69), _p("HUN-nyiregyhaza", "Nyíregyháza", 47.95, 21.72),
            _p("HUN-kaposvar", "Kaposvár", 46.36, 17.80)),
           _DANUBE_IT, _DANUBE_EN, months(4, 8), months(5, 9),
           "Acacia ungherese: fioritura di maggio, molto sensibile a gelate tardive e piogge.",
           "Hungarian acacia: May flowering, very sensitive to late frost and rain."),
    Region("ROU", "ROU", "Romania (Bărăgan, Moldavia, Oltenia)", "Romania (Bărăgan, Moldavia, Oltenia)",
           (_p("ROU-slobozia", "Slobozia", 44.56, 27.37), _p("ROU-iasi", "Iași", 47.16, 27.59),
            _p("ROU-craiova", "Craiova", 44.32, 23.80)),
           _DANUBE_IT, _DANUBE_EN, months(4, 8), months(5, 9)),
    Region("BGR", "BGR", "Bulgaria (Dobrugia, pianura danubiana)", "Bulgaria (Dobruja, Danube plain)",
           (_p("BGR-dobrich", "Dobrich", 43.57, 27.83), _p("BGR-pleven", "Pleven", 43.42, 24.62)),
           _DANUBE_IT, _DANUBE_EN, months(4, 8), months(5, 9)),
    Region("SRB", "SRB", "Serbia (Voivodina, Serbia centrale)", "Serbia (Vojvodina, central Serbia)",
           (_p("SRB-novisad", "Novi Sad", 45.26, 19.83), _p("SRB-kraljevo", "Kraljevo", 43.72, 20.69)),
           ("Acacia", "Tiglio", "Girasole", "Millefiori"), ("Acacia (black locust)", "Linden", "Sunflower", "Multifloral"),
           months(4, 8), months(5, 9)),
    Region("MDA", "MDA", "Moldavia", "Moldova",
           (_p("MDA-balti", "Bălți", 47.76, 27.93), _p("MDA-cahul", "Cahul", 45.91, 28.19)),
           ("Acacia", "Girasole", "Tiglio", "Millefiori"), ("Acacia (black locust)", "Sunflower", "Linden", "Multifloral"),
           months(4, 8), months(5, 9)),
    # ------------------------------------------------------------------ Italy, Spain
    Region("ITA-PIE", "ITA", "Piemonte", "Piedmont",
           (_p("ITA-PIE-cuneo", "Cuneo", 44.39, 7.55), _p("ITA-PIE-asti", "Asti", 44.90, 8.21)),
           ("Acacia", "Castagno", "Tiglio", "Rododendro", "Millefiori"), ("Acacia", "Chestnut", "Linden", "Rhododendron", "Multifloral"),
           months(4, 7), months(5, 8)),
    Region("ITA-LOM", "ITA", "Lombardia", "Lombardy",
           (_p("ITA-LOM-bergamo", "Bergamo", 45.70, 9.67), _p("ITA-LOM-voghera", "Voghera (Oltrepò)", 44.99, 9.01)),
           ("Acacia", "Castagno", "Tiglio", "Millefiori"), ("Acacia", "Chestnut", "Linden", "Multifloral"), months(4, 7), months(5, 8)),
    Region("ITA-EMR", "ITA", "Emilia-Romagna", "Emilia-Romagna",
           (_p("ITA-EMR-bologna", "Bologna", 44.49, 11.34), _p("ITA-EMR-forli", "Forlì", 44.22, 12.04)),
           ("Acacia", "Millefiori", "Erba medica", "Tiglio"), ("Acacia", "Multifloral", "Alfalfa", "Linden"), months(4, 8), months(5, 9)),
    Region("ITA-TOS", "ITA", "Toscana", "Tuscany",
           (_p("ITA-TOS-siena", "Siena", 43.32, 11.33), _p("ITA-TOS-grosseto", "Grosseto", 42.76, 11.11)),
           ("Acacia", "Castagno", "Girasole", "Millefiori", "Melata"), ("Acacia", "Chestnut", "Sunflower", "Multifloral", "Honeydew"),
           months(4, 8), months(5, 9)),
    Region("ITA-SIC", "ITA", "Sicilia", "Sicily",
           (_p("ITA-SIC-lentini", "Lentini (Piana di Catania)", 37.29, 14.99), _p("ITA-SIC-ragusa", "Ragusa", 36.93, 14.73)),
           ("Agrumi", "Sulla", "Timo", "Eucalipto", "Castagno (Etna)"), ("Citrus", "Sulla", "Thyme", "Eucalyptus", "Chestnut (Etna)"),
           months(2, 7), months(4, 8)),
    Region("ITA-CAL", "ITA", "Calabria", "Calabria",
           (_p("ITA-CAL-sibari", "Piana di Sibari", 39.75, 16.45), _p("ITA-CAL-gioiatauro", "Piana di Gioia Tauro", 38.43, 15.90)),
           ("Agrumi", "Sulla", "Castagno", "Eucalipto"), ("Citrus", "Sulla", "Chestnut", "Eucalyptus"), months(3, 7), months(4, 8)),
    Region("ESP-VC", "ESP", "Comunità Valenciana", "Valencian Community",
           (_p("ESP-VC-alzira", "Alzira", 39.15, -0.43), _p("ESP-VC-segorbe", "Segorbe", 39.85, -0.49)),
           ("Fiori d'arancio (azahar)", "Rosmarino", "Millefiori"), ("Orange blossom (azahar)", "Rosemary", "Multifloral"),
           months(1, 6), months(3, 7)),
    Region("ESP-EXT", "ESP", "Estremadura", "Extremadura",
           (_p("ESP-EXT-plasencia", "Plasencia", 40.03, -6.09), _p("ESP-EXT-badajoz", "Badajoz", 38.88, -6.97)),
           ("Erica", "Lavanda selvatica (cantueso)", "Eucalipto", "Melata di leccio"),
           ("Heather", "Wild lavender (cantueso)", "Eucalyptus", "Holm-oak honeydew"), months(3, 7), months(5, 9),
           "Prima regione apistica spagnola per numero di alveari.", "Spain's leading region by number of hives."),
    Region("ESP-AND", "ESP", "Andalusia", "Andalusia",
           (_p("ESP-AND-almonte", "Almonte (Huelva)", 37.26, -6.52), _p("ESP-AND-granada", "Granada", 37.18, -3.60)),
           ("Eucalipto", "Fiori d'arancio", "Rosmarino", "Millefiori"), ("Eucalyptus", "Orange blossom", "Rosemary", "Multifloral"),
           months(2, 7), months(4, 8)),
    Region("ESP-CLM", "ESP", "Castiglia-La Mancia", "Castilla-La Mancha",
           (_p("ESP-CLM-brihuega", "Brihuega (Alcarria)", 40.76, -2.87), _p("ESP-CLM-albacete", "Albacete", 38.99, -1.86)),
           ("Rosmarino", "Lavanda", "Timo", "Millefiori"), ("Rosemary", "Lavender", "Thyme", "Multifloral"), months(4, 7), months(6, 9)),
    # ------------------------------------------------------------------ Turkey, Central & Northern Europe
    Region("TUR-MUG", "TUR", "Muğla", "Muğla",
           (_p("TUR-MUG-mugla", "Muğla", 37.22, 28.36),), ("Melata di pino (çam balı)",), ("Pine honeydew (çam balı)",),
           months(7, 11), months(9, 11),
           "Melata prodotta dall'insetto Marchalina hellenica sui pini: i mesi indicati sono il periodo di flusso, non una fioritura.",
           "Honeydew produced by the Marchalina hellenica insect on pines: the months are the flow period, not a flowering."),
    Region("TUR-ORD", "TUR", "Ordu (Mar Nero)", "Ordu (Black Sea)",
           (_p("TUR-ORD-ordu", "Ordu", 40.98, 37.88),), ("Castagno", "Millefiori del Mar Nero"), ("Chestnut", "Black Sea multifloral"),
           months(6, 8), months(7, 9)),
    Region("DEU", "DEU", "Germania (Brandeburgo, Baviera, Bassa Sassonia)", "Germany (Brandenburg, Bavaria, Lower Saxony)",
           (_p("DEU-beelitz", "Beelitz (Brandeburgo)", 52.24, 12.97), _p("DEU-freising", "Freising (Baviera)", 48.40, 11.75),
            _p("DEU-soltau", "Soltau (Lüneburger Heide)", 52.99, 9.84)),
           ("Colza", "Acacia", "Tiglio", "Erica", "Millefiori"), ("Rapeseed", "Acacia (black locust)", "Linden", "Heather", "Multifloral"),
           months(4, 8), months(5, 9)),
    Region("POL", "POL", "Polonia (Lublino, Podlachia, Opole)", "Poland (Lublin, Podlasie, Opole)",
           (_p("POL-lublin", "Lublino", 51.25, 22.57), _p("POL-bialystok", "Białystok", 53.13, 23.16),
            _p("POL-opole", "Opole", 50.67, 17.93)),
           _EU_CENTRAL_IT, _EU_CENTRAL_EN, months(4, 8), months(5, 9)),
    # ------------------------------------------------------------------ Asia
    Region("CHN-HEN", "CHN", "Henan", "Henan",
           (_p("CHN-HEN-sanmenxia", "Sanmenxia", 34.77, 111.20), _p("CHN-HEN-zhumadian", "Zhumadian", 32.98, 114.02)),
           ("Robinia (acacia)", "Colza", "Giuggiolo", "Vitex"), ("Black locust (acacia)", "Rapeseed", "Jujube", "Vitex"),
           months(3, 8), months(4, 9)),
    Region("CHN-SHD", "CHN", "Shandong", "Shandong",
           (_p("CHN-SHD-linyi", "Linyi", 35.10, 118.35), _p("CHN-SHD-yantai", "Yantai", 37.46, 121.45)),
           ("Robinia (acacia)", "Giuggiolo", "Castagno"), ("Black locust (acacia)", "Jujube", "Chestnut"), months(4, 8), months(5, 9)),
    Region("CHN-SCH", "CHN", "Sichuan", "Sichuan",
           (_p("CHN-SCH-deyang", "Deyang", 31.13, 104.40), _p("CHN-SCH-nanchong", "Nanchong", 30.84, 106.11)),
           ("Colza", "Millefiori"), ("Rapeseed", "Multifloral"), months(2, 6), months(3, 7),
           "La colza fiorisce tra febbraio e aprile: è il primo raccolto dell'anno in Cina.",
           "Rapeseed flowers from February to April: China's first crop of the year."),
    Region("CHN-HUB", "CHN", "Hubei", "Hubei",
           (_p("CHN-HUB-jingzhou", "Jingzhou", 30.33, 112.24), _p("CHN-HUB-xiangyang", "Xiangyang", 32.01, 112.12)),
           ("Colza", "Robinia (acacia)", "Millefiori"), ("Rapeseed", "Black locust (acacia)", "Multifloral"), months(3, 7), months(3, 8)),
    Region("CHN-ZJ", "CHN", "Zhejiang", "Zhejiang",
           (_p("CHN-ZJ-jiangshan", "Jiangshan", 28.74, 118.63), _p("CHN-ZJ-huzhou", "Huzhou", 30.87, 120.09)),
           ("Colza", "Astragalo cinese", "Millefiori"), ("Rapeseed", "Chinese milk vetch", "Multifloral"), months(3, 6), months(3, 7),
           "Molti apicoltori sono nomadi e seguono le fioriture in altre province.",
           "Many beekeepers are migratory and follow the flowering into other provinces."),
    Region("CHN-HLJ", "CHN", "Heilongjiang", "Heilongjiang",
           (_p("CHN-HLJ-hulin", "Hulin", 45.77, 132.98), _p("CHN-HLJ-yichun", "Yichun", 47.73, 128.84)),
           ("Tiglio", "Soia", "Millefiori"), ("Linden (basswood)", "Soybean", "Multifloral"), months(6, 8), months(7, 8)),
    Region("VNM", "VNM", "Vietnam (Altipiani centrali, Sud-Est, delta del Fiume Rosso)", "Vietnam (Central Highlands, Southeast, Red River delta)",
           (_p("VNM-buonmathuot", "Buôn Ma Thuột", 12.67, 108.04), _p("VNM-dongxoai", "Đồng Xoài", 11.54, 106.90),
            _p("VNM-hungyen", "Hưng Yên", 20.65, 106.05)),
           ("Caucciù", "Caffè", "Longan e litchi (nord)"), ("Rubber tree", "Coffee", "Longan and lychee (north)"),
           months(1, 4), months(2, 5)),
    Region("IND-PB", "IND", "Punjab", "Punjab",
           (_p("IND-PB-ludhiana", "Ludhiana", 30.90, 75.85), _p("IND-PB-patiala", "Patiala", 30.34, 76.39)),
           ("Senape", "Eucalipto", "Berseem (trifoglio egiziano)"), ("Mustard", "Eucalyptus", "Berseem clover"),
           months(11, 4), months(12, 5)),
    Region("IND-UP", "IND", "Uttar Pradesh", "Uttar Pradesh",
           (_p("IND-UP-saharanpur", "Saharanpur", 29.96, 77.55), _p("IND-UP-lucknow", "Lucknow", 26.85, 80.95)),
           ("Senape", "Eucalipto", "Millefiori"), ("Mustard", "Eucalyptus", "Multifloral"), months(11, 4), months(12, 5)),
    Region("IND-BR", "IND", "Bihar", "Bihar",
           (_p("IND-BR-muzaffarpur", "Muzaffarpur", 26.12, 85.39),), ("Litchi", "Senape"), ("Lychee", "Mustard"),
           months(12, 4), months(1, 5)),
    # ------------------------------------------------------------------ Oceania, Africa
    Region("AUS", "AUS", "Australia (Nuovo Galles del Sud, Victoria, Australia Occidentale)",
           "Australia (New South Wales, Victoria, Western Australia)",
           (_p("AUS-dubbo", "Dubbo (NSW)", -32.25, 148.60), _p("AUS-wangaratta", "Wangaratta (VIC)", -36.36, 146.31),
            _p("AUS-manjimup", "Manjimup (WA)", -34.24, 116.15)),
           ("Eucalipti (yellow box, red gum, jarrah)", "Colza", "Millefiori"),
           ("Eucalypts (yellow box, red gum, jarrah)", "Canola", "Multifloral"), months(9, 3), months(10, 4),
           "Le fioriture degli eucalipti cambiano molto da un anno all'altro.", "Eucalypt flowering varies a lot from year to year."),
    Region("NZL", "NZL", "Nuova Zelanda (Isola del Nord, Canterbury)", "New Zealand (North Island, Canterbury)",
           (_p("NZL-rotorua", "Rotorua", -38.14, 176.25), _p("NZL-gisborne", "Gisborne", -38.66, 178.02),
            _p("NZL-ashburton", "Ashburton (Canterbury)", -43.90, 171.75)),
           ("Mānuka", "Kānuka", "Trifoglio", "Millefiori"), ("Mānuka", "Kānuka", "Clover", "Multifloral"), months(10, 2), months(12, 3)),
    Region("ETH", "ETH", "Etiopia (Amhara, Oromia, Tigray)", "Ethiopia (Amhara, Oromia, Tigray)",
           (_p("ETH-bahirdar", "Bahir Dar", 11.59, 37.39), _p("ETH-jimma", "Jimma", 7.67, 36.83),
            _p("ETH-mekelle", "Mekelle", 13.50, 39.47)),
           ("Millefiori degli altipiani (Bidens, Croton)", "Eucalipto"), ("Highland multifloral (Bidens, Croton)", "Eucalyptus"),
           months(9, 11), months(10, 12),
           "Raccolto principale dopo le grandi piogge estive; una seconda stagione minore cade in aprile-giugno.",
           "Main harvest after the summer rains; a second, smaller season falls in April-June."),
)

_BY_KEY = {r.key: r for r in REGIONS}
_POINT_REGION = {p.key: r for r in REGIONS for p in r.points}


def all_regions() -> tuple[Region, ...]:
    return REGIONS


def get_region(key: str) -> Region | None:
    return _BY_KEY.get(key)


def region_of_point(point_key: str) -> Region | None:
    return _POINT_REGION.get(point_key)


def all_points() -> list[tuple[Region, Point]]:
    return [(r, p) for r in REGIONS for p in r.points]


def countries() -> list[str]:
    """ISO3 codes covered by at least one region, in the order they first appear."""
    return list(dict.fromkeys(r.country_iso3 for r in REGIONS))


def context(region: Region) -> dict:
    """Curated background for the UI (always labelled as context, never as data)."""
    return {
        "varieties_it": list(region.varieties_it), "varieties_en": list(region.varieties_en),
        "flowering_months": list(region.flowering_months), "harvest_months": list(region.harvest_months),
        "note_it": region.note_it or None, "note_en": region.note_en or None,
        "hemisphere": region.hemisphere, "is_context": True,
    }
