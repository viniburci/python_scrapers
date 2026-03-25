import logging
from datetime import datetime

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from .base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.sanesul.ms.gov.br"


class SanesulScraper(BaseScraper):
    name = "Sanesul"
    url = "https://www.sanesul.ms.gov.br/licitacao/tipolicitacao/licitacao"

    def run(self) -> list[dict]:
        """Faz paginacao PostBack e retorna somente licitacoes do ano corrente."""
        year_threshold = str(datetime.now().year)
        all_items = []

        with Stealth().use_sync(sync_playwright()) as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                logger.info("[Sanesul] Navegando para %s", self.url)
                page.goto(self.url, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(6_000)  # aguarda Cloudflare challenge

                current_page = 1
                while True:
                    logger.info("[Sanesul] Processando pagina %d...", current_page)
                    page.wait_for_selector("#conteudo_gridLicitacao", state="visible", timeout=30_000)
                    page.wait_for_load_state("domcontentloaded")

                    html = page.content()
                    items, last_year = self._parse_page(html)

                    # Para quando chegamos a um ano anterior ao threshold
                    if last_year and last_year < year_threshold:
                        logger.info("[Sanesul] Ano %s anterior ao threshold %s. Parando.", last_year, year_threshold)
                        items = [i for i in items if year_threshold in i.get("published", "")]
                        all_items.extend(items)
                        break

                    if not items and current_page > 1:
                        break

                    all_items.extend(items)

                    # Tenta ir para a proxima pagina via PostBack
                    next_page = current_page + 1
                    next_locator = page.locator(
                        f"a[href*='Page${next_page}'][href*='gridLicitacao']"
                    )
                    if not next_locator.is_visible():
                        logger.info("[Sanesul] Fim da paginacao.")
                        break

                    try:
                        with page.expect_navigation(wait_until="domcontentloaded", timeout=25_000):
                            next_locator.click()
                        current_page = next_page
                    except Exception as e:
                        logger.error("[Sanesul] Falha ao navegar para pagina %d: %s", next_page, e)
                        break
            finally:
                browser.close()

        # Filtro final: apenas ano corrente
        all_items = [i for i in all_items if year_threshold in i.get("published", "")]
        logger.info("[Sanesul] %d itens encontrados para o ano %s", len(all_items), year_threshold)
        return all_items

    def _parse_page(self, html: str):
        """Retorna (items, last_year) onde last_year e o ano do ultimo item valido."""
        soup = BeautifulSoup(html, "lxml")
        items = []
        last_year = None

        table = soup.find("table", {"id": "conteudo_gridLicitacao"})
        if not table:
            logger.warning("[Sanesul] Tabela nao encontrada no HTML.")
            return items, last_year

        for row in table.find_all("tr")[1:]:
            cols = row.find_all("td")
            if len(cols) != 5:
                continue

            numero = cols[0].get_text(strip=True)
            objeto = cols[1].get_text(strip=True)
            published_raw = cols[2].get_text(strip=True)  # DD/MM/YYYY HH:MM:SS

            if not numero.strip().isdigit():
                continue
            if any(kw in numero for kw in ("Número", "Total")):
                continue

            # Extrai ano da data (formato DD/MM/YYYY HH:MM:SS)
            date_parts = published_raw.split("/")
            ano = date_parts[2][:4] if len(date_parts) >= 3 else str(datetime.now().year)

            # URL sintetica estavel (ID interno nao esta no HTML)
            url = f"{BASE_URL}/licitacao/tipolicitacao/licitacao#{numero}-{ano}"
            items.append({
                "title": f"Licitacao {numero}/{ano}",
                "org": "Sanesul",
                "obj": objeto,
                "url": url,
                "published": published_raw,
            })
            last_year = ano

        return items, last_year

    def parse(self, html: str) -> list[dict]:
        items, _ = self._parse_page(html)
        return items
