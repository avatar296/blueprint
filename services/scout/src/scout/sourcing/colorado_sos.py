"""Colorado Secretary of State — active for-profit entities via Socrata SODA API."""

from scout.sourcing.socrata_base import SocrataBusinessSource, SocrataStateConfig

# Active statuses (skip Dissolved, Withdrawn, etc.)
_ACTIVE_STATUSES = "('Good Standing','Delinquent','Exists','Noncompliant')"

# For-profit entity types (skip DNC/FNC nonprofits — ProPublica covers those)
_FOR_PROFIT_TYPES = "('DLLC','DPC','FLLC','FPC','DLP','FLP')"

COLORADO_CONFIG = SocrataStateConfig(
    endpoint="https://data.colorado.gov/resource/4ykn-tg5h.json",
    source_name="colorado_sos",
    id_field="entityid",
    name_field="entityname",
    city_field="principalcity",
    state_field="principalstate",
    date_field="entityformdate",
    type_field="entitytype",
    where_clause=(
        f"entitystatus in {_ACTIVE_STATUSES}"
        f" AND entitytype in {_FOR_PROFIT_TYPES}"
    ),
    type_labels={
        "DLLC": "Domestic Limited Liability Company",
        "DPC": "Domestic Profit Corporation",
        "FLLC": "Foreign Limited Liability Company",
        "FPC": "Foreign Profit Corporation",
        "DLP": "Domestic Limited Partnership",
        "FLP": "Foreign Limited Partnership",
    },
)


class ColoradoSosSource(SocrataBusinessSource):
    """Colorado Secretary of State — active for-profit entities."""

    def __init__(self) -> None:
        super().__init__(COLORADO_CONFIG)
