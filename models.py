from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class Negocio(db.Model):
    """
    Cada negocio registrado tiene su propia 'tienda' accesible por slug
    (ej. rapidix.com/nombredelnegocio o nombredelnegocio.rapidix.com).
    El cliente que entra a esa URL ve SOLO los productos de este negocio.
    """
    __tablename__ = "negocios"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(80), unique=True, nullable=False, index=True)
    nombre = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    # Perfil comercial
    descripcion = db.Column(db.Text)
    foto_portada = db.Column(db.String(255))
    foto_perfil = db.Column(db.String(255))
    whatsapp = db.Column(db.String(30))
    direccion = db.Column(db.String(255))

    # Estado de cuenta / membresía (sincronizado con panel-membresias vía webhook)
    activo = db.Column(db.Boolean, default=True)
    membresia_vencimiento = db.Column(db.DateTime)

    # Facturación (Opción A/B a definir con Facturea — por ahora solo el flag de opt-in)
    facturacion_habilitada = db.Column(db.Boolean, default=False)
    facturea_empresa_id = db.Column(db.String(80))  # referencia a la empresa en Facturea, si aplica

    creado_en = db.Column(db.DateTime, default=datetime.utcnow)

    productos = db.relationship("Producto", backref="negocio", cascade="all, delete-orphan")
    pedidos = db.relationship("Pedido", backref="negocio", cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Producto(db.Model):
    __tablename__ = "productos"

    id = db.Column(db.Integer, primary_key=True)
    negocio_id = db.Column(db.Integer, db.ForeignKey("negocios.id"), nullable=False)

    nombre = db.Column(db.String(120), nullable=False)
    descripcion = db.Column(db.Text)
    precio = db.Column(db.Numeric(10, 2), nullable=False)
    foto = db.Column(db.String(255))
    categoria = db.Column(db.String(80))
    disponible = db.Column(db.Boolean, default=True)
    stock = db.Column(db.Integer)  # null = sin control de stock

    creado_en = db.Column(db.DateTime, default=datetime.utcnow)


class Pedido(db.Model):
    __tablename__ = "pedidos"

    id = db.Column(db.Integer, primary_key=True)
    negocio_id = db.Column(db.Integer, db.ForeignKey("negocios.id"), nullable=False)

    cliente_nombre = db.Column(db.String(120), nullable=False)
    cliente_telefono = db.Column(db.String(30))
    cliente_direccion = db.Column(db.String(255))
    notas = db.Column(db.Text)

    total = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    estado = db.Column(db.String(30), default="pendiente")  # pendiente, confirmado, entregado, cancelado

    facturado = db.Column(db.Boolean, default=False)
    factura_id = db.Column(db.String(80))  # referencia al comprobante en Facturea, si se facturó

    creado_en = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship("ItemPedido", backref="pedido", cascade="all, delete-orphan")


class ItemPedido(db.Model):
    __tablename__ = "items_pedido"

    id = db.Column(db.Integer, primary_key=True)
    pedido_id = db.Column(db.Integer, db.ForeignKey("pedidos.id"), nullable=False)
    producto_id = db.Column(db.Integer, db.ForeignKey("productos.id"), nullable=False)

    nombre_producto = db.Column(db.String(120), nullable=False)  # snapshot al momento de la compra
    precio_unitario = db.Column(db.Numeric(10, 2), nullable=False)  # snapshot
    cantidad = db.Column(db.Integer, nullable=False, default=1)
