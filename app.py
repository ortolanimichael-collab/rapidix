import os
import re
import unicodedata
from decimal import Decimal

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from models import db, Negocio, Producto, Pedido, ItemPedido

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-cambiar-en-produccion")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///rapidix.db"
).replace("postgres://", "postgresql://", 1)  # Render entrega postgres:// viejo, SQLAlchemy 2 pide postgresql://
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)


def slugify(texto):
    texto = texto.lower().strip()
    # Transliterar acentos (á->a, ñ->n, etc.) en vez de descartar la letra
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"[^a-z0-9\s-]", "", texto)
    texto = re.sub(r"[\s-]+", "-", texto).strip("-")
    return texto


# ---------------------------------------------------------------------------
# Landing / home de Rapidix (no es marketplace: solo explica el producto y
# lleva a registrar un negocio o a iniciar sesión)
# ---------------------------------------------------------------------------
@app.route("/")
def home():
    return render_template("home.html")


# ---------------------------------------------------------------------------
# Registro de negocio
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


# ---------------------------------------------------------------------------
# Tienda pública de un negocio: rapidix.com/<slug>
# Solo muestra productos de ESE negocio, sin ruido de otros.
# ---------------------------------------------------------------------------
@app.route("/<slug>")
def tienda_negocio(slug):
    negocio = Negocio.query.filter_by(slug=slug, activo=True).first_or_404()
    productos = Producto.query.filter_by(negocio_id=negocio.id, disponible=True).all()
    return render_template("tienda.html", negocio=negocio, productos=productos)


# ---------------------------------------------------------------------------
# Carrito (guardado en sesión, por negocio, para no mezclar carritos de
# distintas tiendas si el cliente navega varias)
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

    return redirect(url_for("tienda_negocio", slug=slug))


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
# Panel del dueño del negocio (carga de productos, ver pedidos)
# ---------------------------------------------------------------------------
@app.route("/panel")
def panel_dueno():
    negocio_id = session.get("negocio_id")
    if not negocio_id:
        return redirect(url_for("registro_negocio"))

    negocio = Negocio.query.get_or_404(negocio_id)
    productos = Producto.query.filter_by(negocio_id=negocio.id).all()
    pedidos = Pedido.query.filter_by(negocio_id=negocio.id).order_by(Pedido.creado_en.desc()).all()

    return render_template("panel_dueno.html", negocio=negocio, productos=productos, pedidos=pedidos)


@app.route("/panel/productos/nuevo", methods=["POST"])
def producto_nuevo():
    negocio_id = session.get("negocio_id")
    if not negocio_id:
        return redirect(url_for("registro_negocio"))

    producto = Producto(
        negocio_id=negocio_id,
        nombre=request.form["nombre"].strip(),
        descripcion=request.form.get("descripcion", "").strip(),
        precio=Decimal(request.form["precio"]),
        categoria=request.form.get("categoria", "").strip(),
    )
    db.session.add(producto)
    db.session.commit()

    return redirect(url_for("panel_dueno"))


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5000)
