import os
from dotenv import load_dotenv

load_dotenv()

# PostgreSQL
PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", "5432"))
PG_DB = os.getenv("PG_DB", "licitacoes")
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASS = os.getenv("PG_PASS", "")

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Geral
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "1800"))

# ME Compras
ME_USERNAME = os.getenv("ME_USERNAME", "")
ME_PASSWORD = os.getenv("ME_PASSWORD", "")
