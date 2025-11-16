import os
import datetime
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build


def fazer_backup(DB_PATH: str):
    """Envia uma cópia do banco para o Google Drive."""
    
    print("📦 Iniciando backup automático do banco...")

    # Credenciais via variável de ambiente
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        print("❌ GOOGLE_CREDENTIALS_JSON não configurado.")
        return False

    creds_dict = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/drive.file"]
    )

    service = build("drive", "v3", credentials=creds)

    # Nome do arquivo de backup
    agora = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%SZ")
    backup_name = f"backup_licencas_{agora}.db"

    file_metadata = {
        "name": backup_name,
        "mimeType": "application/octet-stream"
    }

    # Upload do arquivo
    media_body = open(DB_PATH, "rb")

    upload = service.files().create(
        body=file_metadata,
        media_body=media_body,
        fields="id"
    ).execute()

    print(f"✅ Backup enviado com sucesso! ID: {upload.get('id')}")
    return True