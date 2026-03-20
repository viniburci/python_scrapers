import logging
import time

from config import CHECK_INTERVAL
from db import init_db, is_new_and_save
from notifier import send
from scrapers import SCRAPERS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    init_db()
    logger.info("Scraper iniciado. Intervalo: %ds", CHECK_INTERVAL)

    while True:
        for scraper in SCRAPERS:
            try:
                logger.info("Buscando: %s (%s)", scraper.name, scraper.url)
                items = scraper.run()

                new_items = []
                for item in items:
                    if is_new_and_save(item):
                        new_items.append(item)
                    elif scraper.ordered:
                        # Otimizacao: se o scraper retorna itens ordenados do mais
                        # recente para o mais antigo, para ao encontrar o primeiro
                        # item ja conhecido (os demais tambem serao conhecidos).
                        logger.info(
                            "[%s] Item ja processado: '%s'. Interrompendo.",
                            scraper.name, item.get("title", "")[:50],
                        )
                        break

                if new_items and hasattr(scraper, "enrich"):
                    scraper.enrich(new_items)

                for item in new_items:
                    logger.info("[NOVO] [%s] %s", scraper.name, item["title"])
                    send(item, scraper.name)
            except Exception as e:
                logger.error("Erro no scraper %s: %s", scraper.name, e, exc_info=True)

        logger.info("Dormindo %ds...\n", CHECK_INTERVAL)
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Scraper encerrado pelo usuario")
