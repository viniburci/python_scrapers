# scraper_fiep_postgres_telegram.py
import hashlib
import time
import json
import requests
import urllib.parse
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import psycopg2

# CONFIGURAÇÃO - PostgreSQL
PG_HOST = "localhost"
PG_PORT = 5432
PG_DB = "licitacoes"
PG_USER = "postgres"
PG_PASS = "123"

# CONFIGURAÇÃO - Telegram
TELEGRAM_TOKEN = "8071395009:AAH-7P6Cys3hncbQdaJYB2paoK7sVeh884s"
TELEGRAM_CHAT_ID = "-1003163879445"

CHECK_INTERVAL_SECONDS = 1800  # 30 minutos

# Conexão PostgreSQL
conn = psycopg2.connect(
    host=PG_HOST, port=PG_PORT, dbname=PG_DB, user=PG_USER, password=PG_PASS
)
cur = conn.cursor()

# Criar tabela se não existir
cur.execute("""
CREATE TABLE IF NOT EXISTS notices (
    id TEXT PRIMARY KEY,
    title TEXT,
    org TEXT,
    url TEXT,
    published TEXT,
    raw_hash TEXT,
    found_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")
conn.commit()

# UTILITÁRIOS
def md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()

def is_new_and_save(item):
    unique_str = (item['url'] or "") + "|" + item['title']
    uid = md5(unique_str)
    cur.execute("SELECT 1 FROM notices WHERE id=%s", (uid,))
    if cur.fetchone():
        return False, uid
    cur.execute(
        "INSERT INTO notices (id, title, org, url, published, raw_hash) VALUES (%s,%s,%s,%s,%s,%s)",
        (uid, item['title'], item['org'], item['url'], item['published'], md5(json.dumps(item, ensure_ascii=False)))
    )
    conn.commit()
    return True, uid

def send_telegram_message(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "disable_web_page_preview": False, "parse_mode": "Markdown"}
    resp = requests.post(url, json=payload, timeout=15)
    return resp.ok, resp.text

def format_item_message(item):
    return f"*{item['title']}*\nÓrgão: {item['org']}\nPublicado: {item['published']}\nLink: {item['url']}"

# FETCH DINÂMICO - FIEP
def fetch_dynamic_fiep(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, timeout=60000)
        # Espera os artigos carregarem
        page.wait_for_selector("div.tab-noticias article.edital", timeout=30000)
        html = page.content()
        browser.close()
        return html

# PARSER FIEP
def parse_fiep(html, base_url="https://portaldecompras.sistemafiep.org.br"):
    soup = BeautifulSoup(html, "lxml")
    items = []

    for artigo in soup.select("article.edital"):
        # Título
        h3 = artigo.select_one("h3")
        title = h3.get_text(strip=True) if h3 else "Sem título"

        # Órgão/empresa contratante
        empresa_div = artigo.select_one("div.empresas")
        org = empresa_div.get_text(strip=True) if empresa_div else ""

        # Data de abertura
        p_data = artigo.find("p", string=lambda x: x and "Data da abertura da proposta:" in x)
        date = p_data.get_text(strip=True).replace("Data da abertura da proposta:", "") if p_data else ""

        # URL (primeiro documento disponível)
        link_el = artigo.select_one("ul.documentos li a[href]")
        url = urllib.parse.urljoin(base_url, link_el.get("href")) if link_el else None

        items.append({
            "title": title,
            "org": org,
            "url": url,
            "published": date
        })

    return items

# SITES
SITES = [
    {
        "name": "FIEP",
        "url": "https://portaldecompras.sistemafiep.org.br/",
        "parser": parse_fiep,
        "fetch_dynamic": fetch_dynamic_fiep,
        "base": "https://portaldecompras.sistemafiep.org.br"
    }
]

# LOOP PRINCIPAL
def main_loop():
    while True:
        try:
            for site in SITES:
                try:
                    print(f"[INFO] Buscando site: {site['name']} ({site['url']})")
                    html = site["fetch_dynamic"](site["url"])
                    print(f"[INFO] Página carregada: {len(html)} bytes")

                    items = site["parser"](html, base_url=site.get("base"))
                    print(f"[INFO] {len(items)} itens encontrados em {site['name']}")
                    for item in items:
                        print(f"  - {item['title']} | {item['url']}")
                        is_new, _ = is_new_and_save(item)
                        if is_new:
                            msg = format_item_message(item)
                            ok, resp = send_telegram_message(msg)
                            print(f"[ALERTA] Novo item [{site['name']}]: {item['title']}", "Enviado" if ok else f"Erro: {resp}")
                except Exception as e:
                    print(f"[ERRO] Site {site['name']}: {e}")
            print(f"[INFO] Dormindo {CHECK_INTERVAL_SECONDS} segundos...\n")
            time.sleep(CHECK_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            print("Parando scraper...")
            break

if __name__ == "__main__":
    main_loop()
