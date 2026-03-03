"""New York Department of State — active for-profit entities via Socrata SODA API."""

from scout.sourcing.socrata_base import SocrataBusinessSource, SocrataStateConfig

# For-profit entity types (skip nonprofits — ProPublica covers those)
_FOR_PROFIT_TYPES = (
    "('DOMESTIC BUSINESS CORPORATION',"
    "'FOREIGN BUSINESS CORPORATION',"
    "'DOMESTIC LIMITED LIABILITY COMPANY',"
    "'FOREIGN LIMITED LIABILITY COMPANY',"
    "'DOMESTIC LIMITED PARTNERSHIP',"
    "'FOREIGN LIMITED PARTNERSHIP')"
)

NEWYORK_CONFIG = SocrataStateConfig(
    endpoint="https://data.ny.gov/resource/n9v6-gdp6.json",
    source_name="newyork_sos",
    id_field="dos_id",
    name_field="current_entity_name",
    city_field="dos_process_city",
    state_field="dos_process_state",
    date_field="initial_dos_filing_date",
    type_field="entity_type",
    where_clause=f"entity_type in {_FOR_PROFIT_TYPES}",
    type_labels={
        "DOMESTIC BUSINESS CORPORATION": "Domestic Business Corporation",
        "FOREIGN BUSINESS CORPORATION": "Foreign Business Corporation",
        "DOMESTIC LIMITED LIABILITY COMPANY": "Domestic LLC",
        "FOREIGN LIMITED LIABILITY COMPANY": "Foreign LLC",
        "DOMESTIC LIMITED PARTNERSHIP": "Domestic Limited Partnership",
        "FOREIGN LIMITED PARTNERSHIP": "Foreign Limited Partnership",
    },
)


class NewYorkSosSource(SocrataBusinessSource):
    """New York Department of State — active for-profit corporations and LLCs."""

    def __init__(self) -> None:
        super().__init__(NEWYORK_CONFIG)
