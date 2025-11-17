import requests
import os

# URL do servidor de backup
BACKUP_SERVER_URL = os.getenv("BACKUP_SERVER_URL")
BACKUP_TOKEN      = os.getenv("BACKUP_TOKEN")           

def enviar_backup_remoto(caminho_db):
    """
    Envia o banco sqlite local para o ServidorBackup centralizado.
    Substitui totalmente o antigo backup_dropbox().
    """
    if not BACKUP_SERVER_URL:
        print("❌ BACKUP_SERVER_URL não configurado.")
        return False

    if not BACKUP_TOKEN:
        print("❌ BACKUP_TOKEN não configurado.")
        return False

    if not os.path.exists(caminho_db):
        print(f"❌ Banco não encontrado: {caminho_db}")
        return False

    try:
        with open(caminho_db, "rb") as f:
            resp = requests.post(
                BACKUP_SERVER_URL,
                headers={"X-Backup-Token": BACKUP_TOKEN},
                files={"arquivo": f}
            )

        if resp.status_code == 200:
            print("✅ Backup enviado para o ServidorBackup com sucesso!")
            print("📎 Resposta:", resp.json())
            return True
        else:
            print(f"❌ Erro ao enviar backup remoto: {resp.status_code}")
            print(resp.text)
            return False

    except Exception as e:
        print("❌ Exceção ao enviar backup remoto:", e)
        return False