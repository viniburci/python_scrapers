import logging
import re
from datetime import datetime

from bs4 import BeautifulSoup

from .base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://compras.fiems.com.br"
_ID_PATTERN = re.compile(r"trListaMuralProcesso_Click\((\d+),")


class FiemsScraper(BaseScraper):
    name = "FIEMS"
    url = "https://compras.fiems.com.br/portal/Mural.aspx?nNmTela=E"

    def fetch(self) -> str:
        prev_year = str(datetime.now().year - 1)
        return self._fetch_with_scroll(
            self.url,
            wait_selector="tbody#trListaMuralProcesso",
            scroll_pause_ms=1500,
            stop_selector="tbody#trListaMuralProcesso tr td:nth-child(6)",
            date_threshold=prev_year,
        )

    def parse(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        items = []
        rows = soup.select("tbody#trListaMuralProcesso tr")

        if not rows:
            logger.warning("[FIEMS] Nenhuma linha encontrada no HTML")

        for tr in rows:
            cols = tr.find_all("td")
            if len(cols) < 8:
                continue

            title = cols[1].get_text(strip=True)
            org = cols[2].get_text(strip=True)
            obj = cols[3].get_text(strip=True)
            published = cols[6].get_text(strip=True)

            url = None
            match = _ID_PATTERN.search(cols[1].get("onclick", ""))
            if match:
                url = f"{BASE_URL}/Portal/Detalhe.aspx?id={match.group(1)}"

            if title and url:
                items.append({"title": title, "org": org, "obj": obj, "url": url, "published": published})

        return items
