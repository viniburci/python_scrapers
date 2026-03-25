"""
Teste isolado do scraper FIESC.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from scrapers.fiesc import FiescScraper

def main():
    print("\n=== TESTE FIESC ===\n")
    scraper = FiescScraper()

    print(f"[1/2] Buscando pagina: {scraper.url}")
    print("      (pode demorar — faz scroll ate o fim da lista)\n")

    try:
        html = scraper.fetch()
        print(f"[1/2] HTML capturado: {len(html)} bytes\n")
    except Exception as e:
        print(f"[ERRO] Falha no fetch: {e}")
        return

    print("[2/2] Parseando licitacoes...")
    items = scraper.parse(html)
    print(f"      {len(items)} licitacoes encontradas.\n")

    if not items:
        print("AVISO: Nenhum item encontrado. Verifique os seletores do parser.")
        return

    print(f"--- Primeiros 5 resultados ---")
    for i, item in enumerate(items[:5], 1):
        print(f"[{i}] {item['title']}")
        print(f"     Orgao:     {item['org']}")
        print(f"     Objeto:    {item.get('obj', '')[:100]}")
        print(f"     Publicado: {item['published']}")
        print(f"     URL:       {item['url']}")
        print()

if __name__ == "__main__":
    main()
