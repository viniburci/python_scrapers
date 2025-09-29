import requests

# CONFIGURAÇÃO
TELEGRAM_TOKEN = "8071395009:AAH-7P6Cys3hncbQdaJYB2paoK7sVeh884s"  # Substitua pelo token real
TELEGRAM_CHAT_ID = "-1003163879445"    # Seu chat_id do grupo (negativo)

# Mensagem de teste
mensagem = "✅ Teste de envio de mensagens do bot."

# Envio
resp = requests.post(
    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
    json={"chat_id": TELEGRAM_CHAT_ID, "text": mensagem, "parse_mode": "Markdown"}
)

# Resultado
print(resp.status_code)
print(resp.text)
