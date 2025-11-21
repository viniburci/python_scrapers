import requests
from bs4 import BeautifulSoup
import urllib.parse
from playwright.sync_api import sync_playwright
import time

# --- FUNÇÕES DE FETCH (Playwright) ---

def fetch_dynamic_scroll(url, wait_selector="tbody#tableProcessDataBody tr", load_more_selector=None):
    """
    Busca o HTML da página de busca do BNC usando o Playwright.
    Espera o carregamento da rede e o primeiro item da tabela.
    """
    print(f"[FETCH] Iniciando Playwright para {url}...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        try:
            page.goto(url, timeout=60000)
            
            # Espera até o primeiro item da tabela ser carregado
            print(f"[FETCH] Aguardando o primeiro item da tabela ({wait_selector})...")
            page.wait_for_selector(wait_selector, timeout=30000)
            
            # Espera a rede ficar inativa para garantir que o conteúdo foi totalmente carregado
            print("[FETCH] Aguardando estabilidade da rede (networkidle)...")
            page.wait_for_load_state("networkidle")
            
            # Carrega mais itens, se houver um seletor para isso
            if load_more_selector:
                while True:
                    try:
                        page.click(load_more_selector)
                        page.wait_for_selector(wait_selector, timeout=10000)
                        print("[FETCH] Mais itens carregados.")
                    except Exception:
                        break
            
            html = page.content()
            print("[FETCH] Conteúdo HTML capturado com sucesso.")
            browser.close()
            return html

        except Exception as e:
            print(f"[FETCH] ❌ ERRO CRÍTICO DURANTE O CARREGAMENTO OU ESPERA: {e}")
            browser.close()
            return ""


# --- PARSERS BNC ---

def parse_bnc_tabela(html, base_url="https://bnccompras.com"):
    """
    Parser para a tabela principal do BNC Compras.
    Extrai o URL de detalhe, Título (Nº Processo) e Órgão.
    """
    print("[PARSE TABELA] Analisando HTML da tabela...")
    soup = BeautifulSoup(html, "lxml")
    items = []
    
    # Seletor exato para o corpo da tabela de processos
    rows = soup.select("tbody#tableProcessDataBody tr")
    
    for tr in rows:
        cols = tr.find_all("td")
        
        if len(cols) < 8:  # A tabela parece ter no mínimo 8 colunas
            continue
            
        # Coluna 0: Botão de Detalhe (com o link)
        link_el = cols[0].select_one("a[title='Informações do Processo']")
        url = None
        if link_el and 'href' in link_el.attrs:
            caminho_relativo = link_el['href']
            # Cria o URL absoluto
            url = urllib.parse.urljoin(base_url, caminho_relativo)
        
        # Coluna 2: Número do Processo (Título)
        title = cols[2].get_text(strip=True)
        # Coluna 1: Órgão
        org = cols[1].get_text(strip=True)
        # Coluna 3: Modalidade
        modalidade = cols[3].get_text(strip=True) 
        # Coluna 7: Data de Abertura
        published_date = cols[6].get_text(strip=True)  # Ajuste para pegar a coluna correta
        
        if title and url:
            items.append({
                "site_name": "BNC",
                "title": title, 
                "org": org, 
                "url": url, 
                "published": published_date,
                "obj": modalidade 
            })
            
    print(f"[PARSE TABELA] {len(items)} itens básicos encontrados.")
    return items


def fetch_and_parse_bnc_detalhe(url_detalhe):
    """
    Faz uma requisição HTTP para a URL de detalhe e extrai os campos relevantes.
    """
    print(f"[FETCH DETALHE] Buscando detalhes em: {url_detalhe}")
    try:
        response = requests.get(url_detalhe, timeout=30)
        response.raise_for_status() 
        soup = BeautifulSoup(response.text, "lxml")
        
        # Campos essenciais para registrar
        campos_para_extrair = {
            "Organization": "promotor",  # Órgão responsável
            "Number": "n_chamamento",    # Nº Chamamento (Número do Processo)
            "Modality": "modalidade",    # Modalidade (tipo do processo)
            "Status": "fase",            # Fase atual do processo
            "TotalBaseValue": "valor_total",  # Valor Total do Processo
            "ProductOrService": "objeto",  # Objeto (Descrição do objeto do processo)
            "PublicationTime": "publicacao_data",  # Data de publicação
            "OrgPhone": "fone_promotor",  # Telefone do órgão
            "OrgEmail": "email_promotor",  # E-mail do órgão
        }
        
        detalhes = {}

        for html_id, nome_campo in campos_para_extrair.items():
            campo_tag = soup.find('input', {'id': html_id})
            
            if not campo_tag:
                campo_tag = soup.find('textarea', {'id': html_id})
            
            valor = None
            if campo_tag:
                if campo_tag.name == 'input':
                    valor = campo_tag.get('value', '').strip()
                elif campo_tag.name == 'textarea':
                    valor = campo_tag.get_text(strip=True)
            
            detalhes[nome_campo] = valor
            
        print("[FETCH DETALHE] Detalhes extraídos com sucesso.")
        return detalhes

    except requests.exceptions.RequestException as e:
        print(f"[ERRO BNC DETALHE] Falha ao acessar {url_detalhe}: {e}")
        return None
    except Exception as e:
        print(f"[ERRO BNC PARSE] Falha ao analisar detalhes: {e}")
        return None


# --- BLOCO DE TESTE ---

def testar_bnc_scraper():
    """Simula o processo completo de scraping para o BNC Compras."""
    
    BNC_URL = "https://bnccompras.com/Process/ProcessSearchPublic?param1=0"
    
    # 1. Obter o HTML da tabela principal (requer Playwright)
    html_tabela = fetch_dynamic_scroll(BNC_URL)
    
    if not html_tabela:
        print("[TESTE] ❌ Falha ao obter HTML da tabela. Encerrando.")
        return
    
    # 2. Analisar o HTML da tabela e extrair os links
    itens_basicos = parse_bnc_tabela(html_tabela)
    
    if not itens_basicos:
        print("[TESTE] Nenhuma licitação encontrada na tabela. Encerrando.")
        return

    # 3. Processar o primeiro item encontrado para buscar detalhes
    primeiro_item = itens_basicos[0]
    
    print("\n" + "="*50)
    print(f"PROCESSANDO O PRIMEIRO ITEM:")
    print(f"URL BÁSICA: {primeiro_item['url']}")
    print("="*50)

    # 4. Buscar os detalhes completos
    detalhes = fetch_and_parse_bnc_detalhe(primeiro_item['url'])
    
    if detalhes:
        # 5. Mesclar os dados relevantes
        item_completo = {**primeiro_item, **detalhes}
        
        print("\n" + "🌟"*10 + " DADOS FINAIS COMPLETOS " + "🌟"*10)
        for key, value in item_completo.items():
            if key in ['valor_total', 'publicacao_data', 'objeto', 'fase', 'n_chamamento', 'promotor', 'url']:
                if key == 'objeto' and value:
                    value = value[:150] + "..." if len(value) > 150 else value
                print(f"- {key.upper()}: {value}")
        print("="*55)
    else:
        print("[TESTE] Falha ao obter detalhes do primeiro item.")


if __name__ == "__main__":
    # Certifique-se de ter 'playwright' e 'requests' instalados
    # pip install playwright beautifulsoup4 requests lxml
    # playwright install chromium
    print("Iniciando teste de scraping do BNC Compras...")
    testar_bnc_scraper()
