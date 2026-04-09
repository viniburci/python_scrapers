import logging
import time

from config import CHECK_INTERVAL, FILTER_KEYWORDS
from db import generate_id, get_known_ids, init_db, save_many
from notifier import send
from scrapers import SCRAPERS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _matches_filter(item: dict) -> bool:
    """Retorna True se o item passa pelo filtro de palavras-chave.
    Se FILTER_KEYWORDS estiver vazio, todos os itens passam."""
    if not FILTER_KEYWORDS:
        return True
    itens_text = " ".join(i.get("descricao", "") for i in item.get("itens", []))
    text = f"{item.get('title', '')} {item.get('obj', '')} {itens_text}".lower()
    return any(kw in text for kw in FILTER_KEYWORDS)


def main():
    init_db()
    logger.info("Scraper iniciado. Intervalo: %ds", CHECK_INTERVAL)

    while True:
        for scraper in SCRAPERS:
            try:
                logger.info("Buscando: %s (%s)", scraper.name, scraper.url)
                items = scraper.run()

                # Um unico SELECT para todos os itens da pagina
                known = get_known_ids(items)

                new_items = []
                for item in items:
                    if generate_id(item) not in known:
                        new_items.append(item)
                    elif scraper.ordered:
                        logger.info(
                            "[%s] Item ja processado: '%s'. Interrompendo.",
                            scraper.name, item.get("title", "")[:50],
                        )
                        break

                # Deduplica itens com mesmo ID no mesmo lote (evita envio duplo)
                seen = set()
                deduped = []
                for item in new_items:
                    uid = generate_id(item)
                    if uid not in seen:
                        seen.add(uid)
                        deduped.append(item)
                new_items = deduped

                # Um unico INSERT em lote para todos os novos
                save_many(new_items)

                for item in new_items:
                    logger.info("[NOVO] [%s] %s", scraper.name, item["title"])
                    if _matches_filter(item):
                        send(item, scraper.name)
                    else:
                        logger.info("[FILTRADO] [%s] %s", scraper.name, item["title"])
            except Exception as e:
                logger.error("Erro no scraper %s: %s", scraper.name, e, exc_info=True)

        logger.info("Dormindo %ds...\n", CHECK_INTERVAL)
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Scraper encerrado pelo usuario")
