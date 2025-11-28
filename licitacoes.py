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

CHECK_INTERVAL_SECONDS = 15  # 1800 == 30 minutos

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

def generate_unique_id(item):
    # Gerar um ID único com base em campos fixos, como título e organização
    unique_str = (item['title'] or "") + "|" + (item['org'] or "")
    return hashlib.md5(unique_str.encode("utf-8")).hexdigest()

def is_new_and_save(item):
    # Gerar um ID único baseado no título e organização
    uid = generate_unique_id(item)
    
    # Verifica se o ID já existe no banco de dados
    cur.execute("SELECT 1 FROM notices WHERE id=%s", (uid,))
    if cur.fetchone():
        return False, uid  # Se já existe, não insere novamente
    
    try:
        # Inserir o item no banco de dados
        cur.execute(
            "INSERT INTO notices (id, title, org, url, published, raw_hash) VALUES (%s,%s,%s,%s,%s,%s)",
            (uid, item['title'], item['org'], item['url'], item['published'], hashlib.md5(json.dumps(item, ensure_ascii=False).encode('utf-8')).hexdigest())
        )
        conn.commit()
        return True, uid  # Item inserido com sucesso
    except Exception as e:
        conn.rollback()
        print(f"[ERRO SQL] Falha ao inserir item: {e}")
        return False, uid    
    
def escape_markdown(text):
    """
    Escapa os caracteres especiais usados no Markdown do Telegram, como:
    - _ (underline)
    - * (asterisco)
    - [ ] (colchetes)
    - ( ) (parênteses)
    - ~ (til)
    """
    # Escapa os caracteres que têm significado especial no Markdown
    text = re.sub(r'([\\`*_{}[\]()#+\-.!])', r'\\\1', text)
    return text

def send_telegram_message(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    # Escapa o texto usando a função de escape Markdown
    escaped_msg = escape_markdown(msg)

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": escaped_msg,
        "disable_web_page_preview": False,
        "parse_mode": "Markdown"
    }
    
    retries = 0
    max_retries = 5  # Limite de tentativas
    wait_time = 0  # Inicialmente sem tempo de espera

    while retries < max_retries:
        try:
            resp = requests.post(url, json=payload, timeout=15)
            if resp.ok:
                return True, resp.text
            elif resp.status_code == 429:
                # Extrai o tempo de espera recomendado (em segundos) da resposta
                retry_after = resp.json().get("parameters", {}).get("retry_after", 19)  # Valor padrão 19
                print(f"[ALERTA] Limite de requisições atingido. Esperando {retry_after} segundos...")
                time.sleep(retry_after)
                retries += 1
            else:
                return False, f"Erro desconhecido: {resp.text}"
        except requests.exceptions.RequestException as e:
            return False, f"Erro de conexão: {e}"

    return False, f"Falha após {max_retries} tentativas."

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

def fetch_details_page(url, base_url="https://bnccompras.com"):
    """
    Função para buscar a página de detalhes da licitação e extrair o objeto da licitação.
    """
    try:
        # Fazer a requisição para a página de detalhes
        response = requests.get(url, timeout=30)
        response.raise_for_status()  # Garante que o status seja 200 OK
        soup = BeautifulSoup(response.text, "lxml")
        
        # Procurar o campo "OBJETO" dentro da textarea
        objeto_textarea = soup.find("textarea", {"id": "ProductOrService"})
        
        if objeto_textarea:
            # Retorna o conteúdo do objeto
            return objeto_textarea.get_text(strip=True)
        else:
            return None  # Caso o objeto não seja encontrado
        
    except requests.exceptions.RequestException as e:
        print(f"[ERRO] Falha ao acessar a página de detalhes: {e}")
        return None

def parse_bnc(html, base_url="https://bnccompras.com"):
    """
    Parser para o site BNC Compras. Este parser extrai as informações do site de licitações,
    incluindo os detalhes da licitação após o clique no link.
    """
    soup = BeautifulSoup(html, "lxml")
    items = []

    # Encontrando todas as linhas de licitação dentro do corpo da tabela
    rows = soup.select("tbody#tableProcessDataBody tr")
    
    for row in rows:
        # Extração de todas as células de cada linha
        cols = row.find_all("td")
        
        # Se a linha não tiver o número esperado de células, ignoramos
        if len(cols) < 8:
            continue

        # Extrair os dados das células específicas
        url_el = cols[0].select_one("a")  # Link do processo
        url = urllib.parse.urljoin(base_url, url_el["href"]) if url_el else None
        org = cols[1].get_text(strip=True)  # Nome da organização
        licitacao_codigo = cols[2].get_text(strip=True)  # Código da licitação (35/2025)
        tipo_licitacao = cols[3].get_text(strip=True)  # Tipo de licitação (PREGÃO ELETRÔNICO)
        local = cols[4].get_text(strip=True)  # Localização (PAIÇANDU-PR)
        objeto = cols[5].get_text(strip=True)  # Objeto (RECEPÇÃO DE PROPOSTAS)
        data_abertura = cols[6].get_text(strip=True)  # Data de Abertura (26/11/2025 10:36)
        data_encerramento = cols[7].get_text(strip=True)  # Data de Encerramento (11/12/2025 09:00)

        # Agora, vamos buscar os detalhes do objeto da licitação, clicando no link
        if url:
            # Acessando a página de detalhes
            objeto_detalhado = fetch_details_page(url, base_url)
        else:
            objeto_detalhado = None
        
        # Se encontramos o objeto detalhado, usamos ele, senão mantemos o objeto atual
        objeto = objeto_detalhado if objeto_detalhado else objeto

        # Adicionando o item ao array de items
        items.append({
            "title": licitacao_codigo,  # Usando o código da licitação como título
            "org": org,
            "url": url,
            "published": data_abertura,
            "obj": objeto,  # Objeto da licitação, agora detalhado se disponível
            "location": local,
            "closing_date": data_encerramento
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


def parse_sanesul_from_playwright_content(html, base_url="https://www.sanesul.ms.gov.br"):
    """
    Parser robusto para o HTML da Sanesul.
    """
    soup = BeautifulSoup(html, "lxml")
    items = []

    table = soup.find("table", {"id": "conteudo_gridLicitacao"})
    if not table:
        print("[ERRO PARSER] Tabela de licitações não encontrada no HTML.")
        return items, None 

    rows = table.find_all("tr")[1:] 

    for row in rows:
        cols = row.find_all("td")
        
        # --- FILTRO A: Linha de Paginação / Sub-Tabela / Lixo ---
        # 1. Linhas com apenas uma coluna são provavelmente a paginação ou subtítulos.
        if len(cols) == 1:
            # Garante que ignora a linha que contém o bloco de paginação
            if cols[0].find("a", href=lambda x: x and "__doPostBack" in x):
                 continue
            continue
        
        # 2. Licitações válidas devem ter EXATAMENTE 6 colunas de dados.
        if len(cols) != 6:
            continue
        
        # --- EXTRAÇÃO DE DADOS ---
        
        numero = cols[0].get_text(strip=True)
        ano = cols[1].get_text(strip=True)
        objeto = cols[2].get_text(strip=True)
        data_abertura = cols[3].get_text(strip=True)
        fuso_horario = cols[4].get_text(strip=True)
        link_mais_detalhes = cols[5].find("a", {"title": "Mais detalhes da Licitação!"})

        # --- FILTRO B: Validação de Dados Úteis ---
        
        # Um registro de licitação deve ter um link de detalhes
        if not link_mais_detalhes:
             continue
             
        # O campo Número e Ano devem ser (ou começar com) dígitos
        if not (numero.strip().isdigit() and ano.strip().isdigit()):
            # Se for o caso de "1/2" em uma única célula ou outro lixo, ignora
            # Se o filtro anterior de 'len(cols) != 6' falhar, este pega o lixo.
            continue
            
        # Não extrai linhas que claramente são cabeçalhos ou totais
        if "Número" in numero or "Ano" in ano or "Total" in numero:
            continue 

        # --- ARMAZENAMENTO ---
        detalhes_url = link_mais_detalhes.get("href")
            
        items.append({
            "title": f"Licitação {numero}/{ano}",
            "org": "Sanesul",
            "obj": objeto,
            "url": detalhes_url, 
            "published": data_abertura,
            "fuso_horario": fuso_horario
        })

    return items, None

def fetch_sanesul_playwright(url, base_url="https://www.sanesul.ms.gov.br"):
    all_items = []
    
    with sync_playwright() as p:
        # Inicia o navegador (Chrome)
        browser = p.chromium.launch(headless=True) # Use headless=False para debugar visualmente
        page = browser.new_page()
        
        print(f"[PLAYWRIGHT] Navegando para a URL inicial: {url}")
        page.goto(url, timeout=60000)

        current_page_num = 1
        
        while True:
            print(f"[PLAYWRIGHT] Processando Página {current_page_num}...")
            
            # 1. Obter o conteúdo HTML da página atual
            html_content = page.content()
            
            # 2. Chamar o seu parser para extrair os dados desta página
            # O parser deve retornar uma lista de itens e ignorar o link de próxima página.
            items_da_pagina, _ = parse_sanesul_from_playwright_content(html_content, base_url)
            
            if not items_da_pagina and current_page_num > 1:
                # Se não houver itens em uma página que não é a primeira, consideramos o fim.
                print(f"[PLAYWRIGHT] Nenhuma licitação encontrada na página {current_page_num}. Fim.")
                break
            
            all_items.extend(items_da_pagina)
            
            # 3. Preparar a busca pelo link da próxima página
            
            # O valor exato do postback para a próxima página (Ex: 'Page$2', 'Page$3', etc.)
            target_postback_value = f"Page${current_page_num + 1}"

            # Localizador robusto que busca o link com o valor de postback exato no atributo href
            # Isso garante que estamos procurando o link certo para avançar.
            next_link_locator = page.locator(
                f"a[href*='{target_postback_value}'][href*='gridLicitacao']"
            )

            # 4. Verifique se o link da próxima página existe e é visível/clicável
            if not next_link_locator.is_visible():
                print("[PLAYWRIGHT] Fim da paginação. Link da próxima página (PostBack) não encontrado.")
                break
                
            try:
                # 5. Clicar no link e esperar o recarregamento do conteúdo.
                print(f"[PLAYWRIGHT] Clicando no link da página {current_page_num + 1}...")
                
                # Clique síncrono
                next_link_locator.click() 
                
                # *** ADICIONE ESTA LINHA ***
                # Aguarda que a tabela principal 'conteudo_gridLicitacao' esteja visível no DOM
                page.wait_for_selector("#conteudo_gridLicitacao", state="visible", timeout=10000)
                
                current_page_num += 1

            except Exception as e:
                print(f"[ERRO PLAYWRIGHT] Falha ao clicar no link da página {current_page_num + 1}: {e}")
                break

        browser.close()
    return all_items

# SITES
SITES = [
    #{"name": "FIEP", "url": "https://portaldecompras.sistemafiep.org.br", "parser": parse_fiep, "base": "https://portaldecompras.sistemafiep.org.br"},
    #{"name": "FIESC", "url": "https://portaldecompras.fiesc.com.br/Portal/Mural.aspx", "parser": parse_fiesc_tabela, "dynamic": True, "base": "https://portaldecompras.fiesc.com.br"},
    #{"name": "FIEMS", 
    # "url": "https://compras.fiems.com.br/portal/Mural.aspx?nNmTela=E", 
    # "parser": parse_fiems_tabela, 
    #"dynamic": True, 
    # "base": "https://compras.fiems.com.br",
     # CONFIGURAÇÃO DE PARADA BASEADA EM DATA
    # "stop_selector": "tbody#trListaMuralProcesso tr td:nth-child(7)",
    # "date_threshold": 2024
    #},
    #{"name": "Licitacoes-e", "url": "https://www.licitacoes-e.com.br/aop/index.jsp?codSite=39763", "parser": parse_div_list, "dynamic": True, "base": "https://www.licitacoes-e.com.br"},
    #{"name": "BNC", "url": "https://bnccompras.com/Process/ProcessSearchPublic?param1=0", "parser": parse_bnc, "dynamic": True, "base": "https://bnccompras.com/Process/ProcessSearchPublic?param1=0"},
    {"name": "Sanesul", 
     "url": "https://www.sanesul.ms.gov.br/licitacao/tipolicitacao/licitacao", 
     "parser": parse_sanesul_from_playwright_content, 
     "dynamic": False,
     "base": "https://www.sanesul.ms.gov.br",
     "stop_selector": "table#conteudo_gridLicitacao tr td:nth-child(4)", 
     "date_threshold": 2025},
    #{"name": "Casan", "url": "https://www.casan.com.br/menu-conteudo/index/url/licitacoes-em-andamento#0", "parser": parse_div_list, "dynamic": True, "base": "https://www.casan.com.br"},
]

# LOOP PRINCIPAL
# LOOP PRINCIPAL
def main_loop():
    while True:
        try:
            for site in SITES:
                
                # --- TRATAMENTO ESPECIAL PARA SANESUL (PAGINAÇÃO ESTÁTICA) ---
                if site['name'] == 'Sanesul':
                    print(f"[INFO] Buscando site: {site['name']} (Paginação via Playwright)")
    
                    # CHAMA A NOVA FUNÇÃO DE FETCH COM PLAYWRIGHT
                    items = fetch_sanesul_playwright(site['url'], site['base'])
    
                    print(f"[INFO] {len(items)} itens encontrados em {site['name']}")
    
                    # Prossiga para o processamento de novos itens (RESTANTE DO CÓDIGO PERMANECE IGUAL)
                    new_count = 0
                    for item in items:
                        is_new, _ = is_new_and_save(item)
                        if is_new:
                            new_count += 1
                            msg = format_item_message(item)
                            ok, resp = send_telegram_message(msg)
                            print(f"[ALERTA] Novo item [{site['name']}]: {item['title']}", "Enviado" if ok else f"Erro: {resp}")
                    
                    print(f"[INFO] {new_count} novos alertas enviados para {site['name']}")
                    continue # Pula para o próximo site                

                # --- FLUXO PADRÃO (Dinâmico ou Estático de página única) ---
                try:
                    print(f"[INFO] Buscando site: {site['name']} ({site['url']})")
                    
                    if site.get("dynamic"):
                        # ... lógica original do fetch_dynamic_scroll ...
                        stop_sel = site.get("stop_selector")
                        date_thres = site.get("date_threshold")
                        
                        html = fetch_dynamic_scroll(
                            site["url"], 
                            stop_selector=stop_sel, 
                            date_threshold=date_thres
                        )
                        items = site["parser"](html, base_url=site.get("base"))
                    else:
                        response = requests.get(site["url"], timeout=30)
                        response.raise_for_status()
                        html = response.text
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