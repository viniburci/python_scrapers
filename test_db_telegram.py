"""
Teste isolado: banco de dados (conexao, deduplicacao) e Telegram.
Nao executa nenhum scraper.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from db import init_db, is_new_and_save, _connect
from notifier import send

ITEM_TESTE = {
    "title": "[TESTE] Licitacao de Verificacao do Sistema",
    "org": "Orgao de Teste",
    "url": "https://exemplo.com/licitacao/teste-12345",
    "published": "25/03/2026",
    "obj": "Verificacao de funcionamento do sistema de alertas.",
}


def test_banco():
    print("\n=== TESTE BANCO DE DADOS ===\n")

    print("[1/4] Conectando e inicializando tabela...")
    try:
        init_db()
        print("      OK - tabela 'notices' pronta\n")
    except Exception as e:
        print(f"      ERRO: {e}")
        return False

    print("[2/4] Inserindo item de teste...")
    try:
        novo = is_new_and_save(ITEM_TESTE)
        if novo:
            print("      OK - item inserido (novo=True)\n")
        else:
            print("      AVISO - item ja existia no banco (novo=False)")
            print("      Isso pode significar que o teste foi rodado antes.")
            print("      Se quiser testar do zero, apague o item manualmente.\n")
    except Exception as e:
        print(f"      ERRO: {e}")
        return False

    print("[3/4] Tentando inserir o mesmo item novamente (teste de deduplicacao)...")
    try:
        duplicado = is_new_and_save(ITEM_TESTE)
        if not duplicado:
            print("      OK - deduplicacao funcionando (novo=False para item repetido)\n")
        else:
            print("      FALHA - item duplicado foi inserido!\n")
            return False
    except Exception as e:
        print(f"      ERRO: {e}")
        return False

    print("[4/4] Verificando item no banco diretamente...")
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT id, title, org, found_at FROM notices ORDER BY found_at DESC LIMIT 3")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        print(f"      Ultimos {len(rows)} registros:")
        for row in rows:
            print(f"        id={row[0][:8]}... | {row[2]} | {row[1][:50]} | {row[3]}")
        print()
    except Exception as e:
        print(f"      ERRO: {e}")
        return False

    return True


def test_telegram():
    print("=== TESTE TELEGRAM ===\n")

    print("[1/1] Enviando mensagem de teste...")
    try:
        ok = send(ITEM_TESTE, "TESTE")
        if ok:
            print("      OK - mensagem enviada! Verifique o grupo do Telegram.\n")
        else:
            print("      FALHA - mensagem nao foi enviada. Verifique TOKEN e CHAT_ID.\n")
        return ok
    except Exception as e:
        print(f"      ERRO: {e}")
        return False


if __name__ == "__main__":
    db_ok = test_banco()
    tg_ok = test_telegram()

    print("=== RESULTADO ===")
    print(f"  Banco:    {'OK' if db_ok else 'FALHOU'}")
    print(f"  Telegram: {'OK' if tg_ok else 'FALHOU'}")

    if db_ok and tg_ok:
        print("\nTudo funcionando. Pode rodar: python main.py")
    else:
        print("\nCorrija os erros antes de rodar o main.py")
