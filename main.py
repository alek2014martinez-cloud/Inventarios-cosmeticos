# -*- coding: utf-8 -*-
"""
Control de Inventario de COSMÉTICOS - versión ANDROID (Kivy)
- Interfaz táctil con Kivy
- Base de datos: sqlite3 (se guarda en la carpeta privada de la app)
- Botones + / - junto a cada producto: un toque suma o resta 1 al stock
- Escáner por emulación de teclado (lector Bluetooth/USB) o escribiendo el código
- Precio de costo, precio público y ganancia total del inventario

Compilar APK:  buildozer -v android debug
"""

import os
import sqlite3
from datetime import date, datetime

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import ListProperty, NumericProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.utils import escape_markup as esc
from kivy.utils import get_color_from_hex as hexc

DB_NAME = "inventario_cosmeticos.db"
DIAS_ALERTA = 30
MAX_LOG = 10
MONEDA = "C$"   # Cambia aquí el símbolo de moneda (ej. "$", "US$", "C$")
CATEGORIAS = ["Labiales", "Bases", "Sombras", "Rubores", "Delineadores",
              "Máscaras de pestañas", "Correctores", "Polvos", "Skincare", "Otros"]

COLOR_ENTRADA = "#2e9e5b"
COLOR_SALIDA = "#d9534f"
COLOR_AZUL = "#1f4e9c"
COLOR_NEUTRO = "#f0f0f0"


def fmt_dinero(valor):
    return f"{MONEDA}{valor:,.2f}"


def parsear_precio(texto):
    """Convierte texto a float >= 0 (acepta coma o punto decimal). Lanza ValueError."""
    t = texto.strip().replace(",", ".")
    if t == "":
        return 0.0
    v = float(t)
    if v < 0:
        raise ValueError
    return round(v, 2)


def vibrar(ms=60):
    """Vibración corta como retroalimentación (solo Android; ignora errores)."""
    try:
        from jnius import autoclass
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        context = autoclass("android.content.Context")
        activity.getSystemService(context.VIBRATOR_SERVICE).vibrate(ms)
    except Exception:
        pass


# --------------------------------------------------------------------------
# Capa de datos
# --------------------------------------------------------------------------
class Database:
    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self._crear_tabla()
        self._migrar()
        self._datos_muestra()

    def _crear_tabla(self):
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS productos (
                    codigo_barras     TEXT PRIMARY KEY,
                    marca             TEXT NOT NULL,
                    nombre_producto   TEXT NOT NULL,
                    tono_color        TEXT,
                    categoria         TEXT,
                    cantidad_stock    INTEGER NOT NULL DEFAULT 0,
                    fecha_vencimiento TEXT,
                    precio_costo      REAL NOT NULL DEFAULT 0,
                    precio_publico    REAL NOT NULL DEFAULT 0
                )
            """)

    def _migrar(self):
        cols = [r["name"] for r in self.conn.execute("PRAGMA table_info(productos)")]
        with self.conn:
            if "precio_costo" not in cols:
                self.conn.execute(
                    "ALTER TABLE productos ADD COLUMN precio_costo REAL NOT NULL DEFAULT 0")
            if "precio_publico" not in cols:
                self.conn.execute(
                    "ALTER TABLE productos ADD COLUMN precio_publico REAL NOT NULL DEFAULT 0")

    def _datos_muestra(self):
        n = self.conn.execute("SELECT COUNT(*) FROM productos").fetchone()[0]
        if n > 0:
            return
        hoy = date.today()
        muestras = [
            ("041554561227", "Maybelline", "Fit Me Matte + Poreless", "120 Classic Ivory",
             "Bases", 24, hoy.replace(year=hoy.year + 2).isoformat(), 180.0, 280.0),
            ("773602453028", "MAC", "Retro Matte Lipstick", "Ruby Woo",
             "Labiales", 8, date.fromordinal(hoy.toordinal() + 20).isoformat(),
             600.0, 950.0),
            ("3614272049529", "L'Oréal Paris", "Lash Paradise Mascara", "Negro Intenso",
             "Máscaras de pestañas", 15, hoy.replace(year=hoy.year + 1).isoformat(), 250.0, 390.0),
        ]
        with self.conn:
            self.conn.executemany("""
                INSERT INTO productos (codigo_barras, marca, nombre_producto, tono_color,
                                       categoria, cantidad_stock, fecha_vencimiento,
                                       precio_costo, precio_publico)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, muestras)

    def obtener(self, codigo):
        return self.conn.execute(
            "SELECT * FROM productos WHERE codigo_barras = ?", (codigo,)).fetchone()

    def buscar(self, texto=""):
        like = f"%{texto.strip()}%"
        return self.conn.execute("""
            SELECT * FROM productos
            WHERE codigo_barras LIKE ? OR marca LIKE ? OR nombre_producto LIKE ?
                  OR tono_color LIKE ? OR categoria LIKE ?
            ORDER BY marca COLLATE NOCASE, nombre_producto COLLATE NOCASE
        """, (like, like, like, like, like)).fetchall()

    def insertar(self, d):
        with self.conn:
            self.conn.execute("""
                INSERT INTO productos (codigo_barras, marca, nombre_producto, tono_color,
                                       categoria, cantidad_stock, fecha_vencimiento,
                                       precio_costo, precio_publico)
                VALUES (:codigo, :marca, :nombre, :tono, :categoria, :stock, :vencimiento,
                        :costo, :publico)
            """, d)

    def actualizar(self, d):
        with self.conn:
            self.conn.execute("""
                UPDATE productos SET marca=:marca, nombre_producto=:nombre, tono_color=:tono,
                       categoria=:categoria, cantidad_stock=:stock, fecha_vencimiento=:vencimiento,
                       precio_costo=:costo, precio_publico=:publico
                WHERE codigo_barras=:codigo
            """, d)

    def set_stock(self, codigo, stock):
        with self.conn:
            self.conn.execute(
                "UPDATE productos SET cantidad_stock=? WHERE codigo_barras=?", (stock, codigo))

    def eliminar(self, codigo):
        with self.conn:
            self.conn.execute("DELETE FROM productos WHERE codigo_barras=?", (codigo,))


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def dias_para_vencer(fecha_txt):
    """Devuelve días restantes (negativo = vencido) o None si no hay fecha válida."""
    if not fecha_txt:
        return None
    try:
        f = datetime.strptime(fecha_txt, "%Y-%m-%d").date()
    except ValueError:
        return None
    return (f - date.today()).days


def estado_vencimiento(fecha_txt):
    d = dias_para_vencer(fecha_txt)
    if d is None:
        return "Sin fecha"
    if d < 0:
        return f"VENCIDO (hace {-d} d)"
    if d <= DIAS_ALERTA:
        return f"Vence en {d} d"
    return "OK"


def etiqueta_producto(row):
    tono = f" [Tono {row['tono_color']}]" if row["tono_color"] else ""
    return f"{row['marca']} {row['nombre_producto']}{tono}"


def etiqueta_dict(d):
    tono = f" [Tono {d['tono']}]" if d["tono"] else ""
    return f"{d['marca']} {d['nombre']}{tono}"


# --------------------------------------------------------------------------
# Widgets personalizados
# --------------------------------------------------------------------------
class ColorLabel(Label):
    bg_color = ListProperty(hexc(COLOR_NEUTRO))


class InfoArea(ButtonBehavior, Label):
    """Zona de texto del producto: al tocarla se abre la edición."""


class ProductoRow(BoxLayout):
    codigo = StringProperty("")
    texto = StringProperty("")
    stock = NumericProperty(0)
    bg = ListProperty([1, 1, 1, 1])


def _wrap(label):
    label.bind(size=lambda w, s: setattr(w, "text_size", (s[0], None)))


def confirmar(titulo, mensaje, on_si):
    box = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(10))
    lbl = Label(text=mensaje, halign="center", valign="middle")
    lbl.bind(size=lambda w, s: setattr(w, "text_size", s))
    box.add_widget(lbl)
    fila = BoxLayout(size_hint_y=None, height=dp(54), spacing=dp(10))
    pop = Popup(title=titulo, content=box, size_hint=(0.9, 0.38), auto_dismiss=False)

    def si(*_):
        pop.dismiss()
        on_si()

    b_no = Button(text="No", font_size="16sp", on_release=lambda *_: pop.dismiss())
    b_si = Button(text="Sí, eliminar", font_size="16sp", bold=True, background_normal="",
                  background_color=hexc(COLOR_SALIDA), on_release=si)
    fila.add_widget(b_no)
    fila.add_widget(b_si)
    box.add_widget(fila)
    pop.open()


# --------------------------------------------------------------------------
# Formulario flotante (alta / edición)
# --------------------------------------------------------------------------
class ProductoPopup(Popup):
    def __init__(self, app, titulo, datos=None, codigo_bloqueado=False,
                 on_save=None, on_delete=None, on_cancel=None):
        super().__init__(title=titulo, size_hint=(0.96, 0.94), auto_dismiss=False)
        self.app = app
        self.on_save = on_save
        self.on_delete = on_delete
        self.on_cancel = on_cancel
        self._aviso_neg = False
        self.campos = {}
        app.dialogos += 1

        datos = datos or {}
        grid = GridLayout(cols=1, spacing=dp(4), size_hint_y=None, padding=(0, 0, 0, dp(8)))
        grid.bind(minimum_height=grid.setter("height"))

        def etiqueta(texto):
            lbl = Label(text=texto, size_hint_y=None, height=dp(24), halign="left",
                        valign="middle", font_size="13sp")
            lbl.bind(size=lambda w, s: setattr(w, "text_size", s))
            grid.add_widget(lbl)

        def entrada(valor="", **kw):
            return TextInput(text=str(valor), multiline=False, size_hint_y=None,
                             height=dp(46), write_tab=False, font_size="16sp", **kw)

        etiqueta("Código de barras:")
        self.campos["codigo"] = entrada(datos.get("codigo", ""), disabled=codigo_bloqueado)
        grid.add_widget(self.campos["codigo"])

        etiqueta("Marca *:")
        self.campos["marca"] = entrada(datos.get("marca", ""))
        grid.add_widget(self.campos["marca"])

        etiqueta("Nombre del producto *:")
        self.campos["nombre"] = entrada(datos.get("nombre", ""))
        grid.add_widget(self.campos["nombre"])

        etiqueta("Tono / Color:")
        self.campos["tono"] = entrada(datos.get("tono", ""))
        grid.add_widget(self.campos["tono"])

        etiqueta("Categoría:")
        cat = datos.get("categoria", CATEGORIAS[0])
        valores = list(CATEGORIAS) + ([cat] if cat not in CATEGORIAS else [])
        self.campos["categoria"] = Spinner(text=cat, values=valores, size_hint_y=None,
                                           height=dp(46), font_size="16sp")
        grid.add_widget(self.campos["categoria"])

        etiqueta("Stock (usa + / - o escribe):")
        fila_stock = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(6))
        fila_stock.add_widget(Button(text="-", font_size="28sp", bold=True, size_hint_x=None,
                                     width=dp(64), background_normal="",
                                     background_color=hexc(COLOR_SALIDA),
                                     on_release=lambda *_: self._ajustar_stock(-1)))
        self.campos["stock"] = entrada(datos.get("stock", 1), input_filter="int",
                                       input_type="number", halign="center")
        fila_stock.add_widget(self.campos["stock"])
        fila_stock.add_widget(Button(text="+", font_size="28sp", bold=True, size_hint_x=None,
                                     width=dp(64), background_normal="",
                                     background_color=hexc(COLOR_ENTRADA),
                                     on_release=lambda *_: self._ajustar_stock(1)))
        grid.add_widget(fila_stock)

        etiqueta(f"Precio de costo ({MONEDA}):")
        self.campos["costo"] = entrada(f"{datos.get('costo', 0):.2f}", input_type="number")
        grid.add_widget(self.campos["costo"])

        etiqueta(f"Precio público ({MONEDA}):")
        self.campos["publico"] = entrada(f"{datos.get('publico', 0):.2f}", input_type="number")
        grid.add_widget(self.campos["publico"])

        etiqueta("Vencimiento (AAAA-MM-DD):")
        self.campos["vencimiento"] = entrada(datos.get("vencimiento", ""),
                                             hint_text="Ej. 2027-05-31")
        grid.add_widget(self.campos["vencimiento"])

        scroll = ScrollView()
        scroll.add_widget(grid)

        self.lbl_ganancia = Label(text="", size_hint_y=None, height=dp(28), bold=True,
                                  font_size="14sp")
        self.lbl_error = Label(text="", size_hint_y=None, height=dp(40), halign="center",
                               valign="middle", color=hexc("#ff7b7b"), font_size="13sp")
        self.lbl_error.bind(size=lambda w, s: setattr(w, "text_size", s))

        for k in ("costo", "publico"):
            self.campos[k].bind(text=lambda *_: self._calc_ganancia())
        self._calc_ganancia()

        botones = BoxLayout(size_hint_y=None, height=dp(56), spacing=dp(8))
        botones.add_widget(Button(text="Cancelar", font_size="16sp",
                                  on_release=lambda *_: self._cancelar()))
        if on_delete:
            botones.add_widget(Button(text="Eliminar", font_size="16sp", bold=True,
                                      background_normal="", background_color=hexc(COLOR_SALIDA),
                                      on_release=lambda *_: self._eliminar()))
        botones.add_widget(Button(text="Guardar", font_size="16sp", bold=True,
                                  background_normal="", background_color=hexc(COLOR_ENTRADA),
                                  on_release=lambda *_: self._guardar()))

        raiz = BoxLayout(orientation="vertical", spacing=dp(6))
        raiz.add_widget(scroll)
        raiz.add_widget(self.lbl_ganancia)
        raiz.add_widget(self.lbl_error)
        raiz.add_widget(botones)
        self.content = raiz

    def _ajustar_stock(self, delta):
        try:
            n = int(self.campos["stock"].text or 0)
        except ValueError:
            n = 0
        self.campos["stock"].text = str(max(0, n + delta))

    def _calc_ganancia(self):
        try:
            costo = parsear_precio(self.campos["costo"].text)
            publico = parsear_precio(self.campos["publico"].text)
        except ValueError:
            self.lbl_ganancia.text = "Ganancia por unidad: —"
            self.lbl_ganancia.color = (0.7, 0.7, 0.7, 1)
            return
        g = publico - costo
        pct = f" ({g / costo * 100:.0f}% sobre costo)" if costo > 0 else ""
        self.lbl_ganancia.text = f"Ganancia por unidad: {fmt_dinero(g)}{pct}"
        self.lbl_ganancia.color = hexc("#5be08f") if g >= 0 else hexc("#ff7b7b")

    def _error(self, msg):
        self.lbl_error.text = msg

    def _cerrar(self):
        self.app.dialogos -= 1
        self.dismiss()
        Clock.schedule_once(self.app.reenfocar, 0.2)

    def _cancelar(self):
        if self.on_cancel:
            self.on_cancel()
        self._cerrar()

    def _eliminar(self):
        def hacer():
            self.on_delete()
            self._cerrar()
        confirmar("Eliminar", "¿Eliminar definitivamente este producto?", hacer)

    def _guardar(self):
        v = {k: w.text.strip() for k, w in self.campos.items()}
        if not v["codigo"]:
            return self._error("Ingresa el código de barras.")
        if not v["marca"] or not v["nombre"]:
            return self._error("Marca y nombre son obligatorios.")
        try:
            v["stock"] = int(v["stock"] or 0)
            if v["stock"] < 0:
                raise ValueError
        except ValueError:
            return self._error("El stock debe ser un entero ≥ 0.")
        try:
            v["costo"] = parsear_precio(v["costo"])
            v["publico"] = parsear_precio(v["publico"])
        except ValueError:
            return self._error("Los precios deben ser números ≥ 0 (ej. 125.50).")
        if v["publico"] < v["costo"] and not self._aviso_neg:
            self._aviso_neg = True
            return self._error("El precio público es menor al costo (ganancia negativa).\n"
                               "Pulsa Guardar otra vez para confirmar.")
        if v["vencimiento"]:
            try:
                datetime.strptime(v["vencimiento"], "%Y-%m-%d")
            except ValueError:
                return self._error("Fecha inválida. Usa AAAA-MM-DD (ej. 2027-05-31).")
        err = self.on_save(v)
        if err:
            return self._error(err)
        self._cerrar()


# --------------------------------------------------------------------------
# Interfaz (KV)
# --------------------------------------------------------------------------
KV = """
#:import dp kivy.metrics.dp

<ColorLabel>:
    size_hint_y: None
    text_size: self.width - dp(16), None
    height: max(self.texture_size[1] + dp(20), dp(48))
    halign: 'center'
    valign: 'middle'
    bold: True
    color: 0.2, 0.2, 0.2, 1
    canvas.before:
        Color:
            rgba: self.bg_color
        Rectangle:
            pos: self.pos
            size: self.size

<ProductoRow>:
    orientation: 'horizontal'
    padding: dp(4)
    spacing: dp(6)
    canvas.before:
        Color:
            rgba: root.bg
        Rectangle:
            pos: self.pos
            size: self.size
    InfoArea:
        text: root.texto
        markup: True
        font_size: '13sp'
        color: 0.1, 0.1, 0.1, 1
        halign: 'left'
        valign: 'middle'
        text_size: self.size
        on_release: app.editar_producto(root.codigo)
    Button:
        text: '-'
        font_size: '34sp'
        bold: True
        size_hint_x: None
        width: dp(62)
        background_normal: ''
        background_color: 0.85, 0.33, 0.31, 1
        on_release: app.cambiar_stock(root.codigo, -1)
    Label:
        text: str(int(root.stock))
        font_size: '24sp'
        bold: True
        size_hint_x: None
        width: dp(50)
        color: 0.1, 0.1, 0.1, 1
    Button:
        text: '+'
        font_size: '34sp'
        bold: True
        size_hint_x: None
        width: dp(62)
        background_normal: ''
        background_color: 0.18, 0.62, 0.36, 1
        on_release: app.cambiar_stock(root.codigo, 1)

<Root>:
    orientation: 'vertical'
    BoxLayout:
        orientation: 'vertical'
        ScreenManager:
            id: sm
            Screen:
                name: 'scan'
                BoxLayout:
                    orientation: 'vertical'
                    padding: dp(8)
                    spacing: dp(8)
                    BoxLayout:
                        size_hint_y: None
                        height: dp(68)
                        spacing: dp(8)
                        ToggleButton:
                            id: btn_entrada
                            text: 'ENTRADA  (+1)'
                            group: 'modo'
                            state: 'down'
                            allow_no_selection: False
                            font_size: '17sp'
                            bold: True
                            background_normal: ''
                            background_down: ''
                            background_color: (0.18, 0.62, 0.36, 1) if self.state == 'down' else (0.72, 0.72, 0.72, 1)
                            on_state: app.actualizar_modo()
                        ToggleButton:
                            id: btn_salida
                            text: 'SALIDA  (-1)'
                            group: 'modo'
                            allow_no_selection: False
                            font_size: '17sp'
                            bold: True
                            background_normal: ''
                            background_down: ''
                            background_color: (0.85, 0.33, 0.31, 1) if self.state == 'down' else (0.72, 0.72, 0.72, 1)
                            on_state: app.actualizar_modo()
                    ColorLabel:
                        id: lbl_modo
                        font_size: '14sp'
                    BoxLayout:
                        size_hint_y: None
                        height: dp(56)
                        spacing: dp(6)
                        TextInput:
                            id: entry
                            hint_text: 'Escanea o escribe el código'
                            multiline: False
                            font_size: '20sp'
                            halign: 'center'
                            write_tab: False
                            text_validate_unfocus: False
                            on_text_validate: app.al_escanear()
                        Button:
                            text: 'OK'
                            font_size: '18sp'
                            bold: True
                            size_hint_x: None
                            width: dp(74)
                            on_release: app.al_escanear()
                    ColorLabel:
                        id: lbl_resultado
                        text: 'Listo para escanear...'
                        font_size: '15sp'
                    ColorLabel:
                        id: lbl_alerta
                        text: 'Sin alertas de vencimiento'
                        font_size: '16sp'
                        color: 0.45, 0.45, 0.45, 1
                    Label:
                        text: 'Últimas 10 acciones'
                        size_hint_y: None
                        height: dp(24)
                        bold: True
                        halign: 'left'
                        text_size: self.size
                        color: 0.2, 0.2, 0.2, 1
                    ScrollView:
                        GridLayout:
                            id: log_box
                            cols: 1
                            size_hint_y: None
                            height: self.minimum_height
                            spacing: dp(2)
            Screen:
                name: 'inv'
                BoxLayout:
                    orientation: 'vertical'
                    padding: dp(8)
                    spacing: dp(6)
                    BoxLayout:
                        size_hint_y: None
                        height: dp(48)
                        spacing: dp(6)
                        TextInput:
                            id: busqueda
                            hint_text: 'Buscar producto, marca, tono, código...'
                            multiline: False
                            font_size: '15sp'
                            write_tab: False
                            on_text: app.refrescar_inventario()
                        Button:
                            text: 'Limpiar'
                            size_hint_x: None
                            width: dp(80)
                            on_release: root.ids.busqueda.text = ''
                    RecycleView:
                        id: rv
                        viewclass: 'ProductoRow'
                        RecycleBoxLayout:
                            default_size: None, dp(100)
                            default_size_hint: 1, None
                            size_hint_y: None
                            height: self.minimum_height
                            orientation: 'vertical'
                            spacing: dp(4)
                    ColorLabel:
                        id: lbl_estado
                        font_size: '13sp'
                    GridLayout:
                        cols: 2
                        size_hint_y: None
                        height: dp(110)
                        spacing: dp(4)
                        Label:
                            id: tot_unidades
                            markup: True
                            halign: 'center'
                            color: 0.13, 0.13, 0.13, 1
                        Label:
                            id: tot_inversion
                            markup: True
                            halign: 'center'
                            color: 0.13, 0.13, 0.13, 1
                        Label:
                            id: tot_venta
                            markup: True
                            halign: 'center'
                            color: 0.13, 0.13, 0.13, 1
                        Label:
                            id: tot_ganancia
                            markup: True
                            halign: 'center'
                            color: 0.12, 0.48, 0.27, 1
                    Button:
                        text: 'NUEVO COSMÉTICO'
                        size_hint_y: None
                        height: dp(56)
                        font_size: '16sp'
                        bold: True
                        background_normal: ''
                        background_color: 0.12, 0.31, 0.61, 1
                        on_release: app.nuevo_producto()
        BoxLayout:
            size_hint_y: None
            height: dp(60)
            Button:
                text: 'ESCÁNER'
                font_size: '16sp'
                bold: True
                on_release: app.ir('scan')
            Button:
                text: 'INVENTARIO'
                font_size: '16sp'
                bold: True
                on_release: app.ir('inv')
"""


class Root(BoxLayout):
    pass


# --------------------------------------------------------------------------
# Aplicación principal
# --------------------------------------------------------------------------
class InventarioApp(App):
    title = "Inventario de Cosméticos"

    def build(self):
        Window.clearcolor = (0.96, 0.96, 0.96, 1)
        Window.softinput_mode = "resize"
        self.db = Database(os.path.join(self.user_data_dir, DB_NAME))
        self.dialogos = 0
        self._flash_ev = None
        Builder.load_string(KV)
        return Root()

    def on_start(self):
        self.actualizar_modo()
        self.refrescar_inventario()
        Clock.schedule_once(self.reenfocar, 0.3)

    # ---------------- Navegación ----------------
    def ir(self, pantalla):
        self.root.ids.sm.current = pantalla
        if pantalla == "inv":
            self.refrescar_inventario()
        else:
            Clock.schedule_once(self.reenfocar, 0.1)

    def reenfocar(self, *_):
        if self.root is None or self.dialogos > 0:
            return
        if self.root.ids.sm.current == "scan":
            self.root.ids.entry.focus = True

    # ---------------- Pestaña Escáner ----------------
    @property
    def modo(self):
        return "entrada" if self.root.ids.btn_entrada.state == "down" else "salida"

    def actualizar_modo(self):
        if self.root is None or "lbl_modo" not in self.root.ids:
            return
        lbl = self.root.ids.lbl_modo
        if self.modo == "entrada":
            lbl.text = "MODO ENTRADA: cada lectura SUMA 1 al stock"
            lbl.bg_color = hexc(COLOR_ENTRADA)
        else:
            lbl.text = "MODO SALIDA: cada lectura RESTA 1 al stock"
            lbl.bg_color = hexc(COLOR_SALIDA)
        lbl.color = (1, 1, 1, 1)
        Clock.schedule_once(self.reenfocar, 0.1)

    def al_escanear(self, *_):
        entry = self.root.ids.entry
        codigo = entry.text.strip()
        entry.text = ""
        if codigo:
            self.procesar_codigo(codigo)
        Clock.schedule_once(self.reenfocar, 0.15)

    def procesar_codigo(self, codigo):
        row = self.db.obtener(codigo)
        if row is None:
            self._alta_desde_escaner(codigo)
            return

        stock = row["cantidad_stock"]
        etiqueta = etiqueta_producto(row)
        self._mostrar_alerta_vencimiento(etiqueta, row["fecha_vencimiento"])

        if self.modo == "entrada":
            nuevo = stock + 1
            self.db.set_stock(codigo, nuevo)
            msg = f"Escaneado: {etiqueta} - Entrada - Stock Actual: {nuevo}"
            self.registrar(msg, "entrada")
            self._resultado(msg, COLOR_ENTRADA, "white")
            vibrar(50)
        else:
            if stock <= 0:
                msg = f"SIN STOCK: {etiqueta} - No se puede restar (Stock Actual: 0)"
                self.registrar(msg, "error")
                self._resultado(msg, "#a30000", "white")
                vibrar(250)
            else:
                nuevo = stock - 1
                self.db.set_stock(codigo, nuevo)
                msg = f"Escaneado: {etiqueta} - Salida - Stock Actual: {nuevo}"
                self.registrar(msg, "salida")
                self._resultado(msg, COLOR_SALIDA, "white")
                vibrar(50)
        self.refrescar_inventario()

    def _alta_desde_escaner(self, codigo):
        vibrar(150)
        self._resultado(f"Código nuevo: {codigo} - completa el registro", COLOR_AZUL, "white")

        def guardar(d):
            d["codigo"] = codigo
            self.db.insertar(d)
            etiqueta = etiqueta_dict(d)
            msg = f"Alta nueva: {etiqueta} - Stock inicial: {d['stock']}"
            self.registrar(msg, "alta")
            self._resultado(msg, COLOR_AZUL, "white")
            self._mostrar_alerta_vencimiento(etiqueta, d["vencimiento"])
            self.refrescar_inventario()
            return None

        def cancelar():
            self._resultado(f"Alta cancelada para el código {codigo}", COLOR_NEUTRO, "#333333")

        ProductoPopup(self, "Cosmético no registrado - Alta nueva",
                      {"codigo": codigo, "stock": 1}, True, guardar, None, cancelar).open()

    # ---------------- Avisos visuales ----------------
    def _resultado(self, texto, bg, fg):
        lbl = self.root.ids.lbl_resultado
        lbl.text = texto
        lbl.bg_color = hexc(bg)
        lbl.color = hexc(fg) if isinstance(fg, str) else fg

    def _mostrar_alerta_vencimiento(self, etiqueta, fecha):
        if self._flash_ev:
            self._flash_ev.cancel()
            self._flash_ev = None
        lbl = self.root.ids.lbl_alerta
        d = dias_para_vencer(fecha)
        if d is None or d > DIAS_ALERTA:
            lbl.text = "Sin alertas de vencimiento"
            lbl.bg_color = hexc(COLOR_NEUTRO)
            lbl.color = (0.45, 0.45, 0.45, 1)
            return
        if d < 0:
            texto = f"¡PRODUCTO VENCIDO! Venció el {fecha} (hace {-d} días)\n{etiqueta}"
            c1, c2 = hexc("#b00020"), hexc("#ff5c5c")
        elif d == 0:
            texto = f"¡VENCE HOY! ({fecha})\n{etiqueta}"
            c1, c2 = hexc("#e65100"), hexc("#ffb347")
        else:
            texto = f"PRÓXIMO A VENCER: faltan {d} días ({fecha})\n{etiqueta}"
            c1, c2 = hexc("#e65100"), hexc("#ffb347")
        lbl.text = texto
        lbl.color = (1, 1, 1, 1)
        vibrar(300)
        estado = {"n": 8}

        def parpadeo(dt):
            lbl.bg_color = c1 if estado["n"] % 2 == 0 else c2
            estado["n"] -= 1
            if estado["n"] < 0:
                lbl.bg_color = c1
                self._flash_ev = None
                return False

        lbl.bg_color = c1
        self._flash_ev = Clock.schedule_interval(parpadeo, 0.25)

    def registrar(self, texto, tag):
        colores = {"entrada": "#1e7a45", "salida": "#b23a36", "error": "#d00000",
                   "alta": COLOR_AZUL}
        hora = datetime.now().strftime("%H:%M:%S")
        lbl = Label(text=f"[b]{hora}[/b]  {esc(texto)}", markup=True, size_hint_y=None,
                    halign="left", valign="middle", font_size="12sp",
                    color=hexc(colores.get(tag, "#333333")))
        lbl.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
        lbl.bind(texture_size=lambda w, s: setattr(w, "height", s[1] + dp(8)))
        caja = self.root.ids.log_box
        caja.add_widget(lbl, index=len(caja.children))   # el más nuevo arriba
        while len(caja.children) > MAX_LOG:
            caja.remove_widget(caja.children[0])

    # ---------------- Pestaña Inventario ----------------
    def _fila(self, r):
        stock = r["cantidad_stock"]
        costo = r["precio_costo"] or 0.0
        publico = r["precio_publico"] or 0.0
        d = dias_para_vencer(r["fecha_vencimiento"])
        if d is not None and d < 0:
            bg = hexc("#f8d7da")
        elif d is not None and d <= DIAS_ALERTA:
            bg = hexc("#fff3cd")
        elif stock == 0:
            bg = hexc("#e4e4e4")
        else:
            bg = [1, 1, 1, 1]
        sub = "  ·  ".join(x for x in (r["tono_color"], r["categoria"]) if x)
        texto = (f"[b]{esc(r['marca'] + ' ' + r['nombre_producto'])}[/b]\n"
                 f"{esc(sub)}\n"
                 f"Público {fmt_dinero(publico)}  |  Ganancia {fmt_dinero((publico - costo) * stock)}\n"
                 f"{esc(estado_vencimiento(r['fecha_vencimiento']))}  |  {esc(r['codigo_barras'])}")
        return {"codigo": r["codigo_barras"], "texto": texto, "stock": stock, "bg": bg}

    def refrescar_inventario(self, *_):
        if self.root is None or "rv" not in self.root.ids:
            return
        ids = self.root.ids
        filas = self.db.buscar(ids.busqueda.text)
        ids.rv.data = [self._fila(r) for r in filas]
        self._totales(filas)
        self._estado(f"{len(filas)} productos" + (" (filtrados)" if ids.busqueda.text.strip() else ""),
                     COLOR_NEUTRO, "#333333")

    def _totales(self, filas):
        ids = self.root.ids
        unidades = inversion = venta = 0
        for r in filas:
            s = r["cantidad_stock"]
            unidades += s
            inversion += (r["precio_costo"] or 0.0) * s
            venta += (r["precio_publico"] or 0.0) * s
        ganancia = venta - inversion
        ids.tot_unidades.text = f"Unidades\n[b][size=20sp]{unidades:,}[/size][/b]"
        ids.tot_inversion.text = f"Inversión (costo)\n[b][size=20sp]{fmt_dinero(inversion)}[/size][/b]"
        ids.tot_venta.text = f"Valor de venta\n[b][size=20sp]{fmt_dinero(venta)}[/size][/b]"
        ids.tot_ganancia.text = f"GANANCIA TOTAL\n[b][size=20sp]{fmt_dinero(ganancia)}[/size][/b]"
        ids.tot_ganancia.color = hexc("#1e7a45") if ganancia >= 0 else hexc("#b23a36")

    def _estado(self, texto, bg, fg):
        lbl = self.root.ids.lbl_estado
        lbl.text = texto
        lbl.bg_color = hexc(bg)
        lbl.color = hexc(fg)

    def cambiar_stock(self, codigo, delta):
        """Botones + / - de cada producto: un toque suma o resta 1."""
        row = self.db.obtener(codigo)
        if row is None:
            return
        etiqueta = etiqueta_producto(row)
        stock = row["cantidad_stock"]
        if delta < 0 and stock <= 0:
            msg = f"SIN STOCK: {etiqueta} - No se puede restar"
            self.registrar(msg, "error")
            self._estado(msg, "#a30000", "#ffffff")
            vibrar(250)
            return
        nuevo = stock + delta
        self.db.set_stock(codigo, nuevo)
        tipo = "entrada" if delta > 0 else "salida"
        msg = f"Manual: {etiqueta} - {'Entrada' if delta > 0 else 'Salida'} - Stock Actual: {nuevo}"
        self.registrar(msg, tipo)
        self._estado(msg, COLOR_ENTRADA if delta > 0 else COLOR_SALIDA, "#ffffff")
        vibrar(30)

        # Actualiza solo esa fila (no mueve el scroll) y los totales
        rv = self.root.ids.rv
        fila = self._fila(self.db.obtener(codigo))
        for item in rv.data:
            if item["codigo"] == codigo:
                item.update(fila)
                break
        rv.refresh_from_data()
        self._totales(self.db.buscar(self.root.ids.busqueda.text))

    @staticmethod
    def _datos_dialogo(r):
        return {"codigo": r["codigo_barras"], "marca": r["marca"], "nombre": r["nombre_producto"],
                "tono": r["tono_color"] or "", "categoria": r["categoria"] or CATEGORIAS[0],
                "stock": r["cantidad_stock"], "vencimiento": r["fecha_vencimiento"] or "",
                "costo": r["precio_costo"] or 0.0, "publico": r["precio_publico"] or 0.0}

    def nuevo_producto(self):
        def guardar(d):
            if self.db.obtener(d["codigo"]):
                return "Ya existe un producto con ese código de barras."
            self.db.insertar(d)
            self.registrar(f"Alta manual: {etiqueta_dict(d)} - Stock inicial: {d['stock']}", "alta")
            self.refrescar_inventario()
            return None

        ProductoPopup(self, "Nuevo cosmético", None, False, guardar).open()

    def editar_producto(self, codigo):
        r = self.db.obtener(codigo)
        if r is None:
            return

        def guardar(d):
            d["codigo"] = codigo
            self.db.actualizar(d)
            self.registrar(f"Editado: {etiqueta_dict(d)} - Stock: {d['stock']}", "alta")
            self.refrescar_inventario()
            return None

        def borrar():
            self.db.eliminar(codigo)
            self.registrar(f"Eliminado: {etiqueta_producto(r)}", "error")
            self.refrescar_inventario()

        ProductoPopup(self, "Editar cosmético", self._datos_dialogo(r), True,
                      guardar, borrar).open()


if __name__ == "__main__":
    InventarioApp().run()
