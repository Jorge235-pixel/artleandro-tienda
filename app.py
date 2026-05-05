# -*- coding: utf-8 -*-
import os, sqlite3, smtplib, csv, io, json, urllib.request
from datetime import datetime
from functools import wraps
from email.mime.text import MIMEText
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, url_for, session, flash, g, Response

APP_DIR=os.path.abspath(os.path.dirname(__file__))
DB=os.path.join(APP_DIR,'instance','tienda.db')
UPLOAD=os.path.join(APP_DIR,'static','uploads','productos')
ALLOWED={'png','jpg','jpeg','webp'}
app=Flask(__name__)
app.secret_key=os.environ.get('SECRET_KEY','CAMBIAR-CLAVE-SECRETA-ARTLEANDRO-2026')
app.config['UPLOAD_FOLDER']=UPLOAD

ADMIN_USER=os.environ.get('ADMIN_USER','admin')
ADMIN_PASS=os.environ.get('ADMIN_PASS','ArtLeandro2026')

def get_db():
    if 'db' not in g:
        g.db=sqlite3.connect(DB)
        g.db.row_factory=sqlite3.Row
    return g.db
@app.teardown_appcontext
def close_db(e=None):
    db=g.pop('db',None)
    if db: db.close()

def init_db():
    os.makedirs(os.path.dirname(DB),exist_ok=True); os.makedirs(UPLOAD,exist_ok=True)
    db=sqlite3.connect(DB); c=db.cursor()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS admin(id INTEGER PRIMARY KEY, usuario TEXT UNIQUE, password TEXT);
    CREATE TABLE IF NOT EXISTS colecciones(id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, descripcion TEXT DEFAULT '', activa INTEGER DEFAULT 1, creada TEXT);
    CREATE TABLE IF NOT EXISTS productos(id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, descripcion TEXT DEFAULT '', precio INTEGER NOT NULL DEFAULT 0, stock INTEGER DEFAULT 0, talla TEXT DEFAULT '', color TEXT DEFAULT '', imagen TEXT DEFAULT '', coleccion_id INTEGER, activo INTEGER DEFAULT 1, destacado INTEGER DEFAULT 0, creado TEXT);
    CREATE TABLE IF NOT EXISTS pedidos(id INTEGER PRIMARY KEY AUTOINCREMENT, cliente TEXT, email TEXT, telefono TEXT, direccion TEXT, ciudad TEXT, metodo_pago TEXT, estado TEXT DEFAULT 'Pendiente', total INTEGER, notas TEXT, creado TEXT);
    CREATE TABLE IF NOT EXISTS pedido_items(id INTEGER PRIMARY KEY AUTOINCREMENT, pedido_id INTEGER, producto_id INTEGER, nombre TEXT, talla TEXT DEFAULT '', cantidad INTEGER, precio INTEGER);
    CREATE TABLE IF NOT EXISTS configuracion(clave TEXT PRIMARY KEY, valor TEXT DEFAULT '');
    ''')
    cols_prod=[r[1] for r in c.execute('PRAGMA table_info(productos)').fetchall()]
    if 'destacado' not in cols_prod:
        c.execute("ALTER TABLE productos ADD COLUMN destacado INTEGER DEFAULT 0")
    cols_items=[r[1] for r in c.execute('PRAGMA table_info(pedido_items)').fetchall()]
    if 'talla' not in cols_items:
        c.execute("ALTER TABLE pedido_items ADD COLUMN talla TEXT DEFAULT ''")
    defaults={
        'telefono_whatsapp':'34638067232',
        'correo_tienda':'contacto@artleandro.com',
        'ubicacion':'Cataluña - España',
        'paypal_correo':'pagos@artleandro.com',
        'nequi_numero':'638067232',
        'banco_info':'Banco / IBAN pendiente por configurar',
        'smtp_email':'',
        'smtp_password':'',
        'smtp_destino':'',
        'smtp_activo':'0',
        'whatsapp_api_activo':'0',
        'whatsapp_token':'',
        'whatsapp_phone_number_id':'',
        'whatsapp_destino':'34638067232'
    }
    for k,v in defaults.items():
        c.execute('INSERT OR IGNORE INTO configuracion(clave,valor) VALUES(?,?)',(k,v))
    c.execute("UPDATE productos SET talla='S,M,L,XL' WHERE talla IS NULL OR TRIM(talla)='' OR LOWER(REPLACE(talla,'ú','u')) IN ('unica','talla unica')")
    c.execute('SELECT COUNT(*) FROM admin')
    if c.fetchone()[0]==0: c.execute('INSERT INTO admin(usuario,password) VALUES(?,?)',(ADMIN_USER,generate_password_hash(ADMIN_PASS)))
    c.execute('SELECT COUNT(*) FROM colecciones')
    if c.fetchone()[0]==0:
        c.execute('INSERT INTO colecciones(nombre,descripcion,creada) VALUES(?,?,?)',('Colección inicial','Prendas cargadas desde las fotos enviadas',datetime.now().isoformat()))
    c.execute('SELECT COUNT(*) FROM productos')
    if c.fetchone()[0]==0:
        imgs=sorted([f for f in os.listdir(UPLOAD) if f.lower().endswith(('.jpg','.png','.jpeg','.webp'))])
        for i,img in enumerate(imgs,1):
            c.execute('INSERT INTO productos(nombre,descripcion,precio,stock,talla,color,imagen,coleccion_id,destacado,creado) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (f'Prenda Art Leandro {i:02d}','Producto listo para editar desde el panel administrador.',0,1,'S,M,L,XL','Por definir',img,1,1 if i<=4 else 0,datetime.now().isoformat()))
    db.commit(); db.close()

def money(v):
    try: return '${:,.0f}'.format(float(v)).replace(',', '.')
    except: return '$0'
app.jinja_env.filters['money']=money

def settings():
    rows=get_db().execute('SELECT clave,valor FROM configuracion').fetchall()
    return {r['clave']:r['valor'] for r in rows}

@app.context_processor
def inject_settings():
    try: cfg=settings()
    except Exception: cfg={}
    return dict(cfg=cfg)

def admin_required(f):
    @wraps(f)
    def w(*a,**k):
        if not session.get('admin'): return redirect(url_for('login'))
        return f(*a,**k)
    return w

def cart(): return session.setdefault('cart',{})
def _cart_key(producto_id, talla): return f"{producto_id}|{(talla or 'Talla por confirmar').strip()}"
def _parse_cart_key(key):
    if '|' in key:
        pid,talla=key.split('|',1); return int(pid),talla
    return int(key),'Talla por confirmar'

def cart_data():
    carrito=cart(); parsed=[]
    for key,qty in carrito.items():
        try:
            pid,talla=_parse_cart_key(key); parsed.append((key,pid,talla,int(qty)))
        except Exception: pass
    ids=sorted(set(pid for _,pid,_,_ in parsed))
    if not ids: return [],0
    q=','.join('?'*len(ids)); rows=get_db().execute(f'SELECT * FROM productos WHERE id IN ({q})',ids).fetchall()
    prod={r['id']:r for r in rows}; items=[]; total=0
    for key,pid,talla,cant in parsed:
        r=prod.get(pid)
        if not r: continue
        sub=cant*int(r['precio']); total+=sub
        items.append({'key':key,'p':r,'talla':talla,'cantidad':cant,'subtotal':sub})
    return items,total

def enviar_correo_pedido(pedido_id):
    cfg=settings()
    if cfg.get('smtp_activo')!='1' or not cfg.get('smtp_email') or not cfg.get('smtp_password'):
        return False, 'Correo SMTP no configurado'
    db=get_db(); p=db.execute('SELECT * FROM pedidos WHERE id=?',(pedido_id,)).fetchone(); items=db.execute('SELECT * FROM pedido_items WHERE pedido_id=?',(pedido_id,)).fetchall()
    destino=cfg.get('smtp_destino') or cfg.get('correo_tienda') or cfg.get('smtp_email')
    detalle='\n'.join([f"- {it['nombre']} | Talla: {it['talla']} | Cant: {it['cantidad']} | Precio: {money(it['precio'])}" for it in items])
    cuerpo=f"""Nueva compra registrada en Art Leandro

Pedido: #{p['id']}
Cliente: {p['cliente']}
Teléfono/WhatsApp: {p['telefono']}
Correo: {p['email']}
Ciudad: {p['ciudad']}
Dirección: {p['direccion']}
Método de pago: {p['metodo_pago']}
Total: {money(p['total'])}
Notas: {p['notas']}

Productos:
{detalle}

Fecha: {p['creado']}
"""
    msg=MIMEText(cuerpo,'plain','utf-8'); msg['Subject']=f"Nueva compra Art Leandro #{p['id']}"; msg['From']=cfg.get('smtp_email'); msg['To']=destino
    try:
        s=smtplib.SMTP('smtp.gmail.com',587,timeout=12); s.starttls(); s.login(cfg.get('smtp_email'),cfg.get('smtp_password')); s.send_message(msg); s.quit(); return True,'Correo enviado'
    except Exception as e:
        print('Error enviando correo:',e); return False,str(e)



def enviar_whatsapp_pedido(pedido_id):
    cfg=settings()
    if cfg.get('whatsapp_api_activo')!='1':
        return False, 'WhatsApp API no activa'
    token=(cfg.get('whatsapp_token') or '').strip()
    phone_id=(cfg.get('whatsapp_phone_number_id') or '').strip()
    destino=(cfg.get('whatsapp_destino') or cfg.get('telefono_whatsapp') or '').strip().replace('+','').replace(' ','')
    if not token or not phone_id or not destino:
        return False, 'Faltan datos de WhatsApp API'
    db=get_db()
    p=db.execute('SELECT * FROM pedidos WHERE id=?',(pedido_id,)).fetchone()
    items=db.execute('SELECT * FROM pedido_items WHERE pedido_id=?',(pedido_id,)).fetchall()
    detalle='\n'.join([f"- {it['nombre']} | Talla: {it['talla']} | Cant: {it['cantidad']} | Precio: {money(it['precio'])}" for it in items])
    texto=f"""🛍️ Nueva compra Art Leandro #{p['id']}

Cliente: {p['cliente']}
Teléfono: {p['telefono']}
Correo: {p['email']}
Ciudad: {p['ciudad']}
Dirección: {p['direccion']}
Pago: {p['metodo_pago']}
Total: {money(p['total'])}

Productos:
{detalle}

Fecha: {p['creado']}"""
    url=f"https://graph.facebook.com/v20.0/{phone_id}/messages"
    data=json.dumps({
        'messaging_product':'whatsapp',
        'to':destino,
        'type':'text',
        'text':{'preview_url':False,'body':texto}
    }).encode('utf-8')
    req=urllib.request.Request(url, data=data, method='POST', headers={
        'Authorization':'Bearer '+token,
        'Content-Type':'application/json'
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            print('WhatsApp enviado:', r.status)
        return True, 'WhatsApp enviado'
    except Exception as e:
        print('Error enviando WhatsApp:', e)
        return False, str(e)

@app.route('/healthz')
def healthz():
    return {'status':'ok','service':'ArtLeandro Tienda'}, 200

@app.route('/')
def index():
    db=get_db(); col=request.args.get('coleccion','')
    cols=db.execute('SELECT * FROM colecciones WHERE activa=1 ORDER BY nombre').fetchall()
    if col: productos=db.execute('SELECT p.*, c.nombre coleccion FROM productos p LEFT JOIN colecciones c ON c.id=p.coleccion_id WHERE p.activo=1 AND p.coleccion_id=? ORDER BY p.destacado DESC,p.id DESC',(col,)).fetchall()
    else: productos=db.execute('SELECT p.*, c.nombre coleccion FROM productos p LEFT JOIN colecciones c ON c.id=p.coleccion_id WHERE p.activo=1 ORDER BY p.destacado DESC,p.id DESC').fetchall()
    destacados=db.execute('SELECT * FROM productos WHERE activo=1 AND destacado=1 ORDER BY id DESC LIMIT 4').fetchall()
    return render_template('index.html',productos=productos,colecciones=cols,destacados=destacados,cart_count=sum(map(int,cart().values())),coleccion_sel=col)

@app.route('/agregar/<int:id>',methods=['POST'])
def agregar(id):
    cantidad=max(1,int(request.form.get('cantidad',1))); talla=request.form.get('talla','Talla por confirmar'); c=cart(); key=_cart_key(id,talla); c[key]=int(c.get(key,0))+cantidad; session.modified=True; flash('Producto agregado al carrito con talla seleccionada.','ok'); return redirect(request.referrer or url_for('index'))
@app.route('/carrito')
def ver_carrito(): items,total=cart_data(); return render_template('carrito.html',items=items,total=total)
@app.route('/carrito/actualizar',methods=['POST'])
def actualizar_carrito():
    c=cart()
    for k,v in request.form.items():
        if k.startswith('qty_'):
            key=k[4:]; qty=max(0,int(v or 0))
            if qty==0: c.pop(key,None)
            else: c[key]=qty
    session.modified=True; return redirect(url_for('ver_carrito'))
@app.route('/checkout',methods=['GET','POST'])
def checkout():
    items,total=cart_data()
    if not items: flash('Tu carrito está vacío.','err'); return redirect(url_for('index'))
    if request.method=='POST':
        f=request.form; db=get_db(); cur=db.execute('INSERT INTO pedidos(cliente,email,telefono,direccion,ciudad,metodo_pago,total,notas,creado) VALUES(?,?,?,?,?,?,?,?,?)',(f['cliente'],f.get('email',''),f['telefono'],f.get('direccion',''),f.get('ciudad',''),f['metodo_pago'],total,f.get('notas',''),datetime.now().strftime('%Y-%m-%d %H:%M')))
        oid=cur.lastrowid
        for it in items:
            db.execute('INSERT INTO pedido_items(pedido_id,producto_id,nombre,talla,cantidad,precio) VALUES(?,?,?,?,?,?)',(oid,it['p']['id'],it['p']['nombre'],it.get('talla',''),it['cantidad'],it['p']['precio']))
            try: db.execute('UPDATE productos SET stock=MAX(stock-?,0) WHERE id=?',(it['cantidad'],it['p']['id']))
            except Exception: pass
        db.commit(); enviar_correo_pedido(oid); enviar_whatsapp_pedido(oid); session['cart']={}; flash('Pedido registrado correctamente. El administrador verificará el pago y el despacho.','ok'); return redirect(url_for('pedido_ok',id=oid))
    return render_template('checkout.html',items=items,total=total)
@app.route('/pedido/<int:id>')
def pedido_ok(id):
    p=get_db().execute('SELECT * FROM pedidos WHERE id=?',(id,)).fetchone(); its=get_db().execute('SELECT * FROM pedido_items WHERE pedido_id=?',(id,)).fetchall(); return render_template('pedido.html',p=p,items=its)

@app.route('/admin/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        u=get_db().execute('SELECT * FROM admin WHERE usuario=?',(request.form['usuario'],)).fetchone()
        if u and check_password_hash(u['password'],request.form['password']): session['admin']=u['usuario']; return redirect(url_for('admin'))
        flash('Usuario o contraseña incorrectos.','err')
    return render_template('login.html')
@app.route('/admin/logout')
def logout(): session.clear(); return redirect(url_for('index'))
@app.route('/admin')
@admin_required
def admin():
    db=get_db(); productos=db.execute('SELECT p.*, c.nombre coleccion FROM productos p LEFT JOIN colecciones c ON c.id=p.coleccion_id ORDER BY p.id DESC').fetchall(); cols=db.execute('SELECT * FROM colecciones ORDER BY nombre').fetchall(); pedidos=db.execute('SELECT * FROM pedidos ORDER BY id DESC').fetchall(); total_ventas=db.execute("SELECT COALESCE(SUM(total),0) t FROM pedidos WHERE estado!='Cancelado'").fetchone()['t']; pendientes=db.execute("SELECT COUNT(*) c FROM pedidos WHERE estado='Pendiente'").fetchone()['c']; return render_template('admin.html',productos=productos,colecciones=cols,pedidos=pedidos,total_ventas=total_ventas,pendientes=pendientes)

def save_file(file):
    if not file or not file.filename: return ''
    ext=file.filename.rsplit('.',1)[-1].lower()
    if ext not in ALLOWED: return ''
    os.makedirs(UPLOAD, exist_ok=True)
    name=datetime.now().strftime('%Y%m%d%H%M%S_')+secure_filename(file.filename); file.save(os.path.join(UPLOAD,name)); return name
@app.route('/admin/producto/nuevo',methods=['POST'])
@admin_required
def nuevo_producto():
    f=request.form; img=save_file(request.files.get('imagen'))
    get_db().execute('INSERT INTO productos(nombre,descripcion,precio,stock,talla,color,imagen,coleccion_id,activo,destacado,creado) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(f['nombre'],f.get('descripcion',''),int(f.get('precio') or 0),int(f.get('stock') or 0),(f.get('talla') or 'S,M,L,XL'),f.get('color',''),img,f.get('coleccion_id') or None,1,1 if f.get('destacado') else 0,datetime.now().isoformat())); get_db().commit(); flash('Producto creado.','ok'); return redirect(url_for('admin'))
@app.route('/admin/producto/<int:id>/editar',methods=['POST'])
@admin_required
def editar_producto(id):
    f=request.form; db=get_db(); img=save_file(request.files.get('imagen')); old=db.execute('SELECT imagen FROM productos WHERE id=?',(id,)).fetchone(); img=img or (old['imagen'] if old else '')
    db.execute('UPDATE productos SET nombre=?,descripcion=?,precio=?,stock=?,talla=?,color=?,imagen=?,coleccion_id=?,activo=?,destacado=? WHERE id=?',(f['nombre'],f.get('descripcion',''),int(f.get('precio') or 0),int(f.get('stock') or 0),(f.get('talla') or 'S,M,L,XL'),f.get('color',''),img,f.get('coleccion_id') or None,1 if f.get('activo') else 0,1 if f.get('destacado') else 0,id)); db.commit(); flash('Producto actualizado.','ok'); return redirect(url_for('admin'))
@app.route('/admin/coleccion/nueva',methods=['POST'])
@admin_required
def nueva_coleccion(): get_db().execute('INSERT INTO colecciones(nombre,descripcion,creada) VALUES(?,?,?)',(request.form['nombre'],request.form.get('descripcion',''),datetime.now().isoformat())); get_db().commit(); flash('Colección creada.','ok'); return redirect(url_for('admin'))
@app.route('/admin/coleccion/<int:id>/editar',methods=['POST'])
@admin_required
def editar_coleccion(id):
    f=request.form; get_db().execute('UPDATE colecciones SET nombre=?, descripcion=?, activa=? WHERE id=?',(f['nombre'],f.get('descripcion',''),1 if f.get('activa') else 0,id)); get_db().commit(); flash('Colección actualizada.','ok'); return redirect(url_for('admin'))
@app.route('/admin/pedido/<int:id>/estado',methods=['POST'])
@admin_required
def estado_pedido(id): get_db().execute('UPDATE pedidos SET estado=? WHERE id=?',(request.form['estado'],id)); get_db().commit(); return redirect(url_for('admin'))
@app.route('/admin/configuracion',methods=['POST'])
@admin_required
def guardar_configuracion():
    db=get_db()
    for k,v in request.form.items(): db.execute('INSERT INTO configuracion(clave,valor) VALUES(?,?) ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor',(k,v))
    if 'smtp_activo' not in request.form: db.execute('UPDATE configuracion SET valor=? WHERE clave=?',('0','smtp_activo'))
    if 'whatsapp_api_activo' not in request.form: db.execute('UPDATE configuracion SET valor=? WHERE clave=?',('0','whatsapp_api_activo'))
    db.commit(); flash('Configuración actualizada.','ok'); return redirect(url_for('admin'))
@app.route('/admin/exportar_pedidos')
@admin_required
def exportar_pedidos():
    rows=get_db().execute('SELECT * FROM pedidos ORDER BY id DESC').fetchall(); out=io.StringIO(); w=csv.writer(out); w.writerow(['ID','Cliente','Email','Telefono','Ciudad','Direccion','Metodo pago','Estado','Total','Notas','Fecha'])
    for r in rows: w.writerow([r['id'],r['cliente'],r['email'],r['telefono'],r['ciudad'],r['direccion'],r['metodo_pago'],r['estado'],r['total'],r['notas'],r['creado']])
    return Response(out.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=pedidos_artleandro.csv'})


# Inicializa la base de datos al arrancar, tanto local como en Render
init_db()

if __name__=='__main__':
    port = int(os.environ.get('PORT', 5057))
    app.run(host='0.0.0.0', port=port, debug=False)
