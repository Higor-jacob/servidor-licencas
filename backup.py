import os
import datetime
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


def fazer_backup(DB_PATH: str):
    print("📦 Iniciando backup automático do banco...")

    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        print("❌ GOOGLE_CREDENTIALS_JSON não configurado.")
        return False

    folder_id = os.getenv("BACKUP_FOLDER_ID")
    if not folder_id:
        print("❌ BACKUP_FOLDER_ID não configurado.")
        return False

    creds_dict = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/drive.file"]
    )

    service = build("drive", "v3", credentials=creds)

    agora = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%SZ")
    backup_name = f"backup_licencas_{agora}.db"

    # 📌 ENVIA PARA UMA PASTA ESPECÍFICA DO DRIVE
    file_metadata = {
        "name": backup_name,
        "parents": [folder_id],   # ← ESSENCIAL!
        "mimeType": "application/octet-stream"
    }

    media = MediaFileUpload(DB_PATH, mimetype="application/octet-stream")

    upload = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id"
    ).execute()

    print(f"✅ Backup enviado com sucesso! ID: {upload.get('id')}")
    return True
