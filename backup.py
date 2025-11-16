import os
import datetime
import dropbox

def backup_dropbox(DB_PATH: str, keep_last: int = 10):
    """
    Envia o banco SQLite para o Dropbox dentro da pasta /backups/.
    Mantém somente os últimos 'keep_last' backups.
    """
    TOKEN = os.getenv("DROPBOX_ACCESS_TOKEN")
    if not TOKEN:
        print("❌ DROPBOX_ACCESS_TOKEN não configurado.")
        return False

    try:
        dbx = dropbox.Dropbox(TOKEN)

        # Nome formatado
        agora = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%SZ")
        dropbox_path = f"/backups/backup_licencas_{agora}.db"

        print(f"📦 Enviando backup para o Dropbox: {dropbox_path}")

        # Upload do arquivo
        with open(DB_PATH, "rb") as f:
            dbx.files_upload(
                f.read(),
                dropbox_path,
                mode=dropbox.files.WriteMode("overwrite")
            )

        print("✅ Backup enviado com sucesso!")

        # ======= LIMPEZA: manter apenas os últimos X backups =======
        try:
            lista = dbx.files_list_folder("/backups").entries

            # Ordenar pelo nome (timestamp está embutido)
            lista_sorted = sorted(lista, key=lambda x: x.name, reverse=True)

            # Itens além do limite permitido
            deletar = lista_sorted[keep_last:]

            for arq in deletar:
                dbx.files_delete_v2(f"/backups/{arq.name}")
                print(f"🧹 Backup antigo removido: {arq.name}")

        except Exception as e:
            print(f"⚠️ Não foi possível limpar backups antigos: {e}")

        return True

    except Exception as e:
        print(f"❌ Erro no backup via Dropbox: {e}")
        return False