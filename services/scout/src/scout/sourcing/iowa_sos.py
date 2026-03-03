"""Iowa Secretary of State — active for-profit entities via Socrata SODA API."""

from scout.sourcing.socrata_base import SocrataBusinessSource, SocrataStateConfig

# For-profit entity types (skip nonprofits, government, co-ops)
_FOR_PROFIT_TYPES = (
    "('DOMESTIC PROFIT',"
    "'FOREIGN PROFIT',"
    "'DOMESTIC LIMITED LIABILITY COMPANY',"
    "'FOREIGN LIMITED LIABILITY COMPANY',"
    "'DOMESTIC LIMITED PARTNERSHIP',"
    "'FOREIGN LIMITED PARTNERSHIP',"
    "'DOMESTIC LIMITED LIABILITY PARTNERSHIP',"
    "'FOREIGN LIMITED LIABILITY PARTNERSHIP',"
    "'DOMESTIC LIMITED LIABILITY LIMITED PARTNERSHIP',"
    "'FOREIGN LIMITED LIABILITY LIMITED PARTNERSHIP',"
    "'DOMESTIC PROFESSIONAL LIMITED LIABILITY COMPANY',"
    "'FOREIGN PROFESSIONAL LIMITED LIABILITY COMPANY',"
    "'DOMESTIC PROFESSIONAL',"
    "'FOREIGN PROFESSIONAL')"
)

IOWA_CONFIG = SocrataStateConfig(
    endpoint="https://data.iowa.gov/resource/ez5t-3qay.json",
    source_name="iowa_sos",
    id_field="corp_number",
    name_field="legal_name",
    city_field="ho_city",
    state_field="ho_state",
    date_field="effective_date",
    type_field="corporation_type",
    where_clause=f"corporation_type in {_FOR_PROFIT_TYPES}",
    type_labels={
        "DOMESTIC PROFIT": "Domestic Profit Corporation",
        "FOREIGN PROFIT": "Foreign Profit Corporation",
        "DOMESTIC LIMITED LIABILITY COMPANY": "Domestic LLC",
        "FOREIGN LIMITED LIABILITY COMPANY": "Foreign LLC",
        "DOMESTIC LIMITED PARTNERSHIP": "Domestic Limited Partnership",
        "FOREIGN LIMITED PARTNERSHIP": "Foreign Limited Partnership",
        "DOMESTIC LIMITED LIABILITY PARTNERSHIP": "Domestic LLP",
        "FOREIGN LIMITED LIABILITY PARTNERSHIP": "Foreign LLP",
        "DOMESTIC LIMITED LIABILITY LIMITED PARTNERSHIP": "Domestic LLLP",
        "FOREIGN LIMITED LIABILITY LIMITED PARTNERSHIP": "Foreign LLLP",
        "DOMESTIC PROFESSIONAL LIMITED LIABILITY COMPANY": "Domestic Professional LLC",
        "FOREIGN PROFESSIONAL LIMITED LIABILITY COMPANY": "Foreign Professional LLC",
        "DOMESTIC PROFESSIONAL": "Domestic Professional Corporation",
        "FOREIGN PROFESSIONAL": "Foreign Professional Corporation",
    },
)


class IowaSosSource(SocrataBusinessSource):
    """Iowa Secretary of State — active for-profit entities."""

    def __init__(self) -> None:
        super().__init__(IOWA_CONFIG)
