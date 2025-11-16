from flask import Flask, render_template, request, jsonify, redirect, url_for, send_from_directory, session
import os, json, sqlite3, datetime, base64
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
from werkzeug.security import generate_password_hash, check_password_hash
from waitress import serve

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 🔹 Diretório persistente no Render
PERSIST_DIR = "/opt/render/persistent/licencas"
os.makedirs(PERSIST_DIR, exist_ok=True)

# 🔹 Banco persistente
DB = os.path.join(PERSIST_DIR, "licencas.db")

# 🔹 Licenças geradas (também persistente)
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



# ========== BANCO ==========
def conectar():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    primeiro_banco = not os.path.exists(DB)

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

    if primeiro_banco:
        print("📌 Banco criado pela primeira vez:", DB)
    else:
        print("📌 Banco já existia, mantendo dados:", DB)

init_db()

# ========== GERAÇÃO ==========
def carregar_chave_privada(senha=None):
    # 1) Tenta carregar da variável de ambiente
    if PRIVATE_KEY_PEM:
        return serialization.load_pem_private_key(
            PRIVATE_KEY_PEM.encode(),
            password=senha.encode() if senha else None,
            backend=default_backend()
        )

    # 2) Fallback: tenta carregar do arquivo físico
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
        json.dump(licenca, f, ensure_ascii=False, indent=2)

    conn = conectar()
    cur = conn.cursor()
    cur.execute("INSERT INTO licencas (cliente, hwid, issued_at, expires_at, arquivo) VALUES (?,?,?,?,?)",
                (cliente, hwid, payload["issued_at"], payload["expires_at"], nome_arquivo))
    conn.commit()
    conn.close()
    return nome_arquivo


# ========== LOGIN ==========
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        user = request.form.get("user")
        pwd = request.form.get("pwd")
        if user == ADMIN_USER and check_password_hash(ADMIN_PASS_HASH, pwd):
            session.permanent = False
            session["admin"] = True
            return redirect(url_for("painel"))
        return render_template("login.html", erro="Usuário ou senha inválidos")
    return render_template("login.html")

def exige_login(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ========== ROTAS PRINCIPAIS ==========
@app.route("/")
def home():
    return redirect("/admin")

@app.route("/admin")
@exige_login
def painel():
    conn = conectar()
    cur = conn.cursor()

    # Estatísticas
    cur.execute("SELECT COUNT(*) FROM licencas")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM licencas WHERE revogado=0 AND expires_at>?", (datetime.datetime.utcnow().isoformat()+"Z",))
    ativas = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM licencas WHERE revogado=1")
    revogadas = cur.fetchone()[0]

    # Lista
    cur.execute("SELECT * FROM licencas ORDER BY id DESC")
    licencas = cur.fetchall()
    conn.close()

    return render_template("painel.html",
                           total=total,
                           ativas=ativas,
                           revogadas=revogadas,
                           licencas=licencas)

@app.route("/admin/gerar", methods=["POST"])
@exige_login
def gerar_via_painel():
    cliente = request.form["cliente"]
    hwid = request.form["hwid"]
    dias = int(request.form["dias"])
    senha = request.form.get("senha")
    try:
        gerar_licenca(cliente, hwid, dias, senha)
        return redirect(url_for("painel"))
    except Exception as e:
        return f"<h3>Erro: {e}</h3>"

@app.route("/download/<path:nome>")
@exige_login
def baixar_licenca(nome):
    return send_from_directory(LIC_DIR, nome, as_attachment=True)

@app.route("/admin/revogar/<int:id>")
@exige_login
def revogar(id):
    conn = conectar()
    cur = conn.cursor()
    cur.execute("UPDATE licencas SET revogado=1, revogado_em=? WHERE id=?",
                (datetime.datetime.utcnow().isoformat()+"Z", id))
    conn.commit()
    conn.close()
    return redirect("/admin")

@app.route("/admin/reativar/<int:id>")
@exige_login
def reativar(id):
    conn = conectar()
    cur = conn.cursor()
    cur.execute("UPDATE licencas SET revogado=0, revogado_em=NULL WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return redirect("/admin")


# ========== API ==========
@app.route("/api/licencas", methods=["GET"])
def api_listar():
    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT * FROM licencas")
    dados = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(dados)


@app.route("/api/verificar", methods=["POST"])
def verificar_licenca():
    """Valida uma licença enviada pelo cliente e retorna status"""
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
        expira_em = datetime.datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00"))

        conn = conectar()
        cur = conn.cursor()
        cur.execute("SELECT revogado FROM licencas WHERE hwid=? ORDER BY id DESC LIMIT 1", (hwid,))
        row = cur.fetchone()
        conn.close()

        if row and row["revogado"] == 1:
            return jsonify({"status": "revogada"})
        if datetime.datetime.now(datetime.timezone.utc) > expira_em:
            return jsonify({"status": "expirada"})

        return jsonify({"status": "valida"})
    except Exception as e:
        return jsonify({"status": "invalida", "erro": str(e)})


# ================================
# 🔧 PAINEL DE DEBUG (com login)
# ================================
@app.route("/debug")
@exige_login
def debug_home():
    return """
    <h1>Debug Tools</h1>
    <ul>
        <li><a href='/debug/dbpath'>📌 Caminho do banco</a></li>
        <li><a href='/debug/show'>📋 Mostrar registros</a></li>
        <li><a href='/debug/download-db'>⬇️ Baixar banco</a></li>
        <li><a href='/debug/upload-db'>⬆️ Subir banco</a></li>
        <li><a href='/debug/migrar'>🔄 Migrar banco antigo</a></li>
    </ul>
    """

@app.route("/debug/dbpath")
@exige_login
def debug_dbpath():
    return f"<h3>Banco atual:</h3><p>{DB}</p>"

@app.route("/debug/show")
@exige_login
def debug_show():
    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT * FROM licencas")
    dados = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(dados)

# BAIXAR DB
@app.route("/debug/download-db")
@exige_login
def debug_download():
    return send_from_directory(
        os.path.dirname(DB),
        os.path.basename(DB),
        as_attachment=True
    )

# UPLOAD DB
@app.route("/debug/upload-db", methods=["GET", "POST"])
@exige_login
def debug_upload():
    if request.method == "POST":
        file = request.files.get("arquivo")
        if file:
            # sobrescreve com segurança
            temp = DB + ".tmp"
            file.save(temp)

            os.replace(temp, DB)  # troca atômica
            return "✔ Banco atualizado com sucesso!"
        return "❌ Nenhum arquivo enviado."

    return """
    <h3>Enviar novo banco (.db)</h3>
    <form method='post' enctype='multipart/form-data'>
        <input type='file' name='arquivo'>
        <button type='submit'>Enviar</button>
    </form>
    """

# MIGRAR DB ANTIGO
@app.route("/debug/migrar")
@exige_login
def debug_migrar():
    antigo = "/opt/render/project/src/licencas.db"
    novo = DB

    if os.path.exists(antigo):
        import shutil
        shutil.copy(antigo, novo)
        return "✔ Banco migrado para o persistente!"
    return "❌ Banco antigo não encontrado."


# ============================================
# 📊 TELA DE VISUALIZAÇÃO DO BANCO (mini-phpMyAdmin)
# ============================================

@app.route("/admin/db")
@exige_login
def admin_db():
    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT * FROM licencas ORDER BY id DESC")
    dados = cur.fetchall()
    conn.close()

    # Converte para lista de dicionários
    licencas = [dict(row) for row in dados]

    return render_template("db_view.html", licencas=licencas)

# ========== EXECUÇÃO ==========
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port)