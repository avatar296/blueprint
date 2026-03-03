"""SEC EDGAR company sourcing — XBRL Frames API for employee counts, Submissions for enrichment."""

import logging
import os
import time

import httpx

from scout.sourcing.base import CompanyRecord, CompanySource

log = logging.getLogger("scout.sourcing.sec_edgar")

# SEC requires a User-Agent with contact email
_FRAMES_URL = (
    "https://data.sec.gov/api/xbrl/companyfacts/frames/"
    "us-gaap/EntityNumberOfEmployees/USD/CY{year}.json"
)
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_REQUEST_DELAY = 0.1  # 10 req/s limit

# Top-level SIC code → industry name mapping
SIC_INDUSTRY: dict[str, str] = {
    "0100": "Agriculture — Crops",
    "0200": "Agriculture — Livestock",
    "1000": "Metal Mining",
    "1200": "Coal Mining",
    "1300": "Oil & Gas Extraction",
    "1400": "Nonmetallic Minerals Mining",
    "1500": "General Building Construction",
    "1600": "Heavy Construction",
    "1700": "Special Trade Construction",
    "2000": "Food & Kindred Products",
    "2100": "Tobacco Products",
    "2200": "Textile Mill Products",
    "2300": "Apparel",
    "2400": "Lumber & Wood Products",
    "2500": "Furniture & Fixtures",
    "2600": "Paper & Allied Products",
    "2700": "Printing & Publishing",
    "2800": "Chemicals & Allied Products",
    "2810": "Industrial Chemicals",
    "2820": "Plastics & Synthetic Materials",
    "2830": "Pharmaceuticals",
    "2834": "Pharmaceutical Preparations",
    "2835": "In Vitro Diagnostics",
    "2836": "Biological Products",
    "2840": "Soap & Cleaning Products",
    "2860": "Industrial Chemicals",
    "2870": "Agricultural Chemicals",
    "2900": "Petroleum Refining",
    "3000": "Rubber & Plastics Products",
    "3100": "Leather Products",
    "3200": "Stone, Clay, Glass Products",
    "3300": "Primary Metal Industries",
    "3400": "Fabricated Metal Products",
    "3500": "Industrial Machinery & Equipment",
    "3559": "Special Industry Machinery",
    "3560": "General Industrial Machinery",
    "3570": "Computer & Office Equipment",
    "3572": "Computer Storage Devices",
    "3576": "Computer Communications Equipment",
    "3577": "Computer Peripherals",
    "3580": "Refrigeration & Heating Equipment",
    "3600": "Electronic & Electrical Equipment",
    "3620": "Electrical Industrial Apparatus",
    "3630": "Household Appliances",
    "3640": "Lighting Equipment",
    "3660": "Communications Equipment",
    "3670": "Electronic Components",
    "3672": "Printed Circuit Boards",
    "3674": "Semiconductors",
    "3679": "Electronic Components NEC",
    "3680": "Electronic Components NEC",
    "3690": "Electronic Components NEC",
    "3700": "Transportation Equipment",
    "3710": "Motor Vehicles",
    "3714": "Motor Vehicle Parts",
    "3720": "Aircraft & Parts",
    "3728": "Aircraft Parts NEC",
    "3740": "Railroad Equipment",
    "3760": "Guided Missiles & Space",
    "3790": "Transportation Equipment NEC",
    "3800": "Instruments & Related Products",
    "3812": "Defense Electronics",
    "3820": "Measuring Instruments",
    "3825": "Instruments for Measurement",
    "3826": "Laboratory Analytical Instruments",
    "3827": "Optical Instruments & Lenses",
    "3829": "Measuring & Controlling Devices",
    "3841": "Surgical & Medical Instruments",
    "3842": "Orthopedic & Prosthetic Devices",
    "3845": "Electromedical Equipment",
    "3851": "Ophthalmic Goods",
    "3861": "Photographic Equipment",
    "3900": "Miscellaneous Manufacturing",
    "4000": "Railroad Transportation",
    "4100": "Transit & Passenger Transport",
    "4200": "Motor Freight & Warehousing",
    "4400": "Water Transportation",
    "4500": "Air Transportation",
    "4510": "Scheduled Air Transportation",
    "4512": "Scheduled Air Transportation",
    "4522": "Air Transportation, Nonscheduled",
    "4580": "Airport Services",
    "4600": "Pipelines",
    "4700": "Transportation Services",
    "4800": "Communications",
    "4810": "Telephone Communications",
    "4812": "Wireless Telecommunications",
    "4813": "Telephone Communications",
    "4820": "Telegraph Communications",
    "4830": "Radio & TV Broadcasting",
    "4833": "Television Broadcasting",
    "4841": "Cable & Pay Television",
    "4899": "Communications NEC",
    "4900": "Electric, Gas & Sanitary Services",
    "4911": "Electric Services",
    "4922": "Natural Gas Distribution",
    "4923": "Natural Gas Transmission",
    "4924": "Natural Gas Distribution",
    "4931": "Electric & Other Services Combined",
    "4932": "Gas & Other Services Combined",
    "4941": "Water Supply",
    "4950": "Sanitary Services",
    "4953": "Refuse Systems",
    "4955": "Hazardous Waste Management",
    "5000": "Durable Goods — Wholesale",
    "5040": "Professional Equipment — Wholesale",
    "5045": "Computers & Peripherals — Wholesale",
    "5047": "Medical Equipment — Wholesale",
    "5050": "Metals & Minerals — Wholesale",
    "5060": "Electrical Apparatus — Wholesale",
    "5065": "Electronic Parts — Wholesale",
    "5080": "Machinery & Equipment — Wholesale",
    "5090": "Durable Goods NEC — Wholesale",
    "5100": "Nondurable Goods — Wholesale",
    "5110": "Paper & Paper Products — Wholesale",
    "5122": "Drugs & Drug Sundries — Wholesale",
    "5130": "Apparel — Wholesale",
    "5140": "Groceries — Wholesale",
    "5150": "Farm Products — Wholesale",
    "5160": "Chemicals — Wholesale",
    "5170": "Petroleum Products — Wholesale",
    "5190": "Nondurable Goods NEC — Wholesale",
    "5200": "Building Materials & Hardware — Retail",
    "5211": "Lumber & Building Materials — Retail",
    "5300": "General Merchandise — Retail",
    "5311": "Department Stores",
    "5331": "Variety Stores",
    "5400": "Food Stores",
    "5411": "Grocery Stores",
    "5500": "Auto Dealers & Gas Stations",
    "5531": "Auto Parts Stores",
    "5600": "Apparel & Accessory Stores",
    "5700": "Home Furniture & Equipment Stores",
    "5712": "Furniture Stores",
    "5731": "Radio, TV & Electronics Stores",
    "5800": "Eating & Drinking Places",
    "5812": "Eating Places",
    "5900": "Retail Stores NEC",
    "5912": "Drug Stores & Pharmacies",
    "5940": "Sporting Goods & Hobby Stores",
    "5944": "Jewelry Stores",
    "5945": "Hobby, Toy & Game Stores",
    "5960": "Nonstore Retailers",
    "5961": "Catalog & Mail Order",
    "5990": "Retail Stores NEC",
    "6000": "Depository Institutions",
    "6020": "State Commercial Banks",
    "6021": "National Commercial Banks",
    "6022": "State Commercial Banks",
    "6035": "Savings Institutions — Federal",
    "6036": "Savings Institutions — State",
    "6099": "Depository Institutions NEC",
    "6100": "Nondepository Credit Institutions",
    "6110": "Federal Credit Agencies",
    "6120": "Savings Institutions",
    "6140": "Personal Credit Institutions",
    "6141": "Personal Credit Institutions",
    "6150": "Business Credit Institutions",
    "6153": "Short-Term Business Credit",
    "6159": "Federal-Sponsored Credit Agencies",
    "6162": "Mortgage Bankers",
    "6163": "Loan Brokers",
    "6199": "Finance NEC",
    "6200": "Security & Commodity Brokers",
    "6211": "Security Brokers & Dealers",
    "6282": "Investment Advice",
    "6311": "Life Insurance",
    "6321": "Accident & Health Insurance",
    "6324": "Hospital & Medical Service Plans",
    "6331": "Fire, Marine & Casualty Insurance",
    "6351": "Surety Insurance",
    "6399": "Insurance Carriers NEC",
    "6411": "Insurance Agents & Brokers",
    "6500": "Real Estate",
    "6510": "Real Estate Operators",
    "6512": "Operators of Apartment Buildings",
    "6519": "Real Property Lessors NEC",
    "6531": "Real Estate Agents & Managers",
    "6552": "Land Subdividers & Developers",
    "6726": "Investment Offices NEC",
    "6770": "Blank Checks",
    "6798": "Real Estate Investment Trusts",
    "7000": "Hotels & Lodging",
    "7011": "Hotels & Motels",
    "7200": "Personal Services",
    "7300": "Business Services",
    "7310": "Advertising Services",
    "7311": "Advertising Services",
    "7320": "Consumer Credit Reporting",
    "7330": "Mailing & Reproduction Services",
    "7340": "Building Services",
    "7350": "Miscellaneous Equipment Rental",
    "7359": "Equipment Rental & Leasing",
    "7361": "Help Supply Services",
    "7363": "Help Supply Services",
    "7370": "Computer & Data Processing Services",
    "7371": "Computer Programming",
    "7372": "Prepackaged Software",
    "7374": "Computer Processing & Data Prep",
    "7380": "Miscellaneous Business Services",
    "7381": "Detective & Armored Car Services",
    "7389": "Services NEC",
    "7500": "Automotive Repair & Services",
    "7510": "Automotive Rentals",
    "7600": "Miscellaneous Repair Services",
    "7812": "Motion Picture Production",
    "7819": "Services Allied to Motion Pictures",
    "7822": "Motion Picture Distribution",
    "7841": "Video Tape Rental",
    "7900": "Amusement & Recreation Services",
    "7941": "Professional Sports Clubs",
    "7990": "Amusement & Recreation NEC",
    "7997": "Membership Sports & Recreation",
    "8000": "Health Services",
    "8011": "Offices of Doctors",
    "8041": "Offices of Chiropractors",
    "8042": "Offices of Optometrists",
    "8049": "Offices of Health Practitioners NEC",
    "8050": "Nursing & Personal Care Facilities",
    "8051": "Skilled Nursing Facilities",
    "8060": "Hospitals",
    "8062": "General Medical & Surgical Hospitals",
    "8071": "Health Services",
    "8082": "Home Health Care Services",
    "8090": "Health Services NEC",
    "8093": "Specialty Outpatient Facilities",
    "8111": "Legal Services",
    "8200": "Educational Services",
    "8300": "Social Services",
    "8351": "Child Day Care Services",
    "8700": "Engineering & Management Services",
    "8711": "Engineering Services",
    "8721": "Accounting & Auditing",
    "8731": "Commercial Physical & Biological Research",
    "8734": "Testing Laboratories",
    "8741": "Management Services",
    "8742": "Management Consulting",
    "8744": "Facilities Support Management",
    "8900": "Services NEC",
    "9100": "Executive, Legislative & General Government",
    "9995": "Nonclassifiable Establishments",
}


def _sic_to_industry(sic: str) -> str | None:
    """Look up industry name from SIC code, trying exact match then prefix."""
    if not sic:
        return None
    # Exact match
    if sic in SIC_INDUSTRY:
        return SIC_INDUSTRY[sic]
    # Try 2-digit prefix (e.g. "3674" → "3600")
    prefix = sic[:2] + "00"
    return SIC_INDUSTRY.get(prefix)


# Map SEC state-of-incorporation codes to US state abbreviations
_SEC_STATE_MAP: dict[str, str] = {
    "AL": "AL", "AK": "AK", "AZ": "AZ", "AR": "AR", "CA": "CA",
    "CO": "CO", "CT": "CT", "DE": "DE", "FL": "FL", "GA": "GA",
    "HI": "HI", "ID": "ID", "IL": "IL", "IN": "IN", "IA": "IA",
    "KS": "KS", "KY": "KY", "LA": "LA", "ME": "ME", "MD": "MD",
    "MA": "MA", "MI": "MI", "MN": "MN", "MS": "MS", "MO": "MO",
    "MT": "MT", "NE": "NE", "NV": "NV", "NH": "NH", "NJ": "NJ",
    "NM": "NM", "NY": "NY", "NC": "NC", "ND": "ND", "OH": "OH",
    "OK": "OK", "OR": "OR", "PA": "PA", "RI": "RI", "SC": "SC",
    "SD": "SD", "TN": "TN", "TX": "TX", "UT": "UT", "VT": "VT",
    "VA": "VA", "WA": "WA", "WV": "WV", "WI": "WI", "WY": "WY",
    "DC": "DC",
}


class SecEdgarSource(CompanySource):
    """Fetch companies with employee counts from SEC EDGAR XBRL Frames API."""

    name = "sec_edgar"

    def __init__(self) -> None:
        self._contact_email = os.environ.get("SCOUT_CONTACT_EMAIL", "")
        if not self._contact_email:
            log.warning("SCOUT_CONTACT_EMAIL not set — SEC EDGAR requires User-Agent with email")

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": f"Blueprint/1.0 ({self._contact_email})",
            "Accept": "application/json",
        }

    def fetch(self) -> list[CompanyRecord]:
        if not self._contact_email:
            log.error("Cannot fetch SEC EDGAR without SCOUT_CONTACT_EMAIL")
            return []

        records = self._fetch_frames()
        log.info("SEC EDGAR: fetched %d companies from Frames API", len(records))

        # Enrich with submissions data (state, SIC, founding)
        enriched = 0
        for rec in records:
            if self._enrich_from_submissions(rec):
                enriched += 1
            time.sleep(_REQUEST_DELAY)

        log.info("SEC EDGAR: enriched %d/%d companies from Submissions API", enriched, len(records))
        return records

    def _fetch_frames(self) -> list[CompanyRecord]:
        """Fetch employee count data from XBRL Frames API.

        Tries current year first, then previous year (filings lag).
        """
        import datetime

        current_year = datetime.date.today().year
        records: list[CompanyRecord] = []

        for year in [current_year, current_year - 1]:
            url = _FRAMES_URL.format(year=year)
            try:
                resp = httpx.get(url, headers=self._headers(), timeout=30.0)
                if resp.status_code != 200:
                    log.debug("Frames API returned %d for year %d", resp.status_code, year)
                    continue

                data = resp.json()
                units = data.get("data", [])
                if not units:
                    continue

                for entry in units:
                    cik = str(entry.get("cik", ""))
                    name = entry.get("entityName", "")
                    val = entry.get("val")

                    if not name or not cik:
                        continue
                    if val is not None and val <= 0:
                        continue

                    records.append(CompanyRecord(
                        name=name,
                        source="sec_edgar",
                        source_id=cik,
                        employee_count=int(val) if val else None,
                    ))

                if records:
                    log.info("Using SEC EDGAR Frames data from year %d", year)
                    break  # got data, no need to try previous year

            except (httpx.HTTPError, ValueError) as exc:
                log.warning("SEC EDGAR Frames API error for year %d: %s", year, exc)

        return records

    def _enrich_from_submissions(self, record: CompanyRecord) -> bool:
        """Enrich a company record with state, SIC code, and industry from Submissions API."""
        if not record.source_id:
            return False

        # CIK needs to be zero-padded to 10 digits
        cik_padded = record.source_id.zfill(10)
        url = _SUBMISSIONS_URL.format(cik=cik_padded)

        try:
            resp = httpx.get(url, headers=self._headers(), timeout=15.0)
            if resp.status_code != 200:
                return False

            data = resp.json()

            # State of incorporation
            state_raw = data.get("stateOfIncorporation", "")
            if state_raw and state_raw in _SEC_STATE_MAP:
                record.state = _SEC_STATE_MAP[state_raw]

            # SIC code and industry
            sic = str(data.get("sic", ""))
            if sic:
                record.sic_code = sic
                record.industry = _sic_to_industry(sic)

            # Website
            website = data.get("website", "")
            if website:
                if not website.startswith("http"):
                    website = f"https://{website}"
                record.website = website

            return True

        except (httpx.HTTPError, ValueError) as exc:
            log.debug("Submissions API error for CIK %s: %s", record.source_id, exc)
            return False
