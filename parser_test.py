import requests
import os
import time
from dotenv import load_dotenv

load_dotenv()
def fetch_dynamic(url):
	response = requests.get(url)
	response.raise_for_status()
	return response.text

#html = fetch_dynamic("https://portaldecompras.fiesc.com.br/Portal/Mural.aspx")
#print(html[:100])  # mostra os primeiros 1000 caracteres

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN") 
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def send_telegram_message(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    

    payload = {
        "chat_id": "-5020354385",
        "text": msg,
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

print(f"Telegram Token: {TELEGRAM_TOKEN}")
print(f"Telegram Chat ID: {TELEGRAM_CHAT_ID}")


if __name__ == "__main__":
	resp = send_telegram_message("Teste de mensagem via Telegram API.")
	print(resp)
 
	print(len("123456789:ABCDEFGHIJKLMN_OPQRSTUVW_XYZ123456789"))
	print(len(TELEGRAM_TOKEN))
 