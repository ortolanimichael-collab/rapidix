import os
import re
import uuid
import unicodedata
from decimal import Decimal

from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.utils import secure_filename

from models import db, Negocio, Categoria, Subcategoria, Producto, Pedido, ItemPedido

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-cambiar-en-produccion")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///rapidix.db"
).replace("postgres://", "postgresql://", 1)  # Render entrega postgres:// viejo, SQLAlchemy 2 pide postgresql://
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8MB por archivo subido

db.init_app(app)

with app.app_context():
    db.create_all()

EXTENSIONES_PERMITIDAS = {"png", "jpg", "jpeg", "webp"}
CARPETA_UPLOADS = os.path.join(app.root_path, "static", "uploads")


def slugify(texto):
    texto = texto.lower().strip()
    # Transliterar acentos (á->a, ñ->n, etc.) en vez de descartar la letra
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"[^a-z0-9\s-]", "", texto)
    texto = re.sub(r"[\s-]+", "-", texto).strip("-")
    return texto


def guardar_imagen(archivo, negocio_id, subcarpeta):
    """
    Guarda una imagen subida en static/uploads/<negocio_id>/<subcarpeta>/<nombre-unico>.ext
    y devuelve la ruta relativa a servir (o None si no vino archivo válido).
    Cada negocio tiene su propia carpeta: sus fotos quedan aisladas de las de otros negocios.
    """
    if not archivo or archivo.filename == "":
        return None

    extension = archivo.filename.rsplit(".", 1)[-1].lower() if "." in archivo.filename else ""
    if extension not in EXTENSIONES_PERMITIDAS:
        return None

    nombre_unico = f"{uuid.uuid4().hex}.{extension}"
    carpeta_destino = os.path.join(CARPETA_UPLOADS, str(negocio_id), subcarpeta)
    os.makedirs(carpeta_destino, exist_ok=True)

    ruta_absoluta = os.path.join(carpeta_destino, secure_filename(nombre_unico))
    archivo.save(ruta_absoluta)

    return f"uploads/{negocio_id}/{subcarpeta}/{nombre_unico}"


def negocio_actual():
    negocio_id = session.get("negocio_id")
    return Negocio.query.get(negocio_id) if negocio_id else None


# ---------------------------------------------------------------------------
# Landing / home de Rapidix
# ---------------------------------------------------------------------------
@app.route("/")
def home():
    return render_template("home.html")


# ---------------------------------------------------------------------------
# Registro e inicio de sesión de negocio
# ---------------------------------------------------------------------------
@app.route("/registro-negocio", methods=["GET", "POST"])
def registro_negocio():
    if request.method == "POST":
        nombre = request.form["nombre"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        slug_base = slugify(nombre)
        slug = slug_base
        contador = 1
        while Negocio.query.filter_by(slug=slug).first():
            contador += 1
            slug = f"{slug_base}-{contador}"

        if Negocio.query.filter_by(email=email).first():
            flash("Ya existe una cuenta con ese email.", "error")
            return redirect(url_for("registro_negocio"))

        negocio = Negocio(nombre=nombre, email=email, slug=slug)
        negocio.set_password(password)
        db.session.add(negocio)
        db.session.commit()

        # TODO: avisar a panel-membresias (webhook de alta) cuando esté la URL del panel

        session["negocio_id"] = negocio.id
        return redirect(url_for("panel_dueno"))

    return render_template("registro_negocio.html")


@app.route("/iniciar-sesion", methods=["GET", "POST"])
def iniciar_sesion():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        negocio = Negocio.query.filter_by(email=email).first()
        if not negocio or not negocio.check_password(password):
            flash("Email o contraseña incorrectos.", "error")
            return redirect(url_for("iniciar_sesion"))

        session["negocio_id"] = negocio.id
        return redirect(url_for("panel_dueno"))

    return render_template("iniciar_sesion.html")


@app.route("/cerrar-sesion")
def cerrar_sesion():
    session.pop("negocio_id", None)
    return redirect(url_for("home"))


# ---------------------------------------------------------------------------
# Tienda pública de un negocio: rapidix.com/<slug>
# Home de la tienda = grid de categorías (como la home de Pedix)
# ---------------------------------------------------------------------------
@app.route("/<slug>")
def tienda_negocio(slug):
    negocio = Negocio.query.filter_by(slug=slug, activo=True).first_or_404()
    categorias = Categoria.query.filter_by(negocio_id=negocio.id).order_by(Categoria.orden).all()
    return render_template("tienda.html", negocio=negocio, categorias=categorias)


@app.route("/<slug>/categoria/<int:categoria_id>")
def tienda_categoria(slug, categoria_id):
    negocio = Negocio.query.filter_by(slug=slug, activo=True).first_or_404()
    categoria = Categoria.query.filter_by(id=categoria_id, negocio_id=negocio.id).first_or_404()
    subcategorias = Subcategoria.query.filter_by(categoria_id=categoria.id).order_by(Subcategoria.orden).all()

    if subcategorias:
        # Con pestañas: productos agrupados por subcategoría
        grupos = []
        for sub in subcategorias:
            productos = Producto.query.filter_by(
                subcategoria_id=sub.id, disponible=True
            ).all()
            grupos.append({"subcategoria": sub, "productos": productos})
        # Productos de la categoría sin subcategoría asignada (por si el negocio mezcla)
        sueltos = Producto.query.filter_by(
            categoria_id=categoria.id, subcategoria_id=None, disponible=True
        ).all()
        if sueltos:
            grupos.append({"subcategoria": None, "productos": sueltos})
        return render_template(
            "tienda_categoria.html", negocio=negocio, categoria=categoria,
            subcategorias=subcategorias, grupos=grupos
        )

    # Sin subcategorías: lista plana, directo (como "Cafetería" en el ejemplo)
    productos = Producto.query.filter_by(categoria_id=categoria.id, disponible=True).all()
    return render_template(
        "tienda_categoria.html", negocio=negocio, categoria=categoria,
        subcategorias=[], grupos=[{"subcategoria": None, "productos": productos}]
    )


# ---------------------------------------------------------------------------
# Carrito (guardado en sesión, por negocio)
# ---------------------------------------------------------------------------
def _carrito_key(negocio_id):
    return f"carrito_{negocio_id}"


@app.route("/<slug>/carrito/agregar", methods=["POST"])
def carrito_agregar(slug):
    negocio = Negocio.query.filter_by(slug=slug, activo=True).first_or_404()
    producto_id = int(request.form["producto_id"])
    cantidad = int(request.form.get("cantidad", 1))

    producto = Producto.query.filter_by(id=producto_id, negocio_id=negocio.id).first_or_404()

    key = _carrito_key(negocio.id)
    carrito = session.get(key, {})
    carrito[str(producto_id)] = carrito.get(str(producto_id), 0) + cantidad
    session[key] = carrito

    return redirect(request.referrer or url_for("tienda_negocio", slug=slug))


@app.route("/<slug>/carrito")
def ver_carrito(slug):
    negocio = Negocio.query.filter_by(slug=slug, activo=True).first_or_404()
    carrito = session.get(_carrito_key(negocio.id), {})

    items = []
    total = Decimal("0")
    for producto_id, cantidad in carrito.items():
        producto = Producto.query.get(int(producto_id))
        if not producto:
            continue
        subtotal = producto.precio * cantidad
        total += subtotal
        items.append({"producto": producto, "cantidad": cantidad, "subtotal": subtotal})

    return render_template("carrito.html", negocio=negocio, items=items, total=total)


@app.route("/<slug>/checkout", methods=["POST"])
def checkout(slug):
    negocio = Negocio.query.filter_by(slug=slug, activo=True).first_or_404()
    carrito = session.get(_carrito_key(negocio.id), {})

    if not carrito:
        flash("El carrito está vacío.", "error")
        return redirect(url_for("ver_carrito", slug=slug))

    pedido = Pedido(
        negocio_id=negocio.id,
        cliente_nombre=request.form["cliente_nombre"].strip(),
        cliente_telefono=request.form.get("cliente_telefono", "").strip(),
        cliente_direccion=request.form.get("cliente_direccion", "").strip(),
        notas=request.form.get("notas", "").strip(),
    )
    db.session.add(pedido)
    db.session.flush()  # para tener pedido.id antes de commit

    total = Decimal("0")
    for producto_id, cantidad in carrito.items():
        producto = Producto.query.get(int(producto_id))
        if not producto:
            continue
        subtotal = producto.precio * cantidad
        total += subtotal
        db.session.add(ItemPedido(
            pedido_id=pedido.id,
            producto_id=producto.id,
            nombre_producto=producto.nombre,
            precio_unitario=producto.precio,
            cantidad=cantidad,
        ))

    pedido.total = total
    db.session.commit()

    session.pop(_carrito_key(negocio.id), None)

    return render_template("pedido_confirmado.html", negocio=negocio, pedido=pedido)


# ---------------------------------------------------------------------------
# Panel del dueño del negocio
# ---------------------------------------------------------------------------
@app.route("/panel")
def panel_dueno():
    negocio = negocio_actual()
    if not negocio:
        return redirect(url_for("iniciar_sesion"))

    categorias = Categoria.query.filter_by(negocio_id=negocio.id).order_by(Categoria.orden).all()
    pedidos = Pedido.query.filter_by(negocio_id=negocio.id).order_by(Pedido.creado_en.desc()).all()

    return render_template("panel_dueno.html", negocio=negocio, categorias=categorias, pedidos=pedidos)


@app.route("/panel/categorias/nueva", methods=["POST"])
def categoria_nueva():
    negocio = negocio_actual()
    if not negocio:
        return redirect(url_for("iniciar_sesion"))

    foto = guardar_imagen(request.files.get("foto"), negocio.id, "categorias")

    categoria = Categoria(
        negocio_id=negocio.id,
        nombre=request.form["nombre"].strip(),
        foto=foto,
    )
    db.session.add(categoria)
    db.session.commit()

    return redirect(url_for("panel_dueno"))


@app.route("/panel/subcategorias/nueva", methods=["POST"])
def subcategoria_nueva():
    negocio = negocio_actual()
    if not negocio:
        return redirect(url_for("iniciar_sesion"))

    categoria_id = int(request.form["categoria_id"])
    categoria = Categoria.query.filter_by(id=categoria_id, negocio_id=negocio.id).first_or_404()

    subcategoria = Subcategoria(
        categoria_id=categoria.id,
        nombre=request.form["nombre"].strip(),
    )
    db.session.add(subcategoria)
    db.session.commit()

    return redirect(url_for("panel_dueno"))


@app.route("/panel/productos/nuevo", methods=["POST"])
def producto_nuevo():
    negocio = negocio_actual()
    if not negocio:
        return redirect(url_for("iniciar_sesion"))

    categoria_id = int(request.form["categoria_id"])
    categoria = Categoria.query.filter_by(id=categoria_id, negocio_id=negocio.id).first_or_404()

    subcategoria_id = request.form.get("subcategoria_id") or None
    if subcategoria_id:
        subcategoria_id = int(subcategoria_id)
        Subcategoria.query.filter_by(id=subcategoria_id, categoria_id=categoria.id).first_or_404()

    precio_original_raw = request.form.get("precio_original", "").strip()
    precio_original = Decimal(precio_original_raw) if precio_original_raw else None

    foto = guardar_imagen(request.files.get("foto"), negocio.id, "productos")

    producto = Producto(
        negocio_id=negocio.id,
        categoria_id=categoria.id,
        subcategoria_id=subcategoria_id,
        nombre=request.form["nombre"].strip(),
        descripcion=request.form.get("descripcion", "").strip(),
        precio=Decimal(request.form["precio"]),
        precio_original=precio_original,
        foto=foto,
    )
    db.session.add(producto)
    db.session.commit()

    return redirect(url_for("panel_dueno"))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
