import hashlib
import time
import json
import requests
import urllib.parse
import re
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import psycopg2
from playwright.async_api import async_playwright

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
    unique_str = (item['title'] or "") + "|" + (item['org'] or "") + "|" + (item['url'] or "")
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


# --- PARSERS ESPECÍFICOS ---

def fetch_fiep_sync(url, **kwargs):
    """
    Função síncrona que usa Playwright para buscar o conteúdo dinâmico.
    """
    print(f"[FETCH] Usando Playwright (síncrono) para carregar: {url}")
    
    html_content = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            
            page.goto(url, wait_until="networkidle") # Espera a rede estabilizar
            
            # Espera até que a lista de licitações apareça (seletor principal)
            page.wait_for_selector(".tab-noticias article.edital", timeout=20000)
            
            # Extrai o HTML do contêiner que segura as licitações
            html_content = page.inner_html("#licitacoes-list")
            
            browser.close()
            
    except Exception as e:
        print(f"[ERRO PLAYWRIGHT] Falha ao buscar conteúdo dinâmico: {e}")
        html_content = None
        
    return html_content

def fetch_static(url, **kwargs):
    """
    Função síncrona para requisições estáticas (simples requests).
    """
    print(f"[FETCH] Usando requests (estático) para buscar: {url}")
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.text

# --- 3. FUNÇÕES DE PARSING ---

def parse_fiep(html, base_url=""):
    """
    Parser para o Portal de Compras da FIEP, corrigido e robusto.
    """
    soup = BeautifulSoup(html, "lxml")
    items = []
    
    for artigo in soup.select("article.edital"):
        
        # Inicialização das variáveis
        title = "Sem modalidade"
        org = ""
        date = ""
        objeto = None
        url = None 
        lic_id = None
        
        # 1. Extração do Título (Modalidade)
        h3 = artigo.select_one("h3")
        title = h3.get_text(strip=True) if h3 else title
        
        # 2. Extração do Órgão (SESI/SENAI)
        empresa_div = artigo.select_one("div.header div.empresas")
        org = empresa_div.get_text(strip=True) if empresa_div else ""
                 
        # 3. Extração da Data (Data da abertura da proposta)
        p_data = artigo.find("p", string=lambda x: x and "Data da abertura da proposta:" in x)
        if p_data:
            date = p_data.get_text(strip=True).replace("Data da abertura da proposta:", "").strip()

        # 4. Extração do Objeto (Descrição Longa)
        # Busca o último <p> que não seja Status, Data ou Empresa Contratante
        paragrafos_dados = artigo.select("div.dados > p.body")
        for p in reversed(paragrafos_dados):
            p_text = p.get_text(strip=True)
            if 'Status:' in p_text or 'Data da abertura da proposta:' in p_text or 'Empresa Contratante' in p_text or not p_text:
                continue
            if len(p_text) > 10: 
                objeto = p_text
                break
            
        # 5. Extração da URL (Link do Edital/Documento Principal)
        link_el = artigo.select_one("ul.documentos li strong:-soup-contains('Edital') + ul a[href]")
        if not link_el:
            link_el = artigo.select_one("ul.documentos li strong:-soup-contains('CHAMAMENTO PÚBLICO') + ul a[href]")
        
        if link_el:
            url = urllib.parse.urljoin(base_url, link_el.get("href"))
            
        # 6. Geração do ID e Adição do Item
        if url: 
            numero_el = artigo.select_one("div.header div.numero")
            lic_id_full_text = numero_el.get_text(strip=True) if numero_el else url
            
            # Extrai o número da licitação
            lic_id = lic_id_full_text.split('|')[1].strip() if '|' in lic_id_full_text else lic_id_full_text
            
            items.append({
                "id": lic_id, 
                "title": title, 
                "org": org, 
                "url": url, 
                "published": date,
                "obj": objeto 
            })
            
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
    # NOVO: Variável para armazenar o ano da última licitação (útil para o filtro)
    last_item_year = None 

    table = soup.find("table", {"id": "conteudo_gridLicitacao"})
    if not table:
        print("[ERRO PARSER] Tabela de licitações não encontrada no HTML.")
        return items, last_item_year # Retorna com last_item_year = None

    rows = table.find_all("tr")[1:] 

    for row in rows:
        # ... (Filtros A, B e Extração de Dados)
        cols = row.find_all("td")
        
        # --- FILTRO A: Linha de Paginação / Sub-Tabela / Lixo ---
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
        if not link_mais_detalhes:
            continue
            
        if not (numero.strip().isdigit() and ano.strip().isdigit()):
            continue
            
        if "Número" in numero or "Ano" in ano or "Total" in numero:
            continue 

        # --- ARMAZENAMENTO ---
        detalhes_url = link_mais_detalhes.get("href")
            
        items.append({
            "title": f"Licitação {numero}/{ano}",
            "org": "Sanesul",
            "obj": objeto,
            "url": detalhes_url, 
            # NOVO: O ano está na coluna 1, então podemos usar ele para validação
            "published": f"{data_abertura} {ano}", # Inclui o ano no campo published para o filtro final
            "fuso_horario": fuso_horario
        })
        
        # NOVO: Atualiza o ano do último item válido
        last_item_year = ano 

    # NOVO: Retorna a lista de itens E o ano do último item válido.
    return items, last_item_year


def fetch_sanesul_playwright(url, base_url="https://www.sanesul.ms.gov.br"):
    all_items = []
    
    # 
    # >>> NOVO: Extrair configurações de parada do dicionário SITES
    #
    site_config = next((s for s in SITES if s['name'] == 'Sanesul'), {})
    date_threshold_str = str(site_config.get("date_threshold")) if site_config.get("date_threshold") else None
    
    with sync_playwright() as p:
        # ... (código para iniciar browser e page)
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        print(f"[PLAYWRIGHT] Navegando para a URL inicial: {url}")
        page.goto(url, timeout=60000)

        current_page_num = 1
        
        while True:
            print(f"[PLAYWRIGHT] Processando Página {current_page_num}...")
            
            # 1. Obter o conteúdo HTML da página atual
            html_content = page.content()
            
            # 2. Chamar o seu parser para extrair os dados desta página
            # O parser agora retorna a lista de itens e o ano do ÚLTIMO item.
            items_da_pagina, last_item_year = parse_sanesul_from_playwright_content(html_content, base_url)
            
            #
            # >>> NOVO: Lógica de Parada de Ano!
            #
            if date_threshold_str and last_item_year and last_item_year < date_threshold_str:
                print(f"[PLAYWRIGHT] Condição de parada atingida. Último item é de {last_item_year}. Parando a paginação.")
                
                #
                # >>> NOVO: Filtrar apenas os itens da página atual que são de 2025
                #
                items_2025_only = [
                    item for item in items_da_pagina
                    if item.get('published', '').strip().endswith(date_threshold_str) # Filtra pelo ano no campo 'published'
                ]
                all_items.extend(items_2025_only)
                break 
                
            if not items_da_pagina and current_page_num > 1:
                print(f"[PLAYWRIGHT] Nenhuma licitação encontrada na página {current_page_num}. Fim.")
                break
                
            all_items.extend(items_da_pagina)
            
            # 3. Preparar a busca pelo link da próxima página
            # ... (código para encontrar next_link_locator)
            target_postback_value = f"Page${current_page_num + 1}"
            next_link_locator = page.locator(
                f"a[href*='{target_postback_value}'][href*='gridLicitacao']"
            )

            # 4. Verifique se o link da próxima página existe e é visível/clicável
            if not next_link_locator.is_visible():
                print("[PLAYWRIGHT] Fim da paginação. Link da próxima página (PostBack) não encontrado.")
                break
                
            try:
                # 5. Clicar no link e esperar o recarregamento do conteúdo.
                # ... (código para clicar e esperar)
                print(f"[PLAYWRIGHT] Clicando no link da página {current_page_num + 1}...")
                next_link_locator.click() 
                page.wait_for_selector("#conteudo_gridLicitacao", state="visible", timeout=10000)
                current_page_num += 1

            except Exception as e:
                print(f"[ERRO PLAYWRIGHT] Falha ao clicar no link da página {current_page_num + 1}: {e}")
                break

        browser.close()
    
    #
    # >>> NOVO: No final, se a parada não foi por ano, filtra o que sobrou.
    #
    if date_threshold_str:
        all_items = [
            item for item in all_items 
            if item.get('published', '').strip().endswith(date_threshold_str)
        ]
        
    return all_items


def fetch_casan_form(url="https://www.casan.com.br/licitacoes/editais"):
    """
    Busca os dados de licitações da CASAN interagindo com o formulário SELECT/Pesquisar,
    com foco na condição de espera pelo carregamento dos resultados.
    """
    
    anos_desejados = ["2025"]
    html_combinado = ""
    
    SELECT_ANO_SELECTOR = '#licitacao_ano'
    BUTTON_PESQUISAR_SELECTOR = '#btnBuscar'
    RESULT_CONTAINER_SELECTOR = '.editais-visualiza-container'
    
    # Seletor de uma linha de resultado dentro do container
    RESULT_ITEM_SELECTOR = f'{RESULT_CONTAINER_SELECTOR} table.table-bordered' 

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            
            print(f"[INFO] Navegando para {url} e interagindo com o formulário...")
            page.goto(url, wait_until="networkidle", timeout=60000) 
            
            for ano in anos_desejados:
                print(f"[INFO] Selecionando ano: {ano}...")
                
                # 1. Seleciona o valor no dropdown
                page.select_option(SELECT_ANO_SELECTOR, value=ano)
                
                # 2. Clica no botão 'Pesquisar'
                print(f"[INFO] Clicando em 'Pesquisar' para o ano {ano}...")
                page.click(BUTTON_PESQUISAR_SELECTOR)
                
                # 3. GARANTIA DE ESPERA:
                # Tentativa A: Esperar pela mensagem de quantidade, ou que uma tabela apareça.
                try:
                    # Espera que o container tenha resultados (mensagem "Quantidade:")
                    # ou uma tabela de licitação (se não houver resultados, espera apenas 5s)
                    page.wait_for_selector(
                        f'{RESULT_CONTAINER_SELECTOR}:has-text("Quantidade:") , {RESULT_ITEM_SELECTOR}',
                        timeout=15000 # Tempo de espera reduzido para 15s (mais rápido que 30s default)
                    )
                except Exception:
                    # Se não aparecer nada em 15s, assumimos que não há resultados (0 itens) e continuamos
                    print(f"[INFO] Nenhum resultado carregado para o ano {ano}. Prosseguindo...")
                
                
                # 4. Coleta o HTML da div de resultados
                # Se o seletor falhar aqui, indica que o elemento não foi encontrado
                html_parte = page.inner_html(RESULT_CONTAINER_SELECTOR)
                html_combinado += html_parte
                
            browser.close()
            return html_combinado
            
    except Exception as e:
        print(f"[ERRO] Falha na interação dinâmica da CASAN: {e}")
        try:
            if 'browser' in locals() and browser:
                 browser.close()
        except:
            pass
        return None


def parse_casan_list(html, base_url="https://www.casan.com.br"):
    """
    Parser adaptado para o HTML retornado pelo fetch_casan_form ou fetch_casan_ajax.
    Busca todas as tabelas de licitação (combinando os anos 2025 e 2024, se aplicável).
    """
    if not html:
        return []
        
    soup = BeautifulSoup(html, "lxml")
    items = []
    
    licitacao_tables = soup.select("table.table-bordered") 
    
    # 2. Iterar sobre cada tabela que representa uma licitação
    for table in licitacao_tables:
        try:
            # Inicializa as variáveis para cada item
            modalidade = ""
            titulo_edital = ""
            objeto = ""
            data_abertura = ""
            url_arquivos = ""

            # --- 1. Extração de Modalidade e Edital para o Título ---
            # CORREÇÃO: Usando 'string='
            modalidade_row = table.find("td", string=lambda t: t and "Modalidade:" in t)
            if modalidade_row:
                modalidade = modalidade_row.find_next_sibling("td").get_text(strip=True)
            
            # CORREÇÃO: Usando 'string='
            edital_row = table.find("td", string=lambda t: t and "Edital:" in t)
            if edital_row:
                titulo_edital = edital_row.find_next_sibling("td").get_text(strip=True)
                # Combine Modalidade e Edital para um título mais completo
                title = f"[{modalidade}] {titulo_edital}"
            else:
                # Se não encontrar o Edital, usa Modalidade como título
                title = modalidade if modalidade else "Licitação (Sem Título)"
            
            # --- 2. Extração da Data de Abertura (para Published) ---
            # CORREÇÃO: Usando 'string='
            # Busca a data de abertura das propostas ou a data de disputa
            data_row = table.find("td", string=lambda t: t and ("Abertura das propostas:" in t or "Disputa de preços:" in t))
            if data_row:
                # O texto deve ser extraído do <b> dentro da próxima <td>
                data_abertura = data_row.find_next_sibling("td").find('b').get_text(strip=True)
            
            # --- 3. Extração do Objeto (Descrição) ---
            # CORREÇÃO: Usando 'string='
            objeto_row = table.find("td", string=lambda t: t and "Objeto:" in t)
            if objeto_row:
                objeto_td = objeto_row.find_next_sibling("td")
                objeto = objeto_td.get_text(strip=True)
                # O Objeto está bagunçado, vamos limpá-lo, removendo a referência ao Licitações-e
                if 'Licitações-e' in objeto:
                     objeto = objeto.split("Licitações-e:")[0].strip()
            
            # --- 4. Extração do URL para os Arquivos ---
            link_tag = table.select_one('a.btn_arquivos[href*="/licitacoes/editais-arquivos/licitacao_id/"]')
            if link_tag:
                url_arquivos = urllib.parse.urljoin(base_url, link_tag.get("href"))
            
            # Adiciona o item se encontrarmos um link de arquivos (indicativo de licitação válida)
            if url_arquivos:
                items.append({
                    "title": title, 
                    "org": "CASAN", 
                    "obj": objeto, 
                    "url": url_arquivos, 
                    "published": data_abertura 
                })

        except Exception as e:
            # Em caso de erro de parse, logamos e ignoramos a tabela
            print(f"[ERRO] Falha ao processar tabela da CASAN: {e}")
            continue
            
    return items
    

# SITES
SITES = [
    {"name": "FIEP", 
     "url": "https://portaldecompras.sistemafiep.org.br", 
     "parser": parse_fiep, 
     "base": "https://portaldecompras.sistemafiep.org.br", 
     "dynamic": True, 
     "fetcher": fetch_fiep_sync
     },
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
    #{"name": "Sanesul", 
    # "url": "https://www.sanesul.ms.gov.br/licitacao/tipolicitacao/licitacao", 
    # "parser": parse_sanesul_from_playwright_content, 
    #"dynamic": False,
    # "base": "https://www.sanesul.ms.gov.br",
    # "stop_selector": "table#conteudo_gridLicitacao tr td:nth-child(4)", 
    # "date_threshold": 2025},
    #{"name": "Casan", 
    # "url": "https://www.casan.com.br/licitacoes/editais", 
    # "parser": parse_casan_list, 
    # "dynamic": True, # Define como dinâmico para usar a lógica de fetchers customizados/Playwright
    # "base": "https://www.casan.com.br",
    # "fetcher": fetch_casan_form 
    #},
]

# LOOP PRINCIPAL
import time
import requests
from playwright.sync_api import sync_playwright
# Importe aqui as suas funções auxiliares

def main_loop():
    """
    Loop principal que itera sobre os sites e extrai o conteúdo.
    CORREÇÃO APLICADA: Interação por clique no elemento visível para ordenação da FIEP.
    """
    while True:
        try:
            for site in SITES:
                
                if site['name'] == 'Sanesul':
                    print(f"[INFO] Ignorando Sanesul (Tratamento especial/separado)...")
                    continue 
                
                try:
                    print(f"\n[INFO] Buscando site: {site['name']} ({site['url']})")
                    
                    html = None
                    
                    if site.get("fetcher") and site['name'] != 'FIEP': 
                        html = site["fetcher"](url=site["url"])
                    
                    # 2. FLUXO EXCLUSIVO PARA FIEP (Playwright com Interação por Clique)
                    elif site['name'] == 'FIEP':
                        print("[FETCH] Usando Playwright (síncrono) INLINE para FIEP (garantindo ordenação 'Mais recentes primeiro').")
                        try:
                            with sync_playwright() as p:
                                browser = p.chromium.launch() 
                                page = browser.new_page()
                                
                                page.goto(site["url"], wait_until="domcontentloaded") 
                                
                                # =========================================================================
                                # CORREÇÃO DO TIMEOUT: Simulação de clique no dropdown customizado
                                # =========================================================================
                                print("[INFO] Tentando simular cliques para ordenação...")
                                
                                # 1. Clica no elemento visível que simula o dropdown (div com 'select-selected')
                                # Seletor: Busca a classe '.select-selected' dentro da classe '.select-ordering'
                                page.click('.select-ordering .select-selected') 
                                page.wait_for_timeout(500) # Pausa curta para a animação abrir o dropdown
                                
                                # 2. Clica na opção "Mais recentes primeiro" (que é o segundo item da lista de opções simulada)
                                # Seletor: Busca a segunda div (nth=1) dentro de '.select-items' na classe '.select-ordering'
                                page.click('.select-ordering .select-items div >> nth=1') 
                                
                                print("[INFO] Ordenação aplicada (Mais recentes primeiro). Aguardando carregamento...")
                                
                                # 3. Esperas:
                                page.wait_for_selector(".tab-noticias article.edital", timeout=30000) 
                                page.wait_for_timeout(2000) 
                                # =========================================================================

                                # Extrai o HTML da div que contém a lista de licitações já ordenada
                                html = page.inner_html("#licitacoes-list")
                                browser.close()
                                
                        except Exception as e:
                            print(f"[ERRO PLAYWRIGHT/FIEP] Falha ao buscar e ordenar conteúdo: {e}")
                            html = None
                    
                    # 3. FLUXO DINÂMICO/ESTÁTICO (Outros sites)
                    elif site.get("dynamic"):
                        # ... (Seu código original para fetch_dynamic_scroll) ...
                        pass
                    else:
                        response = requests.get(site["url"], timeout=30)
                        response.raise_for_status() 
                        html = response.text

                    # --- Processamento Comum ---
                    items = []
                    if html:
                        items = site["parser"](html, base_url=site.get("url"))

                    print(f"[INFO] {len(items)} itens encontrados em {site['name']}")
                    
                    # --- Lógica de Alerta e OTIMIZAÇÃO DE PARADA ---
                    new_count = 0
                    for item in items:
                        is_new, _ = is_new_and_save(item) 
                        
                        if is_new:
                            new_count += 1
                            msg = format_item_message(item)
                            ok, resp = send_telegram_message(msg)
                            print(f"[ALERTA] Novo item [{site['name']}]: {item['title']}", 
                                    ("-> Enviado!" if ok else f"-> ERRO TELEGRAM: {resp}"))
                        else:
                            # OTIMIZAÇÃO: Para a verificação ao encontrar um item antigo (pois está ordenado)
                            print(f"[INFO] Item '{item.get('title', 'Sem Título')}' já processado. Interrompendo a verificação.")
                            break 
                            
                    print(f"[INFO] {new_count} novos alertas enviados para {site['name']}")

                except requests.exceptions.RequestException as e:
                    print(f"[ERRO] Falha de requisição no site {site['name']} (HTTP/Rede): {e}")
                except Exception as e:
                    print(f"[ERRO] Site {site['name']} falhou no processamento (Parsing/Outro): {e}")
        
        except Exception as loop_error:
            print(f"[ERRO GRAVE] Falha no loop principal de sites: {loop_error}")
            
        # --- Tempo de Espera ---
        sleep_time = 30
        print(f"\n[INFO] Ciclo completo. Dormindo {sleep_time} segundos...")
        time.sleep(sleep_time)

if __name__ == "__main__":
    main_loop()