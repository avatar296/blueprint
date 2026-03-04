"""Company sourcing providers — populate the companies table from public data."""

from scout.sourcing.base import CompanyRecord, CompanySource
from scout.sourcing.colorado_sos import ColoradoSosSource
from scout.sourcing.fdic import FdicSource
from scout.sourcing.iowa_sos import IowaSosSource
from scout.sourcing.ncua import NcuaSource
from scout.sourcing.newyork_sos import NewYorkSosSource
from scout.sourcing.oregon_sos import OregonSosSource
from scout.sourcing.propublica import ProPublicaSource
from scout.sourcing.sba_ppp import SbaPppSource
from scout.sourcing.sec_edgar import SecEdgarSource
from scout.sourcing.texas_sos import TexasSosSource
from scout.sourcing.wikidata import WikidataSource

__all__ = [
    "ColoradoSosSource",
    "CompanyRecord",
    "CompanySource",
    "FdicSource",
    "IowaSosSource",
    "NcuaSource",
    "NewYorkSosSource",
    "OregonSosSource",
    "ProPublicaSource",
    "SbaPppSource",
    "SecEdgarSource",
    "TexasSosSource",
    "WikidataSource",
]
