"""Country reference data.

`m49` is the UN M49 / ISO 3166-1 numeric code. NOTE: UN Comtrade uses a few non-ISO
reporter codes (USA 842, France 251, Italy 380 is fine, India 699, Switzerland 757,
Norway 579) — collectors should prefer the ISO3 fields the APIs return and only fall back
to `COMTRADE_CODE_OVERRIDES` / `lookup_iso3()`.

`profile` holds *background reference* (typical varieties and harvest windows) that is
curated, general industry knowledge — it is shown in the UI labelled as background, never
as collected data.
"""
from __future__ import annotations

import re
import unicodedata

# iso3, iso2, m49, fao_code (None when not certain), name_en, name_it, region, lat, lon
_COUNTRIES: list[tuple[str, str, int, int | None, str, str, str, float, float]] = [
    ("ARG", "AR", 32, 9, "Argentina", "Argentina", "South America", -34.0, -64.0),
    ("BRA", "BR", 76, 21, "Brazil", "Brasile", "South America", -10.0, -52.0),
    ("URY", "UY", 858, 234, "Uruguay", "Uruguay", "South America", -32.8, -56.0),
    ("CHL", "CL", 152, 40, "Chile", "Cile", "South America", -35.7, -71.5),
    ("PRY", "PY", 600, 169, "Paraguay", "Paraguay", "South America", -23.4, -58.4),
    ("BOL", "BO", 68, 19, "Bolivia", "Bolivia", "South America", -16.3, -63.6),
    ("PER", "PE", 604, 170, "Peru", "Perù", "South America", -9.2, -75.0),
    ("COL", "CO", 170, 44, "Colombia", "Colombia", "South America", 4.6, -74.1),
    ("MEX", "MX", 484, 138, "Mexico", "Messico", "North America", 23.6, -102.5),
    ("USA", "US", 840, 231, "United States", "Stati Uniti", "North America", 39.8, -98.6),
    ("CAN", "CA", 124, 33, "Canada", "Canada", "North America", 56.1, -106.3),
    ("CUB", "CU", 192, 49, "Cuba", "Cuba", "Central America & Caribbean", 21.5, -79.5),
    ("GTM", "GT", 320, 89, "Guatemala", "Guatemala", "Central America & Caribbean", 15.8, -90.2),
    ("SLV", "SV", 222, 60, "El Salvador", "El Salvador", "Central America & Caribbean", 13.8, -88.9),
    ("NIC", "NI", 558, 157, "Nicaragua", "Nicaragua", "Central America & Caribbean", 12.9, -85.2),
    ("ITA", "IT", 380, 106, "Italy", "Italia", "Europe", 42.8, 12.5),
    ("ESP", "ES", 724, 203, "Spain", "Spagna", "Europe", 40.4, -3.7),
    ("PRT", "PT", 620, 174, "Portugal", "Portogallo", "Europe", 39.6, -8.0),
    ("FRA", "FR", 250, 68, "France", "Francia", "Europe", 46.6, 2.4),
    ("DEU", "DE", 276, 79, "Germany", "Germania", "Europe", 51.2, 10.4),
    ("BEL", "BE", 56, 255, "Belgium", "Belgio", "Europe", 50.6, 4.6),
    ("NLD", "NL", 528, 150, "Netherlands", "Paesi Bassi", "Europe", 52.2, 5.5),
    ("LUX", "LU", 442, 256, "Luxembourg", "Lussemburgo", "Europe", 49.8, 6.1),
    ("AUT", "AT", 40, 11, "Austria", "Austria", "Europe", 47.6, 14.1),
    ("CHE", "CH", 756, 211, "Switzerland", "Svizzera", "Europe", 46.8, 8.2),
    ("GBR", "GB", 826, 229, "United Kingdom", "Regno Unito", "Europe", 54.0, -2.5),
    ("IRL", "IE", 372, 104, "Ireland", "Irlanda", "Europe", 53.2, -8.2),
    ("DNK", "DK", 208, 54, "Denmark", "Danimarca", "Europe", 56.0, 10.0),
    ("SWE", "SE", 752, 210, "Sweden", "Svezia", "Europe", 62.0, 15.0),
    ("FIN", "FI", 246, 67, "Finland", "Finlandia", "Europe", 64.0, 26.0),
    ("NOR", "NO", 578, 162, "Norway", "Norvegia", "Europe", 61.0, 9.0),
    ("POL", "PL", 616, 173, "Poland", "Polonia", "Europe", 52.1, 19.4),
    ("CZE", "CZ", 203, 167, "Czechia", "Cechia", "Europe", 49.8, 15.5),
    ("SVK", "SK", 703, 199, "Slovakia", "Slovacchia", "Europe", 48.7, 19.7),
    ("HUN", "HU", 348, 97, "Hungary", "Ungheria", "Europe", 47.2, 19.5),
    ("ROU", "RO", 642, 183, "Romania", "Romania", "Europe", 45.9, 25.0),
    ("BGR", "BG", 100, 27, "Bulgaria", "Bulgaria", "Europe", 42.7, 25.5),
    ("GRC", "GR", 300, 84, "Greece", "Grecia", "Europe", 39.1, 22.0),
    ("HRV", "HR", 191, 98, "Croatia", "Croazia", "Europe", 45.1, 15.2),
    ("SVN", "SI", 705, 198, "Slovenia", "Slovenia", "Europe", 46.1, 14.9),
    ("SRB", "RS", 688, 272, "Serbia", "Serbia", "Europe", 44.0, 20.9),
    ("BIH", "BA", 70, 80, "Bosnia and Herzegovina", "Bosnia ed Erzegovina", "Europe", 43.9, 17.7),
    ("MNE", "ME", 499, 273, "Montenegro", "Montenegro", "Europe", 42.7, 19.4),
    ("MKD", "MK", 807, 154, "North Macedonia", "Macedonia del Nord", "Europe", 41.6, 21.7),
    ("ALB", "AL", 8, 3, "Albania", "Albania", "Europe", 41.2, 20.2),
    ("LTU", "LT", 440, 126, "Lithuania", "Lituania", "Europe", 55.2, 23.9),
    ("LVA", "LV", 428, 119, "Latvia", "Lettonia", "Europe", 56.9, 24.6),
    ("EST", "EE", 233, 63, "Estonia", "Estonia", "Europe", 58.6, 25.0),
    ("CYP", "CY", 196, 50, "Cyprus", "Cipro", "Europe", 35.1, 33.4),
    ("MLT", "MT", 470, 134, "Malta", "Malta", "Europe", 35.9, 14.4),
    ("UKR", "UA", 804, 230, "Ukraine", "Ucraina", "Europe", 48.4, 31.2),
    ("MDA", "MD", 498, 146, "Moldova", "Moldavia", "Europe", 47.4, 28.4),
    ("BLR", "BY", 112, 57, "Belarus", "Bielorussia", "Europe", 53.7, 27.9),
    ("RUS", "RU", 643, 185, "Russia", "Russia", "Europe", 61.5, 105.3),
    ("TUR", "TR", 792, 223, "Turkey", "Turchia", "Middle East", 39.0, 35.2),
    ("CHN", "CN", 156, 41, "China", "Cina", "Asia", 35.9, 104.2),
    ("HKG", "HK", 344, 96, "Hong Kong", "Hong Kong", "Asia", 22.3, 114.2),
    ("TWN", "TW", 158, 214, "Taiwan", "Taiwan", "Asia", 23.7, 121.0),
    ("IND", "IN", 356, 100, "India", "India", "Asia", 20.6, 79.0),
    ("PAK", "PK", 586, 165, "Pakistan", "Pakistan", "Asia", 30.4, 69.3),
    ("VNM", "VN", 704, 237, "Vietnam", "Vietnam", "Asia", 14.1, 108.3),
    ("THA", "TH", 764, 216, "Thailand", "Thailandia", "Asia", 15.9, 101.0),
    ("MMR", "MM", 104, 28, "Myanmar", "Myanmar", "Asia", 21.9, 95.9),
    ("MYS", "MY", 458, 131, "Malaysia", "Malaysia", "Asia", 4.2, 102.0),
    ("IDN", "ID", 360, 101, "Indonesia", "Indonesia", "Asia", -0.8, 113.9),
    ("PHL", "PH", 608, 171, "Philippines", "Filippine", "Asia", 12.9, 121.8),
    ("JPN", "JP", 392, 110, "Japan", "Giappone", "Asia", 36.2, 138.3),
    ("KOR", "KR", 410, 117, "South Korea", "Corea del Sud", "Asia", 35.9, 127.8),
    ("KAZ", "KZ", 398, 108, "Kazakhstan", "Kazakistan", "Asia", 48.0, 66.9),
    ("KGZ", "KG", 417, 113, "Kyrgyzstan", "Kirghizistan", "Asia", 41.2, 74.8),
    ("IRN", "IR", 364, 102, "Iran", "Iran", "Middle East", 32.4, 53.7),
    ("ISR", "IL", 376, 105, "Israel", "Israele", "Middle East", 31.0, 34.9),
    ("SAU", "SA", 682, 194, "Saudi Arabia", "Arabia Saudita", "Middle East", 23.9, 45.1),
    ("ARE", "AE", 784, 225, "United Arab Emirates", "Emirati Arabi Uniti", "Middle East", 23.4, 53.8),
    ("JOR", "JO", 400, 112, "Jordan", "Giordania", "Middle East", 30.6, 36.2),
    ("KWT", "KW", 414, 118, "Kuwait", "Kuwait", "Middle East", 29.3, 47.5),
    ("QAT", "QA", 634, 179, "Qatar", "Qatar", "Middle East", 25.4, 51.2),
    ("OMN", "OM", 512, 221, "Oman", "Oman", "Middle East", 21.5, 55.9),
    ("LBN", "LB", 422, 121, "Lebanon", "Libano", "Middle East", 33.9, 35.9),
    ("YEM", "YE", 887, 249, "Yemen", "Yemen", "Middle East", 15.6, 48.5),
    ("EGY", "EG", 818, 59, "Egypt", "Egitto", "Africa", 26.8, 30.8),
    ("MAR", "MA", 504, 143, "Morocco", "Marocco", "Africa", 31.8, -7.1),
    ("DZA", "DZ", 12, 4, "Algeria", "Algeria", "Africa", 28.0, 1.7),
    ("TUN", "TN", 788, 222, "Tunisia", "Tunisia", "Africa", 33.9, 9.5),
    ("ETH", "ET", 231, 238, "Ethiopia", "Etiopia", "Africa", 9.1, 40.5),
    ("KEN", "KE", 404, 114, "Kenya", "Kenya", "Africa", -0.0, 37.9),
    ("TZA", "TZ", 834, 215, "Tanzania", "Tanzania", "Africa", -6.4, 34.9),
    ("ZAF", "ZA", 710, 202, "South Africa", "Sudafrica", "Africa", -30.6, 22.9),
    ("AUS", "AU", 36, 10, "Australia", "Australia", "Oceania", -25.3, 133.8),
    ("NZL", "NZ", 554, 156, "New Zealand", "Nuova Zelanda", "Oceania", -40.9, 174.9),
    # Added after the first live run (Nov 2026): origins named by RASFF (Nepal, Syria, Singapore),
    # FAOSTAT and Comtrade honey data. FAO area codes and M49 codes checked against the FAOSTAT
    # honey extracts (tests/fixtures/reference/faostat_areas.csv); lat/lon are approximate centroids.
    ("HND", "HN", 340, 95, "Honduras", "Honduras", "Central America & Caribbean", 15.2, -86.2),
    ("CRI", "CR", 188, 48, "Costa Rica", "Costa Rica", "Central America & Caribbean", 9.7, -83.8),
    ("PAN", "PA", 591, 166, "Panama", "Panama", "Central America & Caribbean", 8.5, -80.8),
    ("BLZ", "BZ", 84, 23, "Belize", "Belize", "Central America & Caribbean", 17.2, -88.5),
    ("DOM", "DO", 214, 56, "Dominican Republic", "Repubblica Dominicana", "Central America & Caribbean", 18.7, -70.2),
    ("HTI", "HT", 332, 93, "Haiti", "Haiti", "Central America & Caribbean", 19.0, -72.3),
    ("JAM", "JM", 388, 109, "Jamaica", "Giamaica", "Central America & Caribbean", 18.1, -77.3),
    ("ECU", "EC", 218, 58, "Ecuador", "Ecuador", "South America", -1.8, -78.2),
    ("VEN", "VE", 862, 236, "Venezuela", "Venezuela", "South America", 6.4, -66.6),
    ("GEO", "GE", 268, 73, "Georgia", "Georgia", "Asia", 42.3, 43.4),
    ("ARM", "AM", 51, 1, "Armenia", "Armenia", "Asia", 40.1, 45.0),
    ("AZE", "AZ", 31, 52, "Azerbaijan", "Azerbaigian", "Asia", 40.1, 47.6),
    ("UZB", "UZ", 860, 235, "Uzbekistan", "Uzbekistan", "Asia", 41.4, 64.6),
    ("TJK", "TJ", 762, 208, "Tajikistan", "Tagikistan", "Asia", 38.9, 71.3),
    ("AFG", "AF", 4, 2, "Afghanistan", "Afghanistan", "Asia", 33.9, 67.7),
    ("NPL", "NP", 524, 149, "Nepal", "Nepal", "Asia", 28.4, 84.1),
    ("BGD", "BD", 50, 16, "Bangladesh", "Bangladesh", "Asia", 23.7, 90.4),
    ("LKA", "LK", 144, 38, "Sri Lanka", "Sri Lanka", "Asia", 7.9, 80.8),
    ("MNG", "MN", 496, 141, "Mongolia", "Mongolia", "Asia", 46.9, 103.8),
    ("LAO", "LA", 418, 120, "Laos", "Laos", "Asia", 19.9, 102.5),
    ("KHM", "KH", 116, 115, "Cambodia", "Cambogia", "Asia", 12.6, 105.0),
    ("SGP", "SG", 702, 200, "Singapore", "Singapore", "Asia", 1.35, 103.8),
    ("SYR", "SY", 760, 212, "Syria", "Siria", "Middle East", 34.8, 39.0),
    ("IRQ", "IQ", 368, 103, "Iraq", "Iraq", "Middle East", 33.2, 43.7),
    ("SEN", "SN", 686, 195, "Senegal", "Senegal", "Africa", 14.5, -14.5),
    ("BFA", "BF", 854, 233, "Burkina Faso", "Burkina Faso", "Africa", 12.2, -1.6),
    ("GHA", "GH", 288, 81, "Ghana", "Ghana", "Africa", 7.9, -1.0),
    ("NGA", "NG", 566, 159, "Nigeria", "Nigeria", "Africa", 9.1, 8.7),
    ("CMR", "CM", 120, 32, "Cameroon", "Camerun", "Africa", 7.4, 12.4),
    ("CAF", "CF", 140, 37, "Central African Republic", "Repubblica Centrafricana", "Africa", 6.6, 20.9),
    ("COD", "CD", 180, 250, "DR Congo", "Repubblica Democratica del Congo", "Africa", -4.0, 21.8),
    ("UGA", "UG", 800, 226, "Uganda", "Uganda", "Africa", 1.4, 32.3),
    ("RWA", "RW", 646, 184, "Rwanda", "Ruanda", "Africa", -1.9, 29.9),
    ("AGO", "AO", 24, 7, "Angola", "Angola", "Africa", -11.2, 17.9),
    ("ZMB", "ZM", 894, 251, "Zambia", "Zambia", "Africa", -13.1, 27.8),
    ("MWI", "MW", 454, 130, "Malawi", "Malawi", "Africa", -13.3, 34.3),
    ("MOZ", "MZ", 508, 144, "Mozambique", "Mozambico", "Africa", -18.7, 35.5),
    ("ZWE", "ZW", 716, 181, "Zimbabwe", "Zimbabwe", "Africa", -19.0, 29.2),
    ("MDG", "MG", 450, 129, "Madagascar", "Madagascar", "Africa", -18.8, 46.9),
    ("NCL", "NC", 540, 153, "New Caledonia", "Nuova Caledonia", "Oceania", -20.9, 165.6),
]

PRIORITY_ISO3: list[str] = [
    "ARG", "BRA", "URY", "CHL", "ITA", "ESP", "DEU", "UKR", "HUN", "ROU",
    "CHN", "IND", "VNM", "USA", "MEX", "CAN", "AUS", "NZL", "TUR", "SRB",
]

# UN Comtrade reporter codes that differ from ISO numeric.
COMTRADE_CODE_OVERRIDES: dict[int, str] = {842: "USA", 251: "FRA", 699: "IND", 757: "CHE", 579: "NOR", 490: "TWN"}

# Pseudo-codes for aggregates
AGGREGATES: dict[str, dict[str, str]] = {
    "WLD": {"name_en": "World", "name_it": "Mondo"},
    "EU27": {"name_en": "European Union (27)", "name_it": "Unione Europea (27)"},
    "EXTRA_EU": {"name_en": "Extra-EU", "name_it": "Extra-UE"},
}

# Curated background (NOT collected data — shown labelled "background reference").
_PROFILES: dict[str, dict] = {
    "ARG": {"varieties": ["polyflora", "clover"], "harvest": "Nov–Apr",
            "notes_en": "One of the world's largest exporters; mostly light multifloral/pampas honey shipped in 300 kg drums.",
            "notes_it": "Tra i maggiori esportatori mondiali; prevalentemente millefiori chiaro della Pampa spedito in fusti da 300 kg."},
    "BRA": {"varieties": ["polyflora", "eucalyptus", "organic_polyflora"], "harvest": "year-round, peaks Sep–Mar",
            "notes_en": "Large organic-certified exporter (Piauí, Ceará, Rio Grande do Sul).",
            "notes_it": "Importante esportatore di miele biologico (Piauí, Ceará, Rio Grande do Sul)."},
    "URY": {"varieties": ["polyflora", "eucalyptus"], "harvest": "Nov–Apr",
            "notes_en": "Export-oriented light multifloral and eucalyptus honey.",
            "notes_it": "Millefiori chiaro ed eucalipto destinati all'export."},
    "CHL": {"varieties": ["polyflora"], "harvest": "Nov–Mar",
            "notes_en": "Native-flora multifloral (ulmo, quillay); EU is a key market.",
            "notes_it": "Millefiori di flora nativa (ulmo, quillay); l'UE è un mercato chiave."},
    "ITA": {"varieties": ["acacia", "polyflora", "chestnut", "orange_blossom", "linden", "sunflower", "eucalyptus", "honeydew", "dandelion"], "harvest": "Apr–Sep",
            "notes_en": "Large domestic producer and net importer; wide range of monofloral honeys.",
            "notes_it": "Importante produttore e importatore netto; ampia gamma di mieli uniflorali."},
    "ESP": {"varieties": ["polyflora", "orange_blossom", "lavender", "eucalyptus", "rapeseed"], "harvest": "Mar–Oct",
            "notes_en": "EU's largest producer by colonies; orange blossom, rosemary, lavender.",
            "notes_it": "Primo produttore UE per numero di alveari; arancio, rosmarino, lavanda."},
    "DEU": {"varieties": ["rapeseed", "polyflora", "linden"], "harvest": "May–Aug",
            "notes_en": "Europe's largest honey importer and a major re-exporter/packer.",
            "notes_it": "Primo importatore europeo e grande riesportatore/confezionatore."},
    "UKR": {"varieties": ["sunflower", "polyflora", "acacia", "rapeseed", "buckwheat"], "harvest": "May–Sep",
            "notes_en": "Europe's largest producer; large EU supplier (sunflower, acacia, rapeseed).",
            "notes_it": "Primo produttore europeo; grande fornitore dell'UE (girasole, acacia, colza)."},
    "HUN": {"varieties": ["acacia", "polyflora", "sunflower", "rapeseed"], "harvest": "May–Aug",
            "notes_en": "Benchmark acacia origin in Europe.",
            "notes_it": "Origine di riferimento per l'acacia in Europa."},
    "ROU": {"varieties": ["acacia", "polyflora", "sunflower", "linden", "rapeseed"], "harvest": "May–Aug",
            "notes_en": "Major EU producer and exporter; acacia and sunflower.",
            "notes_it": "Grande produttore ed esportatore UE; acacia e girasole."},
    "CHN": {"varieties": ["polyflora", "acacia", "rapeseed", "linden", "buckwheat"], "harvest": "Apr–Sep",
            "notes_en": "World's largest producer and exporter; subject to US anti-dumping duties and EU adulteration scrutiny.",
            "notes_it": "Primo produttore ed esportatore mondiale; soggetto a dazi antidumping USA e controlli UE sulle adulterazioni."},
    "IND": {"varieties": ["polyflora", "rapeseed", "eucalyptus"], "harvest": "Oct–Jun",
            "notes_en": "Fast-growing exporter, mainly to the USA (mustard/rapeseed, multifloral).",
            "notes_it": "Esportatore in forte crescita, soprattutto verso gli USA (senape/colza, millefiori)."},
    "VNM": {"varieties": ["polyflora"], "harvest": "Mar–Jul",
            "notes_en": "Export-oriented producer (mostly to the USA); US anti-dumping order since 2022.",
            "notes_it": "Produzione destinata all'export (soprattutto USA); dazio antidumping USA dal 2022."},
    "USA": {"varieties": ["clover", "polyflora", "orange_blossom", "buckwheat"], "harvest": "May–Sep",
            "notes_en": "World's largest importer; USDA National Honey Report is the reference for bulk prices.",
            "notes_it": "Primo importatore mondiale; l'USDA National Honey Report è il riferimento per i prezzi all'ingrosso."},
    "MEX": {"varieties": ["polyflora", "orange_blossom"], "harvest": "Mar–Jun (Yucatán)",
            "notes_en": "Yucatán peninsula is the main export region; EU (Germany) is a key market.",
            "notes_it": "La penisola dello Yucatán è la principale area di export; l'UE (Germania) è un mercato chiave."},
    "CAN": {"varieties": ["clover", "polyflora"], "harvest": "Jul–Sep",
            "notes_en": "Prairie white clover/canola honey; exports mostly to the USA and Japan.",
            "notes_it": "Miele bianco di trifoglio/canola delle praterie; export verso USA e Giappone."},
    "AUS": {"varieties": ["eucalyptus", "polyflora"], "harvest": "year-round, region-dependent",
            "notes_en": "Eucalyptus-dominated production; exports to Asia and the USA.",
            "notes_it": "Produzione dominata dall'eucalipto; export verso Asia e USA."},
    "NZL": {"varieties": ["manuka", "clover", "polyflora"], "harvest": "Dec–Mar",
            "notes_en": "High-value mānuka; also clover and multifloral.",
            "notes_it": "Mānuka ad alto valore; anche trifoglio e millefiori."},
    "TUR": {"varieties": ["polyflora", "honeydew"], "harvest": "Jun–Sep",
            "notes_en": "Second-largest producer globally by volume; mainly domestic consumption, pine honeydew exports.",
            "notes_it": "Secondo produttore mondiale per volume; consumo prevalentemente interno, export di melata di pino."},
    "SRB": {"varieties": ["acacia", "polyflora", "sunflower", "linden"], "harvest": "May–Aug",
            "notes_en": "Quality acacia origin with EU preferential access (SAA).",
            "notes_it": "Origine di acacia di qualità con accesso preferenziale UE (ASA)."},
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


_ALIASES: dict[str, str] = {
    "usa": "USA", "u s a": "USA", "us": "USA", "united states of america": "USA", "stati uniti d america": "USA",
    "estados unidos": "USA", "viet nam": "VNM", "turkiye": "TUR", "republic of turkiye": "TUR",
    "china mainland": "CHN", "china mainland 41": "CHN", "people s republic of china": "CHN", "repubblica popolare cinese": "CHN",
    "russian federation": "RUS", "iran islamic republic of": "IRN", "republic of korea": "KOR", "korea republic of": "KOR",
    "korea rep": "KOR", "rep of korea": "KOR", "republic of moldova": "MDA", "moldova republic of": "MDA",
    "netherlands kingdom of the": "NLD", "the netherlands": "NLD", "holland": "NLD", "olanda": "NLD",
    "united kingdom of great britain and northern ireland": "GBR", "uk": "GBR", "great britain": "GBR",
    "bolivia plurinational state of": "BOL", "united republic of tanzania": "TZA", "czech republic": "CZE",
    "repubblica ceca": "CZE", "china hong kong sar": "HKG", "hong kong sar": "HKG", "china hong kong": "HKG",
    "china taiwan province of": "TWN", "chinese taipei": "TWN", "other asia nes": "TWN",
    "the former yugoslav republic of macedonia": "MKD", "macedonia": "MKD", "serbia and montenegro": "SRB",
    "ucrania": "UKR", "brasil": "BRA", "mexique": "MEX", "mexico": "MEX", "messico": "MEX", "argentine": "ARG",
    "espana": "ESP", "espagne": "ESP", "allemagne": "DEU", "alemania": "DEU", "deutschland": "DEU",
    "ungarn": "HUN", "hongrie": "HUN", "rumania": "ROU", "roumanie": "ROU", "vietnam": "VNM",
    "uae": "ARE", "emirati arabi": "ARE", "south korea": "KOR", "corea": "KOR", "cina": "CHN",
    "nuova zelanda": "NZL", "nueva zelanda": "NZL", "turchia": "TUR", "turquia": "TUR",
    "world": "WLD", "mondo": "WLD", "all countries": "WLD", "total": "WLD",
    "european union": "EU27", "eu27 2020": "EU27", "eu 27": "EU27", "eu27": "EU27", "unione europea": "EU27",
    "extra eu27 2020": "EXTRA_EU", "extra eu": "EXTRA_EU",
    # Official long forms (FAOSTAT, UN Comtrade, RASFF) of the countries added in Nov 2026.
    "syrian arab republic": "SYR", "lao people s democratic republic": "LAO", "lao pdr": "LAO",
    "lao people s dem rep": "LAO", "democratic republic of the congo": "COD", "dem rep of the congo": "COD",
    "congo democratic republic of the": "COD", "venezuela bolivarian republic of": "VEN",
    "central african rep": "CAF", "dominican rep": "DOM", "republica dominicana": "DOM",
}


def countries() -> list[dict]:
    out = []
    for iso3, iso2, m49, fao, en, it, region, lat, lon in _COUNTRIES:
        out.append(
            {
                "iso3": iso3, "iso2": iso2, "m49": m49, "fao_code": fao, "name_en": en, "name_it": it,
                "region": region, "lat": lat, "lon": lon, "priority": iso3 in PRIORITY_ISO3,
                "profile": _PROFILES.get(iso3),
            }
        )
    return out


_BY_NAME: dict[str, str] = {}
_BY_ISO2: dict[str, str] = {}
_BY_M49: dict[int, str] = {}
_BY_FAO: dict[int, str] = {}
_ISO3: set[str] = set()
for _iso3, _iso2, _m49, _fao, _en, _it, *_ in _COUNTRIES:
    _ISO3.add(_iso3)
    _BY_NAME[_norm(_en)] = _iso3
    _BY_NAME[_norm(_it)] = _iso3
    _BY_ISO2[_iso2] = _iso3
    _BY_M49[_m49] = _iso3
    if _fao:
        _BY_FAO[_fao] = _iso3
for _k, _v in _ALIASES.items():
    _BY_NAME[_norm(_k)] = _v


def is_known_iso3(code: str | None) -> bool:
    return bool(code) and (code in _ISO3 or code in AGGREGATES)


def lookup_iso3(value: str | int | None) -> str | None:
    """Resolve a country from ISO3, ISO2, M49 number or (EN/IT/ES/FR/DE) name. None if unknown."""
    if value is None:
        return None
    if isinstance(value, int) or (isinstance(value, str) and value.strip().isdigit()):
        n = int(value)
        return COMTRADE_CODE_OVERRIDES.get(n) or _BY_M49.get(n) or ("WLD" if n == 0 else None)
    v = value.strip()
    if len(v) == 3 and v.upper() in _ISO3:
        return v.upper()
    if len(v) == 2 and v.upper() in _BY_ISO2:
        return _BY_ISO2[v.upper()]
    if v.upper() == "EL":  # Eurostat uses EL for Greece
        return "GRC"
    if v.upper() in AGGREGATES:
        return v.upper()
    return _BY_NAME.get(_norm(v))


def lookup_fao(code: int | str | None) -> str | None:
    if code is None:
        return None
    try:
        return _BY_FAO.get(int(code))
    except (TypeError, ValueError):
        return None


def country_name(iso3: str | None, lang: str = "it") -> str:
    if not iso3:
        return ""
    if iso3 in AGGREGATES:
        return AGGREGATES[iso3]["name_it" if lang == "it" else "name_en"]
    for c in _COUNTRIES:
        if c[0] == iso3:
            return c[5] if lang == "it" else c[4]
    return iso3


# Words used to tag news by country (lower-case, matched on word boundaries).
COUNTRY_KEYWORDS: dict[str, list[str]] = {
    "ARG": ["argentina", "argentine", "argentino", "argentinian", "buenos aires", "entre rios", "entre ríos"],
    "BRA": ["brazil", "brasil", "brasile", "brazilian", "piaui", "piauí"],
    "URY": ["uruguay", "uruguayan", "uruguaiano"],
    "CHL": ["chile", "chilean", "cile", "cileno"],
    "ITA": ["italy", "italia", "italian", "italiano", "italiana", "osservatorio nazionale miele", "conapi"],
    "ESP": ["spain", "spanish", "españa", "spagna", "spagnolo"],
    "DEU": ["germany", "german", "germania", "deutschland"],
    "UKR": ["ukraine", "ukrainian", "ucraina", "ucraino"],
    "HUN": ["hungary", "hungarian", "ungheria"],
    "ROU": ["romania", "romanian", "rumeno"],
    "CHN": ["china", "chinese", "cina", "cinese"],
    "IND": ["india", "indian", "indiano"],
    "VNM": ["vietnam", "viet nam", "vietnamese"],
    "USA": ["united states", "u.s.", "usda", "american honey", "stati uniti", "fda"],  # not "usa": it is also an Italian verb
    "MEX": ["mexico", "mexican", "messico", "yucatan", "yucatán"],
    "CAN": ["canada", "canadian", "canadese"],
    "AUS": ["australia", "australian", "australiano"],
    "NZL": ["new zealand", "nuova zelanda", "manuka", "mānuka"],
    "TUR": ["turkey", "türkiye", "turkiye", "turkish", "turchia"],
    "SRB": ["serbia", "serbian", "serbo"],
    "POL": ["poland", "polish", "polonia"],
    "BGR": ["bulgaria", "bulgarian"],
    "GRC": ["greece", "greek", "grecia"],
    "FRA": ["france", "french", "francia"],
    "ETH": ["ethiopia", "ethiopian", "etiopia"],
    "MDA": ["moldova", "moldavia"],
    "THA": ["thailand", "thai"],
    "RUS": ["russia", "russian"],
}
