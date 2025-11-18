##############################################################
#  SISTEMA DE LICENÇAS — VERSÃO CORRIGIDA E OTIMIZADA
#  SUPORTE: LICENÇAS, TRIAL PERMANENTE, PAINEL WEB
#  COMPATÍVEL COM RENDER.COM (persistência garantida)
##############################################################

from flask import (
    Flask, render_template, request, jsonify,
    redirect, url_for, send_from_directory, session
)
import os, json, sqlite3, datetime, base64, shutil
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
from werkzeug.security import generate_password_hash, check_password_hash
from backup_remoto import enviar_backup_remoto

##############################################################
# CONFIGURAÇÃO DE CAMINHOS — PERSISTÊNCIA 100%
##############################################################

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 🔹 Diretório persistente no Render
PERSIST_DIR = "/opt/render/persistent/licencas"
os.makedirs(PERSIST_DIR, exist_ok=True)

# 🔹 Caminho do banco persistente
DB = os.path.join(PERSIST_DIR, "licencas.db")

# 🔹 Banco antigo (do deploy)
DB_ANTIGO = "/opt/render/project/src/licencas.db"

# 🔹 Diretório de licenças emitidas
LIC_DIR = os.path.join(PERSIST_DIR, "licencas_emitidas")
os.makedirs(LIC_DIR, exist_ok=True)

# 🔹 Chaves
PRIVATE_KEY = os.path.join(BASE_DIR, "private.pem")
PUBLIC_KEY = os.path.join(BASE_DIR, "public.pem")

PRIVATE_KEY_PEM = os.getenv("PRIVATE_KEY_PEM")
PUBLIC_KEY_PEM = os.getenv("PUBLIC_KEY_PEM")

SECRET_KEY = os.environ.get("SECRET_KEY", os.urandom(32))
ADMIN_USER = "admin"
ADMIN_PASS_HASH = generate_password_hash("admin")

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = SECRET_KEY
app.permanent_session_lifetime = datetime.timedelta(days=1)


##############################################################
# 🔥 FUNÇÕES DO BANCO
##############################################################

def conectar():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def garantir_migracao():
    """
    Se o banco persistente NÃO existe mas o banco antigo existe,
    migramos automaticamente.
    """
    if not os.path.exists(DB) and os.path.exists(DB_ANTIGO):
        print("🔄 Migrando banco antigo para o persistente...")
        shutil.copy(DB_ANTIGO, DB)
        print("✔ Migração concluída:", DB)


def init_db():
    """Cria tabela principal de licenças, se não existir."""
    conn = conectar()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS licencas (
            id INTEGER PRIMARY KEY,
            cliente TEXT,
            hwid TEXT,
            issued_at TEXT,
            expires_at TEXT,
            arquivo TEXT,
            revogado INTEGER DEFAULT 0,
            revogado_em TEXT
        )
    """)

    conn.commit()
    conn.close()


def init_trial_db():
    """Cria tabela de trials permanentes, se não existir."""
    conn = conectar()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS trials (
            id INTEGER PRIMARY KEY,
            hwid TEXT UNIQUE,
            trial_inicio TEXT,
            trial_fim TEXT,
            consumido INTEGER DEFAULT 0
        )
    """)

    conn.commit()
    conn.close()


##############################################################
# 🔥 ORDEM CORRETA DE INICIALIZAÇÃO DO BANCO
##############################################################

garantir_migracao()   # 1) Migrar se necessário
init_db()             # 2) Criar tabela principal
init_trial_db()       # 3) Criar tabela trial

print("📌 BANCO EM USO:", DB)

##############################################################
# BACKUP PARA DROPBOX (opcional, controlado por env vars)
##############################################################

try:
    enviar_backup_remoto(DB)
except Exception as e:
    print("⚠️ Falha ao iniciar backup remoto:", e)


##############################################################
#  CHAVES E ASSINATURA
##############################################################

def carregar_chave_privada(senha=None):
    if PRIVATE_KEY_PEM:
        return serialization.load_pem_private_key(
            PRIVATE_KEY_PEM.encode(),
            password=senha.encode() if senha else None,
            backend=default_backend()
        )
    with open(PRIVATE_KEY, "rb") as f:
        return serialization.load_pem_private_key(
            f.read(),
            password=senha.encode() if senha else None,
            backend=default_backend()
        )


def assinar_payload(priv, dados_bytes):
    return priv.sign(
        dados_bytes,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256()
    )


def gerar_licenca(cliente, hwid, dias, senha=None):
    agora = datetime.datetime.utcnow()
    payload = {
        "nome": cliente,
        "hwid": hwid,
        "issued_at": agora.isoformat() + "Z",
        "expires_at": (agora + datetime.timedelta(days=dias)).isoformat() + "Z",
        "features": ["full", "whatsapp_integration"],
    }

    dados_bytes = json.dumps(payload, separators=(",", ":")).encode()
    chave = carregar_chave_privada(senha)
    assinatura = assinar_payload(chave, dados_bytes)

    licenca = {
        "payload": base64.b64encode(dados_bytes).decode(),
        "assinatura": base64.b64encode(assinatura).decode(),
    }

    nome_arquivo = f"licenca_{cliente.replace(' ', '_')}.licenca"
    caminho = os.path.join(LIC_DIR, nome_arquivo)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(licenca, f, indent=2)

    conn = conectar()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO licencas (cliente, hwid, issued_at, expires_at, arquivo)
        VALUES (?, ?, ?, ?, ?)
    """, (cliente, hwid, payload["issued_at"], payload["expires_at"], nome_arquivo))
    conn.commit()
    conn.close()

    return nome_arquivo


##############################################################
# ROTAS BÁSICAS / LOGIN
##############################################################

@app.route("/")
def home():
    """
    Evita 404 em GET /.
    Se não estiver logado, manda pro /login; se já estiver, vai pro /admin.
    """
    if session.get("admin"):
        return redirect("/admin")
    return redirect("/login")


@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        user = request.form.get("user")
        pwd = request.form.get("pwd")
        if user == ADMIN_USER and check_password_hash(ADMIN_PASS_HASH, pwd):
            session["admin"] = True
            return redirect(url_for("painel"))
        return render_template("login.html", erro="Usuário ou senha inválidos")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


def exige_login(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect("/login")
        return f(*args, **kwargs)
    return wrapper


##############################################################
# PAINEL ADMINISTRATIVO
##############################################################

@app.route("/admin")
@exige_login
def painel():
    conn = conectar()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM licencas")
    total = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM licencas WHERE revogado=0 AND expires_at>?",
                (datetime.datetime.utcnow().isoformat()+"Z",))
    ativas = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM licencas WHERE revogado=1")
    revogadas = cur.fetchone()[0]

    cur.execute("SELECT * FROM licencas ORDER BY id DESC")
    licencas = cur.fetchall()

    # KPIs de trials (opcional, só pra mostrar no painel)
    cur.execute("SELECT COUNT(*) FROM trials")
    total_trials = cur.fetchone()[0]

    conn.close()

    return render_template(
        "painel.html",
        total=total,
        ativas=ativas,
        revogadas=revogadas,
        licencas=licencas,
        total_trials=total_trials
    )


@app.route("/admin/gerar", methods=["POST"])
@exige_login
def gerar_via_painel():
    cliente = request.form["cliente"]
    hwid = request.form["hwid"]
    dias = int(request.form["dias"])
    senha = request.form.get("senha")

    try:
        gerar_licenca(cliente, hwid, dias, senha)
        return redirect("/admin")
    except Exception as e:
        return f"<h3>Erro: {e}</h3>"


##############################################################
# DOWNLOAD
##############################################################

@app.route("/download/<path:nome>")
@exige_login
def baixar_licenca(nome):
    return send_from_directory(LIC_DIR, nome, as_attachment=True)


##############################################################
# REVOGAR / REATIVAR
##############################################################

@app.route("/admin/revogar/<int:id>")
@exige_login
def revogar(id):
    conn = conectar()
    cur = conn.cursor()
    cur.execute(
        "UPDATE licencas SET revogado=1, revogado_em=? WHERE id=?",
        (datetime.datetime.utcnow().isoformat()+"Z", id)
    )
    conn.commit()
    conn.close()
    return redirect("/admin")


@app.route("/admin/reativar/<int:id>")
@exige_login
def reativar(id):
    conn = conectar()
    cur = conn.cursor()
    cur.execute(
        "UPDATE licencas SET revogado=0, revogado_em=NULL WHERE id=?",
        (id,)
    )
    conn.commit()
    conn.close()
    return redirect("/admin")


##############################################################
# VISUALIZAÇÃO DO BANCO (LICENÇAS)
##############################################################

@app.route("/admin/db")
@exige_login
def admin_db():
    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT * FROM licencas ORDER BY id DESC")
    dados = cur.fetchall()
    conn.close()

    licencas = [dict(row) for row in dados]
    return render_template("db_view.html", licencas=licencas)


##############################################################
# VISUALIZAÇÃO DO BANCO (TRIALS)
##############################################################

@app.route("/admin/trials")
@exige_login
def admin_trials():
    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT * FROM trials ORDER BY id DESC")
    dados = cur.fetchall()
    conn.close()

    trials = [dict(row) for row in dados]
    return render_template("trials_view.html", trials=trials)


##############################################################
# API — LISTAR LICENÇAS
##############################################################

@app.route("/api/licencas")
def api_listar():
    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT * FROM licencas")
    dados = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(dados)


##############################################################
# API — VERIFICAR LICENÇA NORMAL
##############################################################

@app.route("/api/verificar", methods=["POST"])
def verificar_licenca_api():
    data = request.json
    licenca = data.get("licenca")

    if not licenca:
        return jsonify({"status": "invalida", "erro": "Licença ausente"}), 400

    try:
        payload_bytes = base64.b64decode(licenca["payload"])
        assinatura = base64.b64decode(licenca["assinatura"])

        if PUBLIC_KEY_PEM:
            public_key = serialization.load_pem_public_key(PUBLIC_KEY_PEM.encode())
        else:
            with open(PUBLIC_KEY, "rb") as f:
                public_key = serialization.load_pem_public_key(f.read())

        public_key.verify(
            assinatura,
            payload_bytes,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )

        payload = json.loads(payload_bytes.decode())
        hwid = payload.get("hwid")
        expira_em = datetime.datetime.fromisoformat(
            payload["expires_at"].replace("Z", "+00:00")
        )

        conn = conectar()
        cur = conn.cursor()
        cur.execute(
            "SELECT revogado FROM licencas WHERE hwid=? ORDER BY id DESC LIMIT 1",
            (hwid,)
        )
        row = cur.fetchone()
        conn.close()

        if row and row["revogado"] == 1:
            return jsonify({"status": "revogada"})
        if datetime.datetime.now(datetime.timezone.utc) > expira_em:
            return jsonify({"status": "expirada"})

        return jsonify({"status": "valida"})

    except Exception as e:
        return jsonify({"status": "invalida", "erro": str(e)})


##############################################################
# API — TRIAL PERMANENTE
##############################################################

@app.route("/api/verificar_trial", methods=["POST"])
def api_verificar_trial():
    dados = request.json
    hwid = dados.get("hwid")

    if not hwid:
        return jsonify({"erro": "hwid ausente"}), 400

    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT * FROM trials WHERE hwid=?", (hwid,))
    row = cur.fetchone()
    conn.close()

    if row:
        return jsonify({
            "consumido": bool(row["consumido"]),
            "trial_inicio": row["trial_inicio"],
            "trial_fim": row["trial_fim"]
        })

    return jsonify({
        "consumido": False,
        "trial_inicio": None,
        "trial_fim": None
    })


@app.route("/api/registrar_trial", methods=["POST"])
def api_registrar_trial():
    dados = request.json
    hwid = dados.get("hwid")
    inicio = dados.get("trial_inicio")
    fim = dados.get("trial_fim")

    if not hwid or not inicio or not fim:
        return jsonify({"erro": "dados incompletos"}), 400

    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT * FROM trials WHERE hwid=?", (hwid,))
    existente = cur.fetchone()

    if existente:
        return jsonify({"status": "ja_existe"})

    cur.execute("""
        INSERT INTO trials (hwid, trial_inicio, trial_fim, consumido)
        VALUES (?, ?, ?, 1)
    """, (hwid, inicio, fim))

    conn.commit()
    conn.close()

    return jsonify({"status": "registrado"})


@app.route("/api/trials", methods=["GET"])
def api_listar_trials():
    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT * FROM trials ORDER BY id DESC")
    dados = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(dados)


##############################################################
# EXECUÇÃO
##############################################################

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    print("🚀 Servidor iniciado na porta", port)
    app.run(host="0.0.0.0", port=port)