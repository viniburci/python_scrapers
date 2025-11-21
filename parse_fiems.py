# Importações necessárias
import re
import urllib.parse
import json
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import time # Importado para a função fetch_dynamic_scroll

# URL e Base URL do site FIEMS
FIEMS_URL = "https://compras.fiems.com.br/portal/Mural.aspx?nNmTela=E"
BASE_URL = "https://compras.fiems.com.br"

# ==============================================================================
# 1. FUNÇÃO DE FETCH DINÂMICO (Adaptada para Playwright)
# Use esta função (ou sua versão mais atualizada) para buscar o HTML
# ==============================================================================

def fetch_dynamic_scroll(url, wait_selector="tbody#trListaMuralProcesso", load_more_selector=None):
    """
    Busca o HTML usando o Playwright e simula a rolagem da página 
    para carregar todos os resultados via lazy loading (scroll).
    """
    with sync_playwright() as p:
        # Use headless=False para ver o que o navegador está fazendo (opcional)
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, timeout=60000)
        
        try:
            # Espera inicial para o primeiro bloco de conteúdo da tabela
            page.wait_for_selector(wait_selector, timeout=30000)
        except:
            print("[FETCH] Aviso: O seletor de espera inicial não foi encontrado.")
            pass

        print("[FETCH] Iniciando rolagem para carregar mais itens (FIEMS)...")
        
        last_height = -1
        scroll_attempts = 0
        MAX_SCROLL_ATTEMPTS = 50 

        while scroll_attempts < MAX_SCROLL_ATTEMPTS:
            # Rola até o final da página
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            
            # Espera o novo conteúdo ser carregado
            time.sleep(1.5) # Tempo de espera reduzido para 1.5s
            
            # Verifica se o tamanho do conteúdo aumentou
            new_height = page.evaluate("document.body.scrollHeight")
            
            if new_height == last_height:
                # Se o tamanho não mudou, chegamos ao final da lista
                print(f"[FETCH] Fim da lista. Todos os itens carregados após {scroll_attempts} rolagens.")
                break
            
            last_height = new_height
            scroll_attempts += 1

        if scroll_attempts == MAX_SCROLL_ATTEMPTS:
            print(f"[FETCH] Aviso: Limite de {MAX_SCROLL_ATTEMPTS} rolagens atingido.")

        html = page.content()
        browser.close()
        return html


# ==============================================================================
# 2. FUNÇÃO PARSER: parse_fiems_tabela
# ==============================================================================

def parse_fiems_tabela(html, base_url):
    """
    Parser específico para o Mural de Compras da FIEMS.
    Extrai o ID da licitação do atributo onclick na Coluna 1.
    """
    soup = BeautifulSoup(html, "lxml")
    items = []
    
    # Seletor: Busca as linhas (tr) dentro da <tbody> com o ID específico
    rows = soup.select("tbody#trListaMuralProcesso tr")
    
    # Regex: Procura a função trListaMuralProcesso_Click e captura o primeiro número (o ID)
    ID_PATTERN = re.compile(r"trListaMuralProcesso_Click\((\d+),")
    
    # Template do URL de detalhes (formato provável para este portal)
    URL_TEMPLATE = base_url + "/Portal/Detalhe.aspx?id={}" 
    
    if not rows:
        print("[PARSER] Alerta: Não foram encontradas linhas de licitação no HTML.")

    for tr in rows:
        cols = tr.find_all("td")
        
        # Mínimo de colunas esperado: 8
        if len(cols) < 8:
            continue
            
        # 1. Extração dos Campos Básicos por Índice
        # Coluna 1: Nome/Título Curto da Chamada
        title = cols[1].get_text(strip=True) 
        # Coluna 2: Órgão (SENAI, etc.)
        org = cols[2].get_text(strip=True)    
        # Coluna 3:
        obj = cols[3].get_text(strip=True)  # Coluna 3: Objeto/Descrição (opcional)
        # Coluna 6: Data (campo de data)
        published_date = cols[6].get_text(strip=True) 
        
        
        # 2. Extração da URL (Usando onclick da Coluna 1)
        url = None
        
        # O elemento clicável (com onclick) é a própria tag <td> na Coluna 1 (índice 1)
        area_clique_td = cols[1] 
        onclick_attr = area_clique_td.get('onclick', '')
        
        if onclick_attr:
            match = ID_PATTERN.search(onclick_attr)
            
            if match:
                process_id = match.group(1) # Captura o ID numérico
                url = URL_TEMPLATE.format(process_id) # Constrói o URL

        # Se o título e o URL foram encontrados, adiciona o item
        if title and url: 
            items.append({
                "title": title, 
                "org": org, 
                "obj": obj,
                "url": url, 
                "published": published_date
            })
        
    return items

# ==============================================================================
# 3. EXECUÇÃO DO TESTE
# ==============================================================================

if __name__ == "__main__":
    print("--- 🌐 Teste Real do Parser FIEMS ---")
    
    try:
        # 1. Busca o HTML real e dinâmico, rolando a página
        html_real = fetch_dynamic_scroll(FIEMS_URL)
        
        # 2. Processa o HTML com o parser
        resultados = parse_fiems_tabela(html_real, BASE_URL)
        
        print(f"\n✅ Total de itens encontrados no site real: {len(resultados)}\n")
        
        # 3. Imprime os 5 primeiros resultados para verificação
        if resultados:
            print("--- 5 Primeiras Licitações Encontradas ---")
            for i, item in enumerate(resultados[:5], 1):
                print(f"--- Licitação {i} ---")
                print(f"Título:    {item['title']}")
                print(f"Órgão:     {item['org']}")
                print(f"Objeto:    {item['obj']}")
                print(f"Data:      {item['published']}")
                print(f"URL:       {item['url']}")
                print("-" * 25)
        else:
            print("⚠️ Nenhuma licitação foi encontrada. Verifique o seletor na função fetch_dynamic_scroll.")

    except Exception as e:
        print(f"\n❌ Ocorreu um erro durante o teste: {e}")
        print("Certifique-se de que o Playwright está instalado e os drivers estão configurados (`python -m playwright install`).")