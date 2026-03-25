import logging
import re
from datetime import datetime

from bs4 import BeautifulSoup

from .base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://portaldecompras.fiesc.com.br"
_ID_PATTERN = re.compile(r"trListaMuralResumoEdital_Click\((\d+),")


class FiescScraper(BaseScraper):
    name = "FIESC"
    url = "https://portaldecompras.fiesc.com.br/Portal/Mural.aspx"

    def fetch(self) -> str:
        prev_year = str(datetime.now().year - 1)
        return self._fetch_with_scroll(
            self.url,
            wait_selector="tbody#trListaMuralProcesso",
            stop_selector="tbody#trListaMuralProcesso tr td:nth-child(7)",
            date_threshold=prev_year,
        )

    def parse(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        items = []

        for tr in soup.select("tbody#trListaMuralProcesso tr"):
            cols = tr.find_all("td")
            if len(cols) < 8:
                continue

            title = cols[3].get_text(strip=True)
            org = cols[2].get_text(strip=True)
            published = cols[6].get_text(strip=True)

            url = None
            span = cols[7].select_one("span.areaClique")
            if span:
                match = _ID_PATTERN.search(span.get("onclick", ""))
                if match:
                    url = f"{BASE_URL}/Detalhe.aspx?id={match.group(1)}"

            if title and url:
                items.append({"title": title, "org": org, "url": url, "published": published})

        return items
