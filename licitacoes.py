import hashlib
import time
import json
import requests
import urllib.parse
import re
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
try:
    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_DB, user=PG_USER, password=PG_PASS
    )
    cur = conn.cursor()
except psycopg2.Error as e:
    print(f"[ERRO] Falha ao conectar ao PostgreSQL: {e}")
    exit(1)

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
    # Usamos URL e Título para criar um ID único
    unique_str = (item['url'] or "") + "|" + item['title']
    uid = md5(unique_str)
    cur.execute("SELECT 1 FROM notices WHERE id=%s", (uid,))
    if cur.fetchone():
        return False, uid
    try:
        # Nota: O campo 'obj' (objeto) não está na tabela notices, então não o inserimos aqui.
        # Poderíamos criar uma coluna nova ou adicioná-lo ao 'title' ou 'raw_hash'.
        # Por enquanto, ele só será usado para o alerta Telegram.
        cur.execute(
            "INSERT INTO notices (id, title, org, url, published, raw_hash) VALUES (%s,%s,%s,%s,%s,%s)",
            (uid, item['title'], item['org'], item['url'], item['published'], md5(json.dumps(item, ensure_ascii=False)))
        )
        conn.commit()
        return True, uid
    except Exception as e:
        conn.rollback()
        print(f"[ERRO SQL] Falha ao inserir item: {e}")
        return False, uid

def send_telegram_message(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "disable_web_page_preview": False, "parse_mode": "Markdown"}
    resp = requests.post(url, json=payload, timeout=15)
    return resp.ok, resp.text

def format_item_message(item):
    """Formata a mensagem para o Telegram, incluindo o campo 'obj' se presente."""
    message = f"*{item['title']}*\n"
    message += f"Órgão: {item['org']}\n"
    # Adiciona o objeto, se existir
    if 'obj' in item and item['obj']:
        # Limita o objeto a 250 caracteres para não estourar o limite do Telegram
        obj_text = item['obj'][:250].strip()
        if len(item['obj']) > 250:
            obj_text += "..."
        message += f"Objeto: {obj_text}\n"
    message += f"Publicado: {item['published']}\n"
    message += f"Link: {item['url']}"
    return message

# FUNÇÕES DE FETCH
def fetch_dynamic_scroll(url, wait_selector="table, div", stop_selector=None, date_threshold=None, max_scrolls=50):
    """
    Busca o HTML usando o Playwright e simula a rolagem da página.
    Adiciona lógica para parar a rolagem se uma data antiga for encontrada.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, timeout=60000)
        
        try:
            # Espera inicial
            page.wait_for_selector(wait_selector, timeout=30000)
        except:
            print("[FETCH] Aviso: O seletor de espera inicial não foi encontrado.")
            pass

        print("[FETCH] Iniciando rolagem para carregar itens recentes...")
        
        last_height = -1
        scroll_attempts = 0
        
        while scroll_attempts < max_scrolls:
            # 1. Checa a condição de parada baseada em data (antes de rolar)
            if stop_selector and date_threshold:
                try:
                    # Avalia se o texto do elemento de data contém o ano de parada
                    last_date_text = page.evaluate(f"""
                        (selector) => {{
                            const elements = document.querySelectorAll(selector);
                            return elements.length > 0 ? elements[elements.length - 1].textContent : null;
                        }}
                    """, stop_selector)
                    
                    if last_date_text and str(date_threshold) in last_date_text:
                        print(f"[FETCH] Condição de parada atingida: Data '{date_threshold}' encontrada no seletor '{stop_selector}'.")
                        break
                        
                except Exception as e:
                    # Ignora falhas na avaliação do seletor e continua rolando
                    # print(f"[FETCH] Erro ao checar data: {e}")
                    pass

            # 2. Rola até o final da página
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            
            # 3. Espera o novo conteúdo ser carregado
            time.sleep(1.5) 
            
            # 4. Verifica se o tamanho do conteúdo aumentou
            new_height = page.evaluate("document.body.scrollHeight")
            
            if new_height == last_height:
                print(f"[FETCH] Fim da lista. Todos os itens carregados após {scroll_attempts} rolagens.")
                break
            
            last_height = new_height
            scroll_attempts += 1
            # print(f"[FETCH] Rolagem {scroll_attempts} realizada. Nova altura: {new_height}")

        if scroll_attempts == max_scrolls:
            print(f"[FETCH] Aviso: Limite máximo de {max_scrolls} rolagens atingido.")

        html = page.content()
        browser.close()
        return html

# PARSERS GENÉRICOS (Mantidos, mas não usados nos sites FIESC/FIEMS/FIEP)
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

# --- PARSERS ESPECÍFICOS ---

def parse_fiep(html, base_url="https://portaldecompras.sistemafiep.org.br"):
    """Parser para o Portal de Compras da FIEP."""
    soup = BeautifulSoup(html, "lxml")
    items = []
    for artigo in soup.select("article.edital"):
        h3 = artigo.select_one("h3")
        title = h3.get_text(strip=True) if h3 else "Sem título"
        empresa_div = artigo.select_one("div.empresas")
        org = empresa_div.get_text(strip=True) if empresa_div else ""
        if not org:
            p_empresa = artigo.find("p", string=lambda x: x and "Empresa Contratante" in x)
            org = p_empresa.get_text(strip=True).replace("Empresa Contratante:", "").strip() if p_empresa else ""
        p_data = artigo.find("p", string=lambda x: x and "Data da abertura da proposta:" in x)
        date = p_data.get_text(strip=True).replace("Data da abertura da proposta:", "").strip() if p_data else ""
        link_el = artigo.select_one("ul.documentos li a[href]")
        url = urllib.parse.urljoin(base_url, link_el.get("href")) if link_el else None
        items.append({"title": title, "org": org, "url": url, "published": date})
    return items

def parse_fiesc_tabela(html, base_url="https://portaldecompras.fiesc.com.br"):
    """
    Parser corrigido para a FIESC. Extrai o ID da licitação do atributo onclick (Coluna 7) para construir o URL absoluto.
    """
    soup = BeautifulSoup(html, "lxml")
    items = []
    rows = soup.select("tbody#trListaMuralProcesso tr")
    ID_PATTERN = re.compile(r"trListaMuralResumoEdital_Click\((\d+),")
    URL_TEMPLATE = base_url + "/Detalhe.aspx?id={}" 
    
    for tr in rows:
        cols = tr.find_all("td")
        if len(cols) < 8:
            continue
            
        # Extração dos Campos Básicos por Índice
        title = cols[3].get_text(strip=True) # Coluna 3: Objeto/Descrição (Título)
        org = cols[2].get_text(strip=True)    # Coluna 2: Unidade Compradora (Órgão)
        published_date = cols[6].get_text(strip=True) # Coluna 6: Data/Hora Final (Publicado)
        
        # Extração da URL (Usando onclick da Coluna 7)
        url = None
        area_clique_span = cols[7].select_one("span.areaClique")
        
        if area_clique_span:
            onclick_attr = area_clique_span.get('onclick', '')
            match = ID_PATTERN.search(onclick_attr)
            
            if match:
                process_id = match.group(1) 
                url = URL_TEMPLATE.format(process_id) 

        if title and url: 
            items.append({
                "title": title, 
                "org": org, 
                "url": url, 
                "published": published_date
            })
        
    return items


def parse_bnc(html, base_url="https://bnccompras.com"):
    """
    Parser para o site BNC Compras. Este parser extrai as informações do site de licitações.
    """
    soup = BeautifulSoup(html, "lxml")
    items = []
    rows = soup.select("tr[style]")  # Assumindo que cada linha de licitação é um <tr> com estilo
    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 5:
            continue
        
        # Extração dos dados
        title = cols[1].get_text(strip=True)
        org = cols[0].get_text(strip=True)
        published = cols[3].get_text(strip=True)
        url = urllib.parse.urljoin(base_url, cols[1].select_one("a")["href"]) if cols[1].select_one("a") else None
        
        if title and url:
            items.append({
                "title": title,
                "org": org,
                "url": url,
                "published": published
            })
    return items


def parse_fiems_tabela(html, base_url="https://compras.fiems.com.br"):
    """
    Parser específico para o Mural de Compras da FIEMS.
    Extrai o ID da licitação do atributo onclick na Coluna 1 e o Objeto da Coluna 3.
    """
    soup = BeautifulSoup(html, "lxml")
    items = []
    
    rows = soup.select("tbody#trListaMuralProcesso tr")
    ID_PATTERN = re.compile(r"trListaMuralProcesso_Click\((\d+),")
    URL_TEMPLATE = base_url + "/Portal/Detalhe.aspx?id={}" 
    
    for tr in rows:
        cols = tr.find_all("td")
        
        if len(cols) < 8:
            continue
            
        # 1. Extração dos Campos Básicos por Índice
        # Coluna 1: Nome/Título Curto da Chamada
        title = cols[1].get_text(strip=True) 
        # Coluna 2: Órgão (SENAI, etc.)
        org = cols[2].get_text(strip=True)    
        # Coluna 3: Objeto/Descrição Completa
        obj = cols[3].get_text(strip=True)
        # Coluna 6: Data (campo de data)
        published_date = cols[6].get_text(strip=True) 
        
        # 2. Extração da URL (Usando onclick da Coluna 1)
        url = None
        area_clique_td = cols[1] 
        onclick_attr = area_clique_td.get('onclick', '')
        
        if onclick_attr:
            match = ID_PATTERN.search(onclick_attr)
            
            if match:
                process_id = match.group(1) 
                url = URL_TEMPLATE.format(process_id) 

        # Se o título e o URL foram encontrados, adiciona o item
        if title and url: 
            items.append({
                "title": title, 
                "org": org, 
                "obj": obj, # Novo campo
                "url": url, 
                "published": published_date
            })
        
    return items

# SITES
SITES = [
    {"name": "FIEP", "url": "https://portaldecompras.sistemafiep.org.br", "parser": parse_fiep, "base": "https://portaldecompras.sistemafiep.org.br"},
    {"name": "FIESC", "url": "https://portaldecompras.fiesc.com.br/Portal/Mural.aspx", "parser": parse_fiesc_tabela, "dynamic": True, "base": "https://portaldecompras.fiesc.com.br"},
    {"name": "FIEMS", 
     "url": "https://compras.fiems.com.br/portal/Mural.aspx?nNmTela=E", 
     "parser": parse_fiems_tabela, 
     "dynamic": True, 
     "base": "https://compras.fiems.com.br",
     # CONFIGURAÇÃO DE PARADA BASEADA EM DATA
     "stop_selector": "tbody#trListaMuralProcesso tr td:nth-child(7)",
     "date_threshold": 2024
    },
    {"name": "FIEMS", "url": "https://compras.fiems.com.br/portal/Mural.aspx?nNmTela=E", "parser": parse_fiems_tabela, "dynamic": True, "base": "https://compras.fiems.com.br"},
    {"name": "Licitacoes-e", "url": "https://www.licitacoes-e.com.br/aop/index.jsp?codSite=39763", "parser": parse_div_list, "dynamic": True, "base": "https://www.licitacoes-e.com.br"},
    {"name": "BNC", "url": "https://bnccompras.com/", "parser": parse_bnc, "dynamic": True, "base": "https://bnccompras.com"},
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
                    
                    # Usa fetch_dynamic_scroll para todos os sites dinâmicos agora
                    if site.get("dynamic"):
                        # Novos parâmetros: seletor de parada e data limite
                        stop_sel = site.get("stop_selector")
                        date_thres = site.get("date_threshold")
                        
                        html = fetch_dynamic_scroll(
                            site["url"], 
                            stop_selector=stop_sel, 
                            date_threshold=date_thres
                        )
                    else:
                        response = requests.get(site["url"], timeout=30)
                        response.raise_for_status()
                        html = response.text

                    print(f"[INFO] Página carregada: {len(html)} bytes")
                    
                    items = site["parser"](html, base_url=site.get("base"))
                    print(f"[INFO] {len(items)} itens encontrados em {site['name']}")
                    
                    new_count = 0
                    for item in items:
                        is_new, _ = is_new_and_save(item)
                        if is_new:
                            new_count += 1
                            msg = format_item_message(item)
                            ok, resp = send_telegram_message(msg)
                            print(f"[ALERTA] Novo item [{site['name']}]: {item['title']}", "Enviado" if ok else f"Erro: {resp}")
                    
                    print(f"[INFO] {new_count} novos alertas enviados para {site['name']}")
                
                except requests.exceptions.RequestException as e:
                    print(f"[ERRO] Falha de requisição no site {site['name']}: {e}")
                except Exception as e:
                    print(f"[ERRO] Site {site['name']}: {e}")
            
            print(f"[INFO] Dormindo {CHECK_INTERVAL_SECONDS} segundos...\n")
            time.sleep(CHECK_INTERVAL_SECONDS)
        
        except KeyboardInterrupt:
            print("Parando scraper...")
            break
        except Exception as e:
            print(f"[ERRO CRÍTICO] Falha no loop principal: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main_loop()