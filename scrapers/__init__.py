from .bnc import BncScraper
from .casan import CasanScraper
from .fiep import FiepScraper
from .fiesc import FiescScraper
from .fiems import FiemsScraper
from .me_compras import MeCompraScraper
from .sanesul import SanesulScraper

SCRAPERS = [
    FiepScraper(),
    SanesulScraper(),
    CasanScraper(),
    FiescScraper(),
    FiemsScraper(),
    BncScraper(),
    MeCompraScraper(),
]
