# Fixtures for `collectors/trade_uk.py` (`uk_hmrc_honey`)

Every file here is a **real capture**, byte for byte, taken on **2026-11-05** by the first live run of
the collector (copied from its raw archive, `data/raw/uk_hmrc_honey/`). HMRC's uktradeinfo API is open
(no key) and its content is under the Open Government Licence v3.0. Tests build their variants from these
files in code (an earlier release, a revision, suppression, unmapped partners, schema drift). No data
file was typed in by hand.

| File | URL (GET, no key) |
|---|---|
| `real_hmrc_date_2026-11-05.json` | https://api.uktradeinfo.com/Date?$filter=MonthId ge 202101 |
| `real_hmrc_flowtype.json` | https://api.uktradeinfo.com/FlowType |
| `real_hmrc_commodity_0409.json` | https://api.uktradeinfo.com/Commodity?$filter=Hs4Code eq '0409' |
| `real_hmrc_country.json` | https://api.uktradeinfo.com/Country?$select=CountryId,CountryCodeAlpha,CountryName,Area1a |
| `real_hmrc_ots_honey_202301-202608.json` | https://api.uktradeinfo.com/OTS?$apply=filter((CommodityId eq 4090000) and MonthId ge 202301 and MonthId le 202608)/groupby((MonthId,FlowTypeId,SuppressionIndex,CommodityId,CountryId),aggregate(Value with sum as Value,NetMass with sum as NetMass)) |
| `real_govuk_ots_release_august-2026.json` | https://www.gov.uk/api/content/government/statistics/uk-overseas-trade-in-goods-statistics-august-2026 |

(The collector sends the same queries URL-encoded by httpx.)

What the captures show (used as test expectations):

* HMRC's month table ends at 202608: August 2026 is the newest month, released on 15 October 2026 at
  09:30 UK time (`first_published_at` of the GOV.UK release page). The next releases are 12 November 2026
  (September) and 11 December 2026 (October).
* Heading 0409 has one UK commodity line: CommodityId 4090000, CN8 04090000 "Natural honey".
* The OTS answer has 2,313 rows (month x flow type x partner, ports summed by HMRC's server), none
  suppressed. Summing the 4,758 per-port rows of the same period ourselves (captured with curl the same
  day) gives the same figures row by row.
* UK imports 2024: 60,303,816 kg, GBP 97,023,258 (UN Comtrade: 60,306.6 t). 2025: 58,974,881 kg,
  GBP 98,914,122 (Comtrade: 58,977.7 t). 2023: 50,923,029 kg (Comtrade 50,969.4 t, FAOSTAT 50,927.2 t).
* August 2026 imports: total GBP 11,283,353 / 5,937,521 kg, of which EU flow types GBP 2,973,343 /
  741,002 kg; New Zealand GBP 2,071,920 / 181,530 kg; China 3,542,032 kg at GBP 0.7784/kg CIF.
* Serbia appears once (October 2023) under HMRC's own code XS.
