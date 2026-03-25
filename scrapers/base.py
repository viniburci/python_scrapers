import logging
from abc import ABC, abstractmethod
from datetime import datetime

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    name: str
    url: str
    ordered: bool = False  # True se os itens vem ordenados do mais recente para o mais antigo

    @abstractmethod
    def parse(self, html: str) -> list[dict]:
        """Parseia o HTML e retorna lista de licitacoes."""
        ...

    def fetch(self) -> str:
        """Fetch padrao: carrega a pagina e aguarda um seletor."""
        return self._fetch_playwright(self.url)

    def run(self) -> list[dict]:
        html = self.fetch()
        items = self.parse(html)
        logger.info("[%s] %d itens encontrados", self.name, len(items))
        return items

    # ------------------------------------------------------------------
    # Helpers de fetch reutilizaveis pelas subclasses
    # ------------------------------------------------------------------

    def _fetch_playwright(self, url: str, wait_selector: str = "body") -> str:
        """Carrega a pagina e espera o seletor aparecer."""
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                page.goto(url, timeout=60_000)
                page.wait_for_selector(wait_selector, timeout=30_000)
                return page.content()
            finally:
                browser.close()

    def _fetch_with_scroll(
        self,
        url: str,
        wait_selector: str = "body",
        max_scrolls: int = 50,
        scroll_pause_ms: int = 2000,
        stop_selector: str | None = None,
        date_threshold: str | None = None,
    ) -> str:
        """Carrega a pagina e rola ate o fim para lazy loading.

        Se stop_selector e date_threshold forem fornecidos, para de rolar
        assim que o ultimo elemento do stop_selector contiver date_threshold
        no seu texto (util para parar ao encontrar itens de anos anteriores).
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                page.goto(url, timeout=60_000)
                try:
                    page.wait_for_selector(wait_selector, timeout=30_000)
                except Exception:
                    logger.warning(
                        "[%s] Seletor '%s' nao encontrado no tempo limite",
                        self.name, wait_selector,
                    )

                last_height = -1
                for i in range(max_scrolls):
                    # Para ao encontrar item antigo (date_threshold no ultimo elemento visivel)
                    if stop_selector and date_threshold:
                        try:
                            last_text = page.evaluate(
                                """(sel) => {
                                    const els = document.querySelectorAll(sel);
                                    return els.length ? els[els.length - 1].textContent : null;
                                }""",
                                stop_selector,
                            )
                            if last_text and date_threshold in last_text:
                                logger.info(
                                    "[%s] Threshold '%s' encontrado. Parando scroll.",
                                    self.name, date_threshold,
                                )
                                break
                        except Exception:
                            pass

                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(scroll_pause_ms)
                    new_height = page.evaluate("document.body.scrollHeight")
                    if new_height == last_height:
                        logger.debug("[%s] Scroll finalizado apos %d rolagens", self.name, i)
                        break
                    last_height = new_height
                else:
                    logger.warning("[%s] Limite de %d rolagens atingido", self.name, max_scrolls)

                return page.content()
            finally:
                browser.close()
