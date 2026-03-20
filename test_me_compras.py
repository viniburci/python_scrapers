"""
Teste isolado do scraper ME Compras.

Fase 1 — Login visivel: confirma que autenticacao funciona.
Fase 2 — Lista + itens: mostra 3 licitacoes de cada pagina com seus itens,
          usando o modal diretamente (sem sair da lista).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
from scrapers.me_compras import MeCompraScraper
from config import ME_USERNAME

LOGIN_URL = "https://me.com.br/do/Login.mvc/LoginNew"
LIST_URL  = "https://me.com.br/supplier/inbox/pendencies/3"
_MAX_PAGES = 3
_SAMPLE_PER_PAGE = 3


def fase1_login_visivel():
    print("\n=== FASE 1: Login visivel ===")
    print(f"Usuario: {ME_USERNAME}\n")

    scraper = MeCompraScraper()
    with Stealth().use_sync(sync_playwright()) as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()
        scraper._login(page)
        print(f"[FASE 1] SUCESSO! URL: {page.url}")
        input("\n[FASE 1] OK. Pressione ENTER para iniciar fase 2 (headless)...")
        browser.close()
    return True


def fase2_lista_com_itens():
    print("\n=== FASE 2: Lista paginada com itens via modal (headless) ===\n")
    scraper = MeCompraScraper()

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
        scraper._login(page)

        page.goto(LIST_URL, timeout=60_000)
        page.wait_for_selector("tr[data-pk]", timeout=20_000)

        for page_num in range(1, _MAX_PAGES + 1):
            page.wait_for_selector("tr[data-pk]", timeout=15_000)
            all_items = scraper.parse(page.content())

            print(f"{'='*60}")
            print(f"PAGINA {page_num}  ({len(all_items)} licitacoes encontradas)")
            print(f"{'='*60}")

            rows = page.locator("tr[data-pk]")
            amostra = all_items[:_SAMPLE_PER_PAGE]

            for idx, item in enumerate(amostra):
                # Abre modal da linha correspondente
                try:
                    modal_link = rows.nth(idx).locator("a.modal-quotations")
                    modal_link.click(timeout=5000)
                    page.wait_for_selector("#modal-grid", timeout=10_000)
                    page.wait_for_timeout(1500)
                    item["itens"], item["total_itens"] = scraper._parse_modal_items(
                        page.locator(".modal-content").inner_html()
                    )
                    page.locator(".close.modal-quotations").click()
                    page.wait_for_selector(".modal-content", state="hidden", timeout=5_000)
                except Exception as e:
                    item["itens"] = []
                    item["total_itens"] = 0
                    print(f"  [AVISO] Modal nao abriu para linha {idx}: {e}")

                itens = item.get("itens", [])
                total = item.get("total_itens", 0)

                print(f"\n  [{idx+1}] {item['title']}")
                print(f"       Orgao:  {item['org']}")
                print(f"       Data:   {item['published']}")
                print(f"       URL:    {item['url']}")
                if itens:
                    print(f"       Itens ({len(itens)} exibidos de {total}):")
                    for prod in itens[:3]:
                        print(f"         - {prod['descricao'][:65]} | {prod['quantidade']} {prod['unidade']}")
                    if total > 3:
                        print(f"         ... e mais {total - 3} itens")
                else:
                    print("       Itens: nenhum extraido")

            print()
            next_btn = page.locator("[data-cy='next-page']")
            if next_btn.is_disabled() or page_num == _MAX_PAGES:
                print(f"[FASE 2] Fim da paginacao apos pagina {page_num}.")
                break
            print(f"[FASE 2] Avancando para pagina {page_num + 1}...\n")
            next_btn.click()
            page.wait_for_selector("tr[data-pk]", timeout=15_000)

        browser.close()


if __name__ == "__main__":
    ok = fase1_login_visivel()
    if ok:
        fase2_lista_com_itens()
