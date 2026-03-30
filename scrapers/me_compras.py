import logging
import re
import urllib.parse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from config import ME_PASSWORD, ME_USERNAME
from .base import BaseScraper

logger = logging.getLogger(__name__)

_LOGIN_URL = "https://me.com.br/do/Login.mvc/LoginNew"
_LIST_URL = "https://me.com.br/supplier/inbox/pendencies/3"
_BASE_URL = "https://me.com.br"
_MAX_PAGES = 3  # 50 itens/pagina => 150 itens por ciclo
_MODAL_TIMEOUT = 2_000  # ms — skip rapido se item nao tem modal


class MeCompraScraper(BaseScraper):
    name = "ME Compras"
    url = _LIST_URL

    def run(self) -> list[dict]:
        """Login + coleta lista + abre modais, tudo numa unica sessao."""
        with Stealth().use_sync(sync_playwright()) as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()
            try:
                self._login(page)
                items = self._collect_with_modals(page)
            except Exception as e:
                logger.error("[ME] Erro durante scraping: %s", e)
                items = []
            finally:
                browser.close()

        logger.info("[ME] %d itens encontrados", len(items))
        return items

    def _login(self, page):
        logger.info("[ME] Realizando login...")
        page.goto(_LOGIN_URL, timeout=60_000)
        page.wait_for_selector("#LoginName", timeout=15_000)

        page.fill("#LoginName", ME_USERNAME)
        page.fill("#RAWSenha", ME_PASSWORD)

        try:
            recaptcha_frame = page.frame_locator("iframe[src*='recaptcha'][src*='anchor']")
            recaptcha_frame.locator("#recaptcha-anchor").click(timeout=3000)
            page.wait_for_timeout(2000)
            logger.info("[ME] reCAPTCHA clicado com sucesso")
        except Exception:
            logger.info("[ME] reCAPTCHA nao exibido, seguindo sem ele")

        page.click("#SubmitAuth")
        page.wait_for_url(lambda url: "login" not in url.lower(), timeout=20_000)
        page.wait_for_load_state("domcontentloaded", timeout=15_000)
        page.wait_for_timeout(3000)
        logger.info("[ME] Login concluido. URL: %s", page.url)

    def _collect_with_modals(self, page) -> list[dict]:
        page.goto(_LIST_URL, timeout=60_000)
        page.wait_for_selector("tr[data-pk]", timeout=20_000)

        all_items = []
        for page_num in range(1, _MAX_PAGES + 1):
            page.wait_for_selector("tr[data-pk]", timeout=15_000)
            page_items = self.parse(page.content())
            rows = page.locator("tr[data-pk]")

            for idx, item in enumerate(page_items):
                try:
                    modal_link = rows.nth(idx).locator("a.modal-quotations")
                    modal_link.click(timeout=_MODAL_TIMEOUT)
                    page.wait_for_selector("#modal-grid", timeout=10_000)
                    page.wait_for_timeout(1500)
                    item["itens"], item["total_itens"] = self._parse_modal_items(
                        page.locator(".modal-content").inner_html()
                    )
                    page.locator(".close.modal-quotations").click()
                    page.wait_for_selector(".modal-content", state="hidden", timeout=5_000)
                except Exception:
                    pass  # item sem modal, continua

                all_items.append(item)

            logger.info("[ME] Pagina %d: %d licitacoes", page_num, len(page_items))

            next_btn = page.locator("[data-cy='next-page']")
            if next_btn.is_disabled() or page_num == _MAX_PAGES:
                break
            next_btn.click()
            page.wait_for_selector("tr[data-pk]", timeout=15_000)

        return all_items

    def parse(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        items = []

        for tr in soup.select("tr[data-pk]"):
            cols = {int(td.get("aria-colindex", 0)): td for td in tr.find_all("td")}

            col2 = cols.get(2)
            link_el = col2.select_one("a") if col2 else None
            if not link_el:
                continue

            serial = link_el.get_text(strip=True)
            href = link_el.get("href", "")
            url = urllib.parse.urljoin(_BASE_URL, href) if href else None

            col3 = cols.get(3)
            tipo = col3.select_one("span").get_text(strip=True) if col3 else ""

            col5 = cols.get(5)
            org = col5.select_one(".truncate-1").get_text(strip=True) if col5 else ""

            col6 = cols.get(6)
            published = col6.select_one(".truncate-1").get_text(strip=True) if col6 else ""

            title = f"{serial} - {tipo}" if tipo else serial

            if serial and url:
                items.append({"title": title, "org": org, "url": url, "published": published})

        return items

    def _parse_modal_items(self, html: str) -> tuple[list[dict], int]:
        soup = BeautifulSoup(html, "lxml")

        total = 0
        header = soup.select_one(".doc-modal-header strong")
        if header:
            m = re.search(r"\((\d+) iten", header.get_text())
            if m:
                total = int(m.group(1))

        items = []
        for tr in soup.select("tbody tr[role='row']"):
            cols = {int(td.get("aria-colindex", 0)): td for td in tr.find_all("td")}

            col2 = cols.get(2)
            col3 = cols.get(3)
            col4 = cols.get(4)
            if not col2:
                continue

            desc_div = col2.find("div")
            desc = " ".join(desc_div.get_text().split()) if desc_div else ""
            unit = col3.select_one(".truncate-1").get_text(strip=True) if col3 else ""
            qty = col4.select_one(".truncate-1").get_text(strip=True) if col4 else ""

            if desc:
                items.append({"descricao": desc, "unidade": unit, "quantidade": qty})

        return items, total or len(items)
