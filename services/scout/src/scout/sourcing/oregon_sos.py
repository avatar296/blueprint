"""Oregon Secretary of State — active for-profit entities via Socrata SODA API."""

from scout.sourcing.socrata_base import SocrataBusinessSource, SocrataStateConfig

# For-profit entity types (skip nonprofits — ProPublica covers those)
_FOR_PROFIT_TYPES = (
    "('DOMESTIC LIMITED LIABILITY COMPANY',"
    "'DOMESTIC BUSINESS CORPORATION',"
    "'FOREIGN LIMITED LIABILITY COMPANY',"
    "'FOREIGN BUSINESS CORPORATION',"
    "'DOMESTIC PROFESSIONAL CORPORATION',"
    "'FOREIGN PROFESSIONAL CORPORATION',"
    "'DOMESTIC LIMITED PARTNERSHIP',"
    "'FOREIGN LIMITED PARTNERSHIP',"
    "'DOMESTIC REGISTERED LIMITED LIABILITY PARTNERSHIP',"
    "'FOREIGN REGISTERED LIMITED LIABILITY PARTNERSHIP')"
)

OREGON_CONFIG = SocrataStateConfig(
    endpoint="https://data.oregon.gov/resource/tckn-sxa6.json",
    source_name="oregon_sos",
    id_field="registry_number",
    name_field="business_name",
    city_field="city",
    state_field="state",
    date_field="registry_date",
    type_field="entity_type",
    where_clause=(
        f"entity_type in {_FOR_PROFIT_TYPES}"
        " AND associated_name_type='PRINCIPAL PLACE OF BUSINESS'"
    ),
    type_labels={
        "DOMESTIC LIMITED LIABILITY COMPANY": "Domestic LLC",
        "DOMESTIC BUSINESS CORPORATION": "Domestic Business Corporation",
        "FOREIGN LIMITED LIABILITY COMPANY": "Foreign LLC",
        "FOREIGN BUSINESS CORPORATION": "Foreign Business Corporation",
        "DOMESTIC PROFESSIONAL CORPORATION": "Domestic Professional Corporation",
        "FOREIGN PROFESSIONAL CORPORATION": "Foreign Professional Corporation",
        "DOMESTIC LIMITED PARTNERSHIP": "Domestic Limited Partnership",
        "FOREIGN LIMITED PARTNERSHIP": "Foreign Limited Partnership",
        "DOMESTIC REGISTERED LIMITED LIABILITY PARTNERSHIP": "Domestic LLP",
        "FOREIGN REGISTERED LIMITED LIABILITY PARTNERSHIP": "Foreign LLP",
    },
)


class OregonSosSource(SocrataBusinessSource):
    """Oregon Secretary of State — active for-profit entities."""

    def __init__(self) -> None:
        super().__init__(OREGON_CONFIG)
