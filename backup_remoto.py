import requests
import os

BACKUP_SERVER_URL = os.getenv("BACKUP_SERVER_URL")
BACKUP_TOKEN      = os.getenv("BACKUP_TOKEN")

def enviar_backup_remoto(caminho_db):
    """
    Envia o banco SQLite para o ServidorBackup.
    """

    if not BACKUP_SERVER_URL:
        print("❌ Variável BACKUP_SERVER_URL não configurada.")
        return False

    if not BACKUP_TOKEN:
        print("❌ Variável BACKUP_TOKEN não configurada.")
        return False

    if not os.path.exists(caminho_db):
        print(f"❌ Arquivo do banco não encontrado: {caminho_db}")
        return False

    try:
        with open(caminho_db, "rb") as f:
            response = requests.post(
                BACKUP_SERVER_URL,
                headers={"X-Backup-Token": BACKUP_TOKEN},
                files={"arquivo": f}
            )

        if response.status_code == 200:
            print("✅ Backup enviado ao ServidorBackup com sucesso!")
            print("📌 Resposta:", response.json())
            return True

        print(f"❌ Erro {response.status_code} ao enviar backup:")
        print(response.text)
        return False

    except Exception as e:
        print("❌ Exceção ao enviar backup remoto:", e)
        return False
