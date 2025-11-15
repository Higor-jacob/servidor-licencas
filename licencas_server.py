from flask import Flask, render_template, request, jsonify, redirect, url_for, send_from_directory, session
import os, json, sqlite3, datetime, base64
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
from werkzeug.security import generate_password_hash, check_password_hash
from waitress import serve


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE_DIR, "licencas.db")
PRIVATE_KEY = os.path.join(BASE_DIR, "private.pem")
PUBLIC_KEY = os.path.join(BASE_DIR, "public.pem")
LIC_DIR = os.path.join(BASE_DIR, "licencas_emitidas")

SECRET_KEY = "uma_chave_secreta_muito_forte"
ADMIN_USER = "admin"
ADMIN_PASS_HASH = generate_password_hash("admin")

os.makedirs(LIC_DIR, exist_ok=True)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = SECRET_KEY



# ========== BANCO ==========
def conectar():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
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

init_db()

# ========== GERAÇÃO ==========
def carregar_chave_privada(senha=None):
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

# ========== EXECUÇÃO ==========
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port)