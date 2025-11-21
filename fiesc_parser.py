# Importações necessárias
import urllib.parse
import re
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# URL do site da FIESC
FIESC_URL = "https://portaldecompras.fiesc.com.br/Portal/Mural.aspx"
BASE_URL = "https://portaldecompras.fiesc.com.br"

# ==============================================================================
# 1. FUNÇÕES ESSENCIAIS (Copiadas do seu script principal)
# ==============================================================================

def fetch_dynamic(url, wait_selector="table, div"):
    """Busca o HTML usando o Playwright para conteúdo dinâmico."""
    with sync_playwright() as p:
        # Nota: headless=True significa que o navegador não será visível
        browser = p.chromium.launch(headless=True) 
        page = browser.new_page()
        print(f"[FETCH] Acessando: {url}")
        page.goto(url, timeout=60000)
        try:
            # Espera carregar uma tabela ou div que contenha os dados
            page.wait_for_selector(wait_selector, timeout=30000)
        except:
            print("[FETCH] Aviso: O seletor de espera não foi encontrado no tempo limite.")
            pass
        html = page.content()
        browser.close()
        return html
    
def fetch_dynamic_scroll(url, wait_selector="table, div"):
    """
    Busca o HTML usando o Playwright e simula a rolagem da página 
    para carregar todos os resultados via lazy loading.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, timeout=60000)
        
        # Espera inicial para o primeiro bloco de conteúdo
        try:
            page.wait_for_selector(wait_selector, timeout=30000)
        except:
            pass

        print("[FETCH] Iniciando rolagem para carregar todos os itens...")
        
        last_height = -1
        scroll_attempts = 0
        MAX_SCROLL_ATTEMPTS = 50 # Limite de tentativas para evitar loops infinitos

        while scroll_attempts < MAX_SCROLL_ATTEMPTS:
            # 1. Rola até o final da página (executa JS no navegador)
            # O Playwright rola a página para baixo o máximo possível
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            
            # 2. Espera o novo conteúdo ser carregado (ajuste o tempo se necessário)
            # 2 segundos é um bom tempo para a maioria das requisições AJAX.
            page.wait_for_timeout(2000) 
            
            # 3. Verifica se o tamanho do conteúdo aumentou
            new_height = page.evaluate("document.body.scrollHeight")
            
            if new_height == last_height:
                # Se o tamanho não mudou, chegamos ao final da lista
                print(f"[FETCH] Fim da lista. Altura estabilizada em {new_height} pixels.")
                break
            
            # 4. Atualiza a altura e continua
            last_height = new_height
            scroll_attempts += 1
            print(f"[FETCH] Rolagem {scroll_attempts} realizada. Nova altura: {new_height}")

        if scroll_attempts == MAX_SCROLL_ATTEMPTS:
            print(f"[FETCH] Aviso: Limite de {MAX_SCROLL_ATTEMPTS} rolagens atingido. Pode haver mais dados.")

        html = page.content()
        browser.close()
        return html

def parse_fiesc_tabela(html, base_url="https://portaldecompras.fiesc.com.br"):
    """
    Parser corrigido para o Mural de Licitações da FIESC.
    Extrai o ID da licitação do atributo onclick (Coluna 7) para construir o URL absoluto.
    """
    soup = BeautifulSoup(html, "lxml")
    items = []
    
    # Seletor: Busca todas as linhas (tr) dentro do corpo da tabela específico
    rows = soup.select("tbody#trListaMuralProcesso tr")
    
    # Regex para extrair o primeiro ID numérico dentro da função de clique
    # Ex: trListaMuralResumoEdital_Click(6577, 59, 6577, true) -> captura '6577'
    ID_PATTERN = re.compile(r"trListaMuralResumoEdital_Click\((\d+),")
    
    # Template do URL de detalhes (formato mais provável, ajuste se necessário)
    URL_TEMPLATE = base_url + "/Detalhe.aspx?id={}" 
    
    for tr in rows:
        cols = tr.find_all("td")
        
        # Oito colunas esperadas (0 a 7)
        if len(cols) < 8:
            continue
            
        # 1. Extração dos Campos Básicos por Índice
        # Coluna 3: Objeto/Descrição (Título)
        title = cols[3].get_text(strip=True) 
        # Coluna 2: Unidade Compradora (Órgão)
        org = cols[2].get_text(strip=True)    
        # Coluna 6: Data/Hora Final (Publicado)
        published_date = cols[6].get_text(strip=True) 
        
        # 2. Extração da URL (Usando onclick da Coluna 7)
        url = None
        
        # O elemento clicável (com onclick) está na Coluna 7 (índice 7)
        area_clique_span = cols[7].select_one("span.areaClique")
        
        if area_clique_span:
            onclick_attr = area_clique_span.get('onclick', '')
            match = ID_PATTERN.search(onclick_attr)
            
            if match:
                process_id = match.group(1) # Captura o ID numérico
                url = URL_TEMPLATE.format(process_id) # Constrói o URL absoluto

        # Só adiciona o item se o Título E a URL foram encontrados
        if title and url: 
            items.append({
                "title": title, 
                "org": org, 
                "url": url, 
                "published": published_date
            })
        
    return items

# ==============================================================================
# 2. EXECUÇÃO DO TESTE
# ==============================================================================

if __name__ == "__main__":
    print("--- 🌐 Teste Real do Parser FIESC ---")
    
    try:
        # 1. Busca o HTML real e dinâmico
        html_real = fetch_dynamic_scroll(FIESC_URL)
        
        # 2. Processa o HTML com o parser
        resultados = parse_fiesc_tabela(html_real, BASE_URL)
        
        print(f"\n✅ Total de itens encontrados no site real: {len(resultados)}\n")
        
        # 3. Imprime os resultados
        if resultados:
            for i, item in enumerate(resultados, 1):
                print(f"--- Licitação {i} ---")
                print(f"Título:    {item['title']}")
                print(f"Órgão:     {item['org']}")
                print(f"Data:      {item['published']}")
                print(f"URL:       {item['url']}")
                print("-" * 25)
        else:
            print("⚠️ Nenhuma licitação foi encontrada. Os seletores HTML podem precisar de ajuste.")

    except Exception as e:
        print(f"\n❌ Ocorreu um erro durante o teste: {e}")
        print("Certifique-se de que o Playwright está instalado e os drivers estão configurados.")
        # Dica para configurar o Playwright:
        # python -m playwright install