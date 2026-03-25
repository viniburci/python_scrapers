"""
Teste isolado do scraper FIEP.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from scrapers.fiep import FiepScraper

def main():
    print("\n=== TESTE FIEP ===\n")
    scraper = FiepScraper()

    print(f"[1/1] Buscando e parseando: {scraper.url}")
    print("      (paginacao + ordenacao 'Mais recentes primeiro')\n")

    try:
        items = scraper.run()
    except Exception as e:
        print(f"[ERRO] Falha no run: {e}")
        return

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
