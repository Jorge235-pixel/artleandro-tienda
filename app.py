from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3, os, smtplib
from email.mime.text import MIMEText

app = Flask(__name__)
app.secret_key = "super-secret-key"

DB = "db.sqlite3"

# -------- DB --------
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS admin(
        id INTEGER PRIMARY KEY,
        username TEXT,
        password TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS productos(
        id INTEGER PRIMARY KEY,
        nombre TEXT,
        precio REAL,
        imagen TEXT,
        tallas TEXT,
        activo INTEGER
    )""")

    # Admin inicial
    cur.execute("SELECT * FROM admin")
    if not cur.fetchone():
        cur.execute("INSERT INTO admin (username,password) VALUES (?,?)",
                    ("admin","ArtLeandro2026"))
    conn.commit()
    conn.close()

init_db()

# -------- RUTAS --------
@app.route("/")
def home():
    conn = get_db()
    productos = conn.execute("SELECT * FROM productos WHERE activo=1").fetchall()
    conn.close()
    return render_template("index.html", productos=productos)

# -------- ADMIN --------
@app.route("/admin", methods=["GET","POST"])
def admin():
    if request.method == "POST":
        user = request.form["usuario"]
        pwd = request.form["password"]

        conn = get_db()
        admin = conn.execute(
            "SELECT * FROM admin WHERE username=? AND password=?",
            (user,pwd)
        ).fetchone()
        conn.close()

        if admin:
            session["admin"] = True
            return redirect("/panel")
        else:
            flash("Usuario o contraseña incorrectos")

    return render_template("admin_login.html")

@app.route("/panel")
def panel():
    if not session.get("admin"):
        return redirect("/admin")

    conn = get_db()
    productos = conn.execute("SELECT * FROM productos").fetchall()
    conn.close()

    return render_template("admin_panel.html", productos=productos)

@app.route("/crear", methods=["GET","POST"])
def crear():
    if not session.get("admin"):
        return redirect("/admin")

    if request.method == "POST":
        nombre = request.form["nombre"]
        precio = request.form["precio"]
        imagen = request.form["imagen"]
        tallas = request.form.getlist("tallas")
        activo = 1 if request.form.get("activo") else 0

        conn = get_db()
        conn.execute(
            "INSERT INTO productos (nombre,precio,imagen,tallas,activo) VALUES (?,?,?,?,?)",
            (nombre,precio,imagen,",".join(tallas),activo)
        )
        conn.commit()
        conn.close()

        return redirect("/panel")

    return render_template("producto_form.html")

# -------- WHATSAPP --------
def link_whatsapp(nombre):
    numero = "34638067232"
    return f"https://wa.me/{numero}?text=Hola%20quiero%20comprar%20{nombre}"

# -------- EMAIL --------
def enviar_correo(msg):
    try:
        correo = os.getenv("EMAIL_USER")
        password = os.getenv("EMAIL_PASS")
        destino = os.getenv("EMAIL_TO")

        m = MIMEText(msg)
        m["Subject"] = "Nueva compra"
        m["From"] = correo
        m["To"] = destino

        s = smtplib.SMTP_SSL("smtp.gmail.com",465)
        s.login(correo,password)
        s.send_message(m)
        s.quit()
    except:
        pass

# -------- MAIN --------
if __name__ == "__main__":
    app.run()
