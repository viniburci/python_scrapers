import logging
import urllib.parse

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from .base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://bnccompras.com"


class BncScraper(BaseScraper):
    name = "BNC"
    url = "https://bnccompras.com/Process/ProcessSearchPublic?param1=0"
    ordered = True

    def fetch(self) -> str:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                page.goto(self.url, timeout=60_000)
                page.wait_for_selector("tbody#tableProcessDataBody tr", timeout=30_000)
                page.wait_for_load_state("networkidle")
                return page.content()
            except Exception as e:
                logger.error("[BNC] Erro no fetch: %s", e)
                return ""
            finally:
                browser.close()

    def _fetch_obj(self, url: str) -> str | None:
        """Busca o objeto na pagina de detalhes (textarea#ProductOrService)."""
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            ta = soup.find("textarea", {"id": "ProductOrService"})
            return ta.get_text(strip=True) if ta else None
        except Exception as e:
            logger.warning("[BNC] Falha ao buscar detalhes de %s: %s", url, e)
            return None

    def parse(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        items = []

        for tr in soup.select("tbody#tableProcessDataBody tr"):
            cols = tr.find_all("td")
            if len(cols) < 8:
                continue

            link_el = cols[0].select_one("a[title='Informações do Processo']")
            url = (
                urllib.parse.urljoin(BASE_URL, link_el["href"].strip())
                if link_el and "href" in link_el.attrs else None
            )
            org = cols[1].get_text(strip=True)
            title = cols[2].get_text(strip=True)
            obj = cols[5].get_text(strip=True)
            published = cols[6].get_text(strip=True)

            if title and url:
                # Tenta enriquecer obj com a pagina de detalhes
                detailed_obj = self._fetch_obj(url)
                if detailed_obj:
                    obj = detailed_obj
                items.append({"title": title, "org": org, "obj": obj, "url": url, "published": published})

        return items
