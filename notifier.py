import logging
import re
import time

import requests

from config import TELEGRAM_CHAT_ID, TELEGRAM_TOKEN

logger = logging.getLogger(__name__)

_MAX_RETRIES = 5


def _escape_md(text: str) -> str:
    """Escapa todos os caracteres especiais do MarkdownV2 do Telegram."""
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', str(text))


def send(item: dict, source: str) -> bool:
    obj = item.get("obj")
    obj_line = ""
    if obj:
        obj_text = obj[:250].strip()
        if len(obj) > 250:
            obj_text += "..."
        obj_line = f"\nObjeto: {_escape_md(obj_text)}"

    itens = item.get("itens", [])
    total_itens = item.get("total_itens", len(itens))
    itens_preview = ""
    if itens:
        linhas = [
            f"  \u2022 {_escape_md(i['descricao'][:80])} ({i['quantidade']} {i['unidade']})"
            for i in itens[:5]
        ]
        restante = total_itens - len(itens[:5])
        if restante > 0:
            linhas.append(f"  _... e mais {restante} itens_")
        itens_preview = "\n\n*Itens:*\n" + "\n".join(linhas)

    text = (
        f"*{_escape_md(item['title'])}*\n"
        f"Fonte: {_escape_md(source)}\n"
        f"Orgao: {_escape_md(item.get('org', '-'))}"
        + obj_line
        + f"\nPublicado: {_escape_md(item.get('published', '-'))}"
        f"\nLink: {_escape_md(item.get('url', '-'))}"
        + itens_preview
    )

    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": False,
    }

    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.post(api_url, json=payload, timeout=15)
            if resp.ok:
                return True
            if resp.status_code == 429:
                retry_after = resp.json().get("parameters", {}).get("retry_after", 19)
                logger.warning("Rate limit Telegram. Aguardando %ds...", retry_after)
                time.sleep(retry_after)
                continue
            logger.error("Falha ao enviar mensagem Telegram: %s", resp.text)
            return False
        except requests.RequestException as e:
            logger.error("Erro na requisicao Telegram: %s", e)
            return False

    logger.error("Falha apos %d tentativas ao enviar para Telegram", _MAX_RETRIES)
    return False
