import logging
import urllib.parse
from datetime import datetime

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from .base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.casan.com.br"


class CasanScraper(BaseScraper):
    name = "CASAN"
    url = "https://www.casan.com.br/licitacoes/editais"

    def fetch(self) -> str:
        year = str(datetime.now().year)
        html_combinado = ""

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                try:
                    logger.info("[CASAN] Navegando para %s", self.url)
                    page.goto(self.url, wait_until="networkidle", timeout=60_000)

                    logger.info("[CASAN] Selecionando ano %s...", year)
                    page.select_option("#licitacao_ano", value=year)
                    page.click("#btnBuscar")

                    try:
                        page.wait_for_selector(
                            '.editais-visualiza-container:has-text("Quantidade:"), '
                            '.editais-visualiza-container table.table-bordered',
                            timeout=15_000,
                        )
                    except Exception:
                        logger.info("[CASAN] Nenhum resultado carregado para o ano %s.", year)

                    html_combinado = page.inner_html(".editais-visualiza-container")
                finally:
                    browser.close()
        except Exception as e:
            logger.error("[CASAN] Falha no fetch: %s", e)

        return html_combinado

    def parse(self, html: str) -> list[dict]:
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        items = []

        for table in soup.select("table.table-bordered"):
            try:
                modalidade = ""
                titulo_edital = ""
                objeto = ""
                data_abertura = ""
                url_arquivos = ""

                modalidade_td = table.find("td", string=lambda t: t and "Modalidade:" in t)
                if modalidade_td:
                    modalidade = modalidade_td.find_next_sibling("td").get_text(strip=True)

                edital_td = table.find("td", string=lambda t: t and "Edital:" in t)
                if edital_td:
                    titulo_edital = edital_td.find_next_sibling("td").get_text(strip=True)
                    title = f"[{modalidade}] {titulo_edital}"
                else:
                    title = modalidade or "Licitacao (Sem Titulo)"

                data_td = table.find(
                    "td",
                    string=lambda t: t and ("Abertura das propostas:" in t or "Disputa de precos:" in t or "Disputa de preços:" in t),
                )
                if data_td:
                    b_tag = data_td.find_next_sibling("td").find("b")
                    if b_tag:
                        data_abertura = b_tag.get_text(strip=True)

                objeto_td = table.find("td", string=lambda t: t and "Objeto:" in t)
                if objeto_td:
                    objeto = objeto_td.find_next_sibling("td").get_text(strip=True)
                    if "Licitacoes-e" in objeto or "Licitações-e" in objeto:
                        objeto = objeto.split("Licitações-e:")[0].split("Licitacoes-e:")[0].strip()

                link_tag = table.select_one('a.btn_arquivos[href*="/licitacoes/editais-arquivos/licitacao_id/"]')
                if link_tag:
                    url_arquivos = urllib.parse.urljoin(BASE_URL, link_tag.get("href"))

                if url_arquivos:
                    items.append({
                        "title": title,
                        "org": "CASAN",
                        "obj": objeto,
                        "url": url_arquivos,
                        "published": data_abertura,
                    })
            except Exception as e:
                logger.warning("[CASAN] Falha ao processar tabela: %s", e)

        return items
