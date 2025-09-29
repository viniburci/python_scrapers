# licitacoes_scraper_postgres_telegram_full.py
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
TELEGRAM_TOKEN = "8145377930:AAHQC83rZtxg0KD7kqzhIJCqr4RUpSRdeI8"
TELEGRAM_CHAT_ID = "-4966623716"

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

# FETCH DINÂMICO
def fetch_dynamic(url, wait_selector="table, div"):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, timeout=60000)
        try:
            page.wait_for_selector(wait_selector, timeout=30000)
        except:
            pass
        html = page.content()
        browser.close()
        return html

# PARSERS
def parse_generic_table(html, base_url=None):
    soup = BeautifulSoup(html, "lxml")
    items = []
    for tr in soup.select("table tbody tr"):
        cols = tr.find_all("td")
        if len(cols) < 1:
            continue
        title_el = cols[0].select_one("a")
        title = title_el.get_text(strip=True) if title_el else cols[0].get_text(strip=True)
        url = title_el.get("href") if title_el else None
        if url and isinstance(url, str) and url.startswith("/") and base_url:
            url = urllib.parse.urljoin(base_url, url)
        org = cols[1].get_text(strip=True) if len(cols) > 1 else ""
        date = cols[2].get_text(strip=True) if len(cols) > 2 else ""
        items.append({"title": title, "org": org, "url": url, "published": date})
    return items

def parse_div_list(html, base_url=None, row_selector="div.licitacao-row"):
    soup = BeautifulSoup(html, "lxml")
    items = []
    for div in soup.select(row_selector):
        title_el = div.select_one("a, .title")
        title = title_el.get_text(strip=True) if title_el else ""
        url = title_el.get("href") if title_el else None
        if url and isinstance(url, str) and url.startswith("/") and base_url:
            url = urllib.parse.urljoin(base_url, url)
        org_el = div.select_one(".org")
        date_el = div.select_one(".date")
        org = org_el.get_text(strip=True) if org_el else ""
        date = date_el.get_text(strip=True) if date_el else ""
        items.append({"title": title, "org": org, "url": url, "published": date})
    return items

from bs4 import BeautifulSoup
import urllib.parse

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
        if not org:
            # fallback no <p> que contém "Empresa Contratante"
            p_empresa = artigo.find("p", string=lambda x: x and "Empresa Contratante" in x)
            org = p_empresa.get_text(strip=True).replace("Empresa Contratante", "") if p_empresa else ""

        # Data de abertura
        p_data = artigo.find("p", string=lambda x: x and "Data da abertura da proposta:" in x)
        date = p_data.get_text(strip=True).replace("Data da abertura da proposta:", "") if p_data else ""

        # URL (primeiro documento, se houver)
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
    {"name": "FIEP", "url": "https://portaldecompras.sistemafiep.org.br", "parser": parse_fiep, "base": "https://portaldecompras.sistemafiep.org.br"},
    {"name": "FIESC", "url": "https://portaldecompras.fiesc.com.br/Portal/Mural.aspx", "parser": parse_div_list, "dynamic": True, "base": "https://portaldecompras.fiesc.com.br"},
    {"name": "FIEMS", "url": "https://compras.fiems.com.br/portal/Mural.aspx?nNmTela=E", "parser": parse_div_list, "dynamic": True, "base": "https://compras.fiems.com.br"},
    {"name": "Licitacoes-e", "url": "https://www.licitacoes-e.com.br/aop/index.jsp?codSite=39763", "parser": parse_div_list, "dynamic": True, "base": "https://www.licitacoes-e.com.br"},
    {"name": "BNC", "url": "https://bnccompras.com/", "parser": parse_div_list, "dynamic": True, "base": "https://bnccompras.com"},
    {"name": "Sanesul", "url": "https://www.sanesul.ms.gov.br/licitacao/tipolicitacao/licitacao", "parser": parse_div_list, "dynamic": True, "base": "https://www.sanesul.ms.gov.br"},
    {"name": "Casan", "url": "https://www.casan.com.br/menu-conteudo/index/url/licitacoes-em-andamento#0", "parser": parse_div_list, "dynamic": True, "base": "https://www.casan.com.br"},
]

# LOOP PRINCIPAL
def main_loop():
    while True:
        try:
            for site in SITES:
                try:
                    print(f"[INFO] Buscando site: {site['name']} ({site['url']})")
                    html = fetch_dynamic(site["url"]) if site.get("dynamic") else requests.get(site["url"]).text
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
