import logging
import urllib.parse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from .base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://portaldecompras.sistemafiep.org.br"


class FiepScraper(BaseScraper):
    name = "FIEP"
    url = BASE_URL + "/"
    ordered = True

    def run(self) -> list[dict]:
        """Faz login de ordenacao, pagina e retorna todos os itens encontrados."""
        items = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                page.goto(self.url, wait_until="domcontentloaded", timeout=60_000)

                # Aplica ordenacao "Mais recentes primeiro"
                try:
                    page.click(".select-ordering .select-selected")
                    page.wait_for_timeout(500)
                    page.click('.select-ordering .select-items div:has-text("Mais recentes primeiro")')
                    page.wait_for_selector(".tab-noticias article.edital", timeout=20_000)
                    page.wait_for_timeout(1500)
                    logger.info("[FIEP] Ordenacao aplicada.")
                except Exception as e:
                    logger.warning("[FIEP] Falha na ordenacao: %s", e)

                max_pages = 20
                for page_num in range(1, max_pages + 1):
                    logger.info("[FIEP] Processando pagina %d...", page_num)
                    html = page.inner_html("#licitacoes-list")
                    page_items = self.parse(html)
                    logger.info("[FIEP] Pagina %d: %d itens.", page_num, len(page_items))
                    items.extend(page_items)

                    next_sel = ".paginationjs-next:not(.disabled)"
                    if page.is_visible(next_sel):
                        page.click(next_sel)
                        page.wait_for_timeout(2000)
                    else:
                        break
            except Exception as e:
                logger.error("[FIEP] Erro na paginacao: %s", e)
            finally:
                browser.close()

        logger.info("[FIEP] %d itens no total", len(items))
        return items

    def parse(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        items = []

        for artigo in soup.select("article.edital"):
            h3 = artigo.select_one("h3")
            title = h3.get_text(strip=True) if h3 else "Sem titulo"

            empresa_div = artigo.select_one("div.header div.empresas")
            org = empresa_div.get_text(strip=True) if empresa_div else ""

            p_data = artigo.find("p", string=lambda x: x and "Data da abertura da proposta:" in x)
            published = (
                p_data.get_text(strip=True).replace("Data da abertura da proposta:", "").strip()
                if p_data else ""
            )

            # Objeto: ultimo <p class="body"> que nao seja status/data/empresa
            obj = None
            for p in reversed(artigo.select("div.dados > p.body")):
                txt = p.get_text(strip=True)
                if any(kw in txt for kw in ("Status:", "Data da abertura", "Empresa Contratante")):
                    continue
                if len(txt) > 10:
                    obj = txt
                    break

            # URL: link do edital
            link_el = artigo.select_one("ul.documentos li strong:-soup-contains('Edital') + ul a[href]")
            if not link_el:
                link_el = artigo.select_one("ul.documentos li strong:-soup-contains('CHAMAMENTO') + ul a[href]")
            if not link_el:
                link_el = artigo.select_one("ul.documentos li a[href]")

            url = urllib.parse.urljoin(BASE_URL, link_el.get("href")) if link_el else None

            if url:
                items.append({"title": title, "org": org, "url": url, "published": published, "obj": obj})

        return items
