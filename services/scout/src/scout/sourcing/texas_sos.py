"""Texas Comptroller — active franchise tax permit holders via Socrata SODA API."""

from scout.sourcing.socrata_base import SocrataBusinessSource, SocrataStateConfig

# For-profit org types (skip CN = Corp-Nonprofit — ProPublica covers those)
_FOR_PROFIT_TYPES = "('CL','CT','CI','CF','PL','PF')"

TEXAS_CONFIG = SocrataStateConfig(
    endpoint="https://data.texas.gov/resource/9cir-efmm.json",
    source_name="texas_sos",
    id_field="taxpayer_number",
    name_field="taxpayer_name",
    city_field="taxpayer_city",
    state_field="taxpayer_state",
    date_field="sos_charter_date",
    type_field="taxpayer_organizational_type",
    where_clause=f"taxpayer_organizational_type in {_FOR_PROFIT_TYPES}",
    type_labels={
        "CL": "Limited Liability Company",
        "CT": "Texas Corporation",
        "CI": "Interstate Corporation",
        "CF": "Foreign Corporation",
        "PL": "Limited Partnership",
        "PF": "Foreign Partnership",
    },
)


class TexasSosSource(SocrataBusinessSource):
    """Texas Comptroller — active franchise tax permit holders."""

    def __init__(self) -> None:
        super().__init__(TEXAS_CONFIG)
