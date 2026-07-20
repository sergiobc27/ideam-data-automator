"""Interfaz de terminal (TUI) estilo app para IDEAM Data Automator.

Adaptación del asistente interactivo clásico (ideam_socrata.main) al estilo
Textual (cajas seleccionables, navegación por flechas, checkmarks, panel de
resumen en vivo), conservando logo CUC, aviso legal, las 21 variables y el
flujo de pasos.

Look moderno (rediseño 2026): tema propio CUC oscuro, cajas con relieve y
título en el borde, barra de pasos (stepper), barra de descarga con gradiente,
transiciones con deslizamiento, micro-interacciones en botones y validación en
vivo del rango de años.

Lanzar con:  ideam-socrata tui
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.color import Gradient
from textual.command import Hit, Hits, Provider
from textual.content import Content
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    LoadingIndicator,
    OptionList,
    ProgressBar,
    SelectionList,
    Static,
)
from textual.widgets.option_list import Option
from textual.widgets.selection_list import Selection

from .engine import ATRIBUTOS_AVANZADOS

from .config import DATASETS_INFO, MAPEO_DEPARTAMENTOS
from .query_validation import build_department_filter
from .ui import build_logo_text

DATASETS_ESTANDAR = [d for d in DATASETS_INFO if d.get("tipo") == "estandar"]
DEPARTAMENTOS = sorted(MAPEO_DEPARTAMENTOS)

# Paleta Universidad de la Costa (CUC) — colores de marca.
ROJO = "#A3161A"
AMARILLO = "#FCD116"
GRIS = "#A5A5A5"

# Tema propio de la app: rojo y amarillo CUC como ACENTOS sobre un fondo
# gris-azulado oscuro (no negro puro). Registrarlo deja que todo el CSS y la
# marcación usen variables ($accent, $primary, $surface…), así cambiar la paleta
# es un solo sitio y se gana modo claro/oscuro gratis.
CUC_THEME = Theme(
    name="cuc",
    primary=ROJO,            # identidad institucional / errores
    secondary="#C9A227",
    accent=AMARILLO,         # foco, acción, paso activo, progreso
    background="#1a1a22",    # fondo neutro (no negro puro: cansa menos la vista)
    surface="#26262f",       # superficie de las cajas (relieve sobre el fondo)
    panel="#313140",         # zonas destacadas (listas, resumen)
    success="#a6e3a1",
    warning="#f9e2af",
    error=ROJO,
    dark=True,
    # Regla de marca: el AMARILLO marca "dónde actuar ahora" (foco, cursor de
    # lista), el rojo queda reservado para identidad/errores. Por defecto Textual
    # deriva el borde de foco y el cursor de lista del primary (rojo) → se
    # redirigen al amarillo para que el foco no se lea como alerta.
    variables={
        "border": AMARILLO,
        "block-cursor-foreground": "#1a1a22",
        "block-cursor-background": AMARILLO,
        "block-cursor-text-style": "bold",
        # variante "desenfocada" (lista sin foco): tinte amarillo tenue, no rojo
        "block-cursor-blurred-foreground": "#e0e0e8",
        "block-cursor-blurred-background": f"{AMARILLO} 20%",
        "block-cursor-blurred-text-style": "none",
        "input-selection-background": f"{AMARILLO} 35%",
    },
)

PRESENTACION = (
    "[bold]Automatización inteligente para la gestión visual de datos "
    "hídricos del IDEAM[/bold]\n"
    "Proyecto de Tesis de Pregrado · Ingeniería Civil\n\n"
    "Autor: Sergio Beltrán Coley\n"
    "Tutora: Ing. Carol Prada Sánchez   ·   Cotutor: Ing. Sebastián Quintero Merchán\n"
    "Universidad de la Costa · Barranquilla, Colombia"
)

AVISO_LEGAL = (
    "[bold]Acuerdo de uso académico e investigativo[/bold]\n\n"
    "Al continuar, usted manifiesta estar de acuerdo con:\n"
    "  • El uso de los datos es exclusivamente para fines académicos e investigativos.\n"
    "  • La información proviene del IDEAM bajo la Política de Datos Abiertos de Colombia.\n"
    "  • El autor no se hace responsable del tratamiento posterior de la información.\n"
    "  • Se prohíbe el uso para fines comerciales no autorizados."
)


# Aviso permanente sobre el alcance de la fuente (datos.gov.co / Socrata).
# La API pública solo expone telemetría de estaciones AUTOMÁTICAS; los históricos
# de estaciones convencionales (muchas zonas, pre-2016) viven solo en DHIME.
AVISO_DHIME = (
    "ℹ La fuente publica datos de estaciones automáticas; los históricos de "
    "estaciones convencionales (en muchas zonas, anteriores a ~2016) solo están "
    "en el portal DHIME del IDEAM."
)


def emoji_de(nombre: str) -> str:
    """Emoji representativo según la variable."""
    n = nombre.lower()
    if "precipita" in n:
        return "🌧️"
    if "viento" in n:
        return "💨"
    if "mar" in n:
        return "🌊"
    if "presión" in n or "presion" in n:
        return "🧭"
    if "humedad" in n:
        return "💧"
    if "temperatura" in n:
        return "🌡️"
    if "rio" in n or "río" in n:
        return "🏞️"
    if "aire" in n:
        return "🌫️"
    if "agua" in n:
        return "🚰"
    if "zonifica" in n:
        return "🗺️"
    if "normales" in n:
        return "📈"
    if "gases" in n or "invernadero" in n:
        return "☁️"
    if "escorrent" in n:
        return "💦"
    if "estaciones" in n:
        return "📍"
    return "📊"


# Banda de colores para el efecto shimmer (oscuro → MUY brillante → oscuro).
_SHIMMER = ["#4a4a4a", "#6b6b6b", "#8a6d0e", "#C9A227", "#FCD116",
            "#FFF3A0", "#FCD116", "#C9A227", "#8a6d0e", "#6b6b6b", "#4a4a4a"]
_SHIMMER_BASE = "#4a4a4a"


class Shimmer(Static):
    """Texto con un brillo en movimiento (la 'firma' animada de la app)."""

    def __init__(self, texto: str = "", **kw) -> None:
        super().__init__(**kw)
        self._texto = texto
        self._pos = 0
        self._timer = None

    def set_texto(self, texto: str) -> None:
        self._texto = texto
        self._pos = 0

    def on_mount(self) -> None:
        self._timer = self.set_interval(0.09, self._tick)

    def on_unmount(self) -> None:
        # No dejar el timer corriendo cuando el widget desaparece de pantalla.
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _tick(self) -> None:
        if not self._texto:  # nada que pintar: no repintar en vano
            return
        self._pos = (self._pos + 1) % (len(self._texto) + len(_SHIMMER) + 6)
        self.update(self._render())

    def detener(self, texto_final: str | None = None) -> None:
        """Detiene la animación y deja un texto fijo."""
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        if texto_final is not None:
            self.update(texto_final)

    def _render(self) -> Content:
        t = Text()
        centro = self._pos
        for i, ch in enumerate(self._texto):
            dist = i - centro
            if 0 <= dist < len(_SHIMMER):
                color = _SHIMMER[dist]
            else:
                color = _SHIMMER[0]
            t.append(ch, style=color)
        return Content.from_rich_text(t)


class StepBar(Static):
    """Barra de progreso de pasos (píldoras) sobre el asistente.

    Paso activo resaltado en amarillo, pasos hechos con ✓ verde, futuros
    apagados. Reactiva: basta con asignar ``stepper.paso = n``.
    """

    paso = reactive(0)
    _PASOS = ("Variable", "Deptos", "Años", "Descarga")

    def watch_paso(self, paso: int) -> None:
        if paso < 1:
            self.update("")  # en el aviso legal aún no hay pasos
            return
        pildoras = []
        for i, nombre in enumerate(self._PASOS, start=1):
            if i < paso:
                pildoras.append(f"[$success bold] ✓ {nombre} [/]")
            elif i == paso:
                pildoras.append(f"[bold $background on $accent] {i} · {nombre} [/]")
            else:
                pildoras.append(f"[$text-disabled] {i} · {nombre} [/]")
        self.update("  [$text-disabled]→[/]  ".join(pildoras))


class ValuePicker(ModalScreen):
    """Selector multi-valor de un atributo del catálogo (carga en vivo)."""

    CSS = """
    ValuePicker { align: center middle; }
    #vp { border: round $accent; background: $surface; padding: 1 2; width: 70%; height: auto; max-height: 85%; }
    #vp Button { margin: 1 1 0 0; transition: background 120ms; }
    #vp Button:hover { background: $accent 20%; text-style: bold; }
    #vp-list { background: $panel; }
    """

    def __init__(self, etiqueta, col, filtros_dep, preseleccion):
        super().__init__()
        self.etiqueta, self.col, self.filtros_dep = etiqueta, col, filtros_dep
        self.preseleccion = set(preseleccion or [])

    def compose(self) -> ComposeResult:
        with Vertical(id="vp"):
            yield Static(f"[$accent bold]{self.etiqueta}[/] · cargando opciones…", id="vp-tit")
            yield SelectionList(id="vp-list")
            with Horizontal():
                yield Button("Cancelar", id="vp-cancel")
                yield Button("Aceptar ✓", id="vp-ok", variant="success")

    def on_mount(self) -> None:
        # spinner nativo mientras llega el catálogo (en vez del shimmer casero)
        self.query_one("#vp-list", SelectionList).loading = True
        self._cargar()

    @work(thread=True)
    def _cargar(self) -> None:
        from .engine import catalogo_valores
        try:
            vals = catalogo_valores(self.col, self.filtros_dep)
        except Exception:  # noqa: BLE001
            vals = []
        self.app.call_from_thread(self._poblar, vals)

    def _poblar(self, vals) -> None:
        sl = self.query_one("#vp-list", SelectionList)
        for v in vals:
            sl.add_option(Selection(v, v, v in self.preseleccion))
        sl.loading = False
        self.query_one("#vp-tit", Static).update(
            f"[$accent bold]{self.etiqueta}[/] · Espacio marca ✓ · {len(vals)} opciones")

    @on(Button.Pressed, "#vp-ok")
    def _ok(self) -> None:
        self.dismiss(list(self.query_one("#vp-list", SelectionList).selected))

    @on(Button.Pressed, "#vp-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)


class FiltrosScreen(ModalScreen):
    """Menú de filtros avanzados: las 7 categorías + códigos manuales."""

    CSS = """
    FiltrosScreen { align: center middle; }
    #fs { border: round $accent; background: $surface; padding: 1 2; width: 80%; height: auto; max-height: 90%; }
    #fs Button { width: 100%; margin: 0 0 1 0; transition: background 120ms; }
    #fs Button:hover { background: $accent 20%; text-style: bold; }
    #fs-volver { width: auto; }
    """

    def __init__(self, filtros_dep):
        super().__init__()
        self.filtros_dep = filtros_dep

    @staticmethod
    def _lbl(etiqueta, n):
        return f"{etiqueta}" + (f"   ✓ {n}" if n else "")

    def compose(self) -> ComposeResult:
        with Vertical(id="fs"):
            yield Static("[$accent bold]Filtros avanzados[/] · catálogo de estaciones (opcional)")
            yield Static("Elige una categoría para filtrar; se combinan entre sí.", classes="pista")
            for etiqueta, col in ATRIBUTOS_AVANZADOS.items():
                n = len(self.app.avanzados.get(col, []))
                yield Button(self._lbl(etiqueta, n), id=f"attr-{col}")
            yield Label("Códigos de estación manuales (separados por coma):")
            yield Input(value=", ".join(sorted(self.app.codigos_manuales)), id="fs-codigos")
            yield Button("← Listo / Volver", id="fs-volver", variant="success")

    @on(Button.Pressed)
    def _click(self, ev: Button.Pressed) -> None:
        bid = ev.button.id or ""
        if bid.startswith("attr-"):
            col = bid[5:]
            etiqueta = next(e for e, c in ATRIBUTOS_AVANZADOS.items() if c == col)
            boton = ev.button

            def cb(res, col=col, etiqueta=etiqueta, boton=boton):
                if res is not None:
                    self.app.avanzados[col] = res
                    boton.label = self._lbl(etiqueta, len(res))

            self.app.push_screen(
                ValuePicker(etiqueta, col, self.filtros_dep, self.app.avanzados.get(col, [])), cb)
        elif bid == "fs-volver":
            txt = self.query_one("#fs-codigos", Input).value
            self.app.codigos_manuales = {c.strip() for c in txt.split(",") if c.strip()}
            self.dismiss()


class ComandosIdeam(Provider):
    """Comandos propios para el command palette (Ctrl+P), además de los del
    sistema (cambiar tema, salir). Búsqueda difusa: escribe 'carp' y aparece."""

    @property
    def _comandos(self):
        app = self.app
        return [
            ("Nueva consulta", "Reinicia el asistente desde el inicio", app.action_reiniciar),
            ("Abrir carpeta de descargas", "Abre la carpeta donde se guardan los datos",
             app.action_abrir_carpeta),
            ("Atrás", "Vuelve al paso anterior", app.action_atras),
            ("Salir", "Cierra la aplicación", app.action_quit),
        ]

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for nombre, ayuda, accion in self._comandos:
            score = matcher.match(nombre)
            if score > 0:
                yield Hit(score, matcher.highlight(nombre), accion, help=ayuda)


class IdeamTUI(App):
    TITLE = "IDEAM Data Automator"
    SUB_TITLE = "Asistente de descarga"
    COMMANDS = App.COMMANDS | {ComandosIdeam}

    CSS = """
    Screen { align: center top; background: $background; }
    #logo { color: $primary; padding: 0; height: auto; text-align: center; }
    #tagline { text-align: center; text-style: bold; padding: 1 0 0 0; height: auto; }
    #stepper { width: 100%; height: auto; content-align: center middle; padding: 1 0 0 0; }
    #cuerpo { height: 1fr; align: center top; }

    /* Cada paso es una 'tarjeta' que flota sobre el fondo, con el título en el borde. */
    .paso {
        background: $surface;
        border: round $accent;
        border-title-color: $accent;
        border-title-style: bold;
        border-subtitle-color: $text-muted;
        padding: 1 2; margin: 1 2; height: auto; max-width: 112;
    }
    .legal { border: round $primary; background: $panel; padding: 1 2; margin: 1 0; height: auto; }
    .pista { color: $text-muted; }
    .presentacion { color: $text-muted; padding: 0 2; text-align: center; }

    OptionList { height: auto; max-height: 18; background: $panel; }
    SelectionList { height: auto; max-height: 18; background: $panel; }
    Input { margin: 1 0; }
    Input.error { border: tall $error; }
    #fila-fechas { height: auto; }
    #fila-fechas Vertical { width: 1fr; padding-right: 2; height: auto; }
    #botones { height: auto; align: center middle; padding-top: 1; }

    /* Micro-interacciones: los botones reaccionan al mouse y al foco de teclado. */
    Button { margin: 0 1; transition: background 120ms, color 120ms; }
    Button:hover { background: $accent 20%; text-style: bold; }
    Button:focus { background: $accent 30%; text-style: bold; }

    #resumen { padding: 0 1; margin: 0 2; color: $text-muted; height: auto; max-width: 112; content-align: center middle; }
    #estado { padding: 1 0; }
    #rango-load { height: 1; }
    ProgressBar { margin: 1 0; }
    """

    BINDINGS = [
        ("q", "quit", "Salir"),
        ("escape", "atras", "Atrás"),
        ("n", "reiniciar", "Nueva consulta"),
        ("o", "abrir_carpeta", "Abrir carpeta"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.paso = 0  # 0=aviso legal, 1=variable, 2=deptos, 3=años, 4=descarga
        self.sel_dataset: dict | None = None
        self.sel_departamentos: list[str] = []
        self._anio_ini = self._anio_fin = ""
        self._con_csv = False
        # filtros avanzados
        self.filtros_base: list[str] = []
        self.dict_reemplazo: dict = {}
        self.avanzados: dict[str, list[str]] = {}
        self.codigos_manuales: set[str] = set()
        self._ultimo_output: str | None = None  # carpeta de la última descarga

    def action_abrir_carpeta(self) -> None:
        """Abre la carpeta de descargas en el explorador (o muestra la ruta)."""
        from .config import DOWNLOAD_DIR
        destino = Path(self._ultimo_output or DOWNLOAD_DIR)
        try:
            destino.mkdir(parents=True, exist_ok=True)
            if hasattr(os, "startfile"):  # Windows
                os.startfile(destino)  # noqa: S606
                self.notify(f"Abriendo {destino}")
            else:
                self.notify(f"Carpeta de descargas: {destino}", timeout=8)
        except Exception as exc:  # noqa: BLE001
            self.notify(f"No se pudo abrir: {exc}", severity="warning")

    # ---------- composición base ----------
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield StepBar(id="stepper")
        yield Static(id="resumen")
        yield VerticalScroll(id="cuerpo")
        yield Footer()

    def on_mount(self) -> None:
        self.register_theme(CUC_THEME)
        self.theme = "cuc"
        self._render()

    # ---------- panel-resumen (siempre visible) ----------
    def _refrescar_resumen(self) -> None:
        self.query_one("#stepper", StepBar).paso = self.paso
        var = self.sel_dataset["nombre"] if self.sel_dataset else "—"
        dep = ", ".join(self.sel_departamentos) if self.sel_departamentos else "—"
        anios = f"{self._anio_ini}–{self._anio_fin}" if self._anio_ini else "—"

        def marca(activo, hecho):
            if hecho:
                return "[$success]✔[/]"
            return "[$accent]➤[/]" if activo else "[$text-disabled]·[/]"

        linea = (
            f"{marca(self.paso==1, self.sel_dataset is not None)} Variable: [b]{var}[/b]   "
            f"{marca(self.paso==2, bool(self.sel_departamentos))} Deptos: [b]{dep}[/b]   "
            f"{marca(self.paso==3, bool(self._anio_ini))} Años: [b]{anios}[/b]"
        )
        self.query_one("#resumen", Static).update(linea)

    # ---------- navegación ----------
    def _titulo_paso(self) -> tuple[str, str]:
        """Título y subtítulo (van EN el borde de la tarjeta del paso)."""
        nombre = self.sel_dataset["nombre"] if self.sel_dataset else ""
        return {
            0: ("  IDEAM Data Automator  ", "  Acuerdo de uso académico  "),
            1: ("  Paso 1 · Elige la variable  ", "  escribe para filtrar · ↓ lista · Enter elige  "),
            2: (f"  Paso 2 · Departamentos · {nombre}  ", "  ↑↓ navegar · Espacio marca ✓ · varios  "),
            3: ("  Paso 3 · Rango de años  ", "  revisa el rango y pulsa Descargar  "),
            4: (f"  {emoji_de(nombre)} {nombre}  ", "  descargando…  "),
        }[self.paso]

    def _render(self) -> None:
        self._refrescar_resumen()
        cuerpo = self.query_one("#cuerpo", VerticalScroll)
        cuerpo.remove_children()
        builder = {0: self._aviso, 1: self._variables, 2: self._departamentos,
                   3: self._anios, 4: self._descarga}[self.paso]
        panel = builder()
        titulo, subtitulo = self._titulo_paso()
        panel.border_title = titulo
        panel.border_subtitle = subtitulo
        cuerpo.mount(panel)
        self._animar_entrada(panel)
        foco = {1: "#buscar-var", 2: "#lista-deptos", 3: "#f-ini"}.get(self.paso)
        if foco:
            self.call_after_refresh(lambda s=foco: self.query_one(s).focus())
        if self.paso == 3:
            self._detectar_anios()
        if self.paso == 4:
            self._descargar_worker()

    def _animar_entrada(self, panel) -> None:
        """Fundido suave al entrar cada paso."""
        panel.styles.opacity = 0.0
        panel.styles.animate("opacity", value=1.0, duration=0.28, easing="out_cubic")

    def action_atras(self) -> None:
        if not (0 < self.paso < 4):
            return
        if self.paso == 3 and not self._tiene_dep():
            self.paso = 1  # el dataset no tiene paso de departamentos
        else:
            self.paso -= 1
        self._render()

    def action_reiniciar(self) -> None:
        if self.paso == 4:
            self.paso, self.sel_dataset, self.sel_departamentos = 1, None, []
            self._anio_ini = self._anio_fin = ""
            self.filtros_base, self.dict_reemplazo = [], {}
            self.avanzados, self.codigos_manuales = {}, set()
            self._render()

    # ---------- paso 0: aviso legal + presentación ----------
    def _aviso(self) -> Vertical:
        rechazar = Button("No acepto (salir)", id="rechazar", variant="error")
        rechazar.tooltip = "Cierra el asistente sin descargar nada."
        aceptar = Button("Acepto los términos →", id="aceptar", variant="success")
        aceptar.tooltip = "Aceptas el uso académico e investigativo y entras al asistente."
        return Vertical(
            Static(Content.from_rich_text(build_logo_text()), id="logo"),
            Shimmer("» Descarga, valida y organiza datos hídricos del IDEAM, sin límites «",
                    id="tagline"),
            Static(PRESENTACION, classes="presentacion"),
            Static(AVISO_LEGAL, classes="legal"),
            Horizontal(rechazar, aceptar, id="botones"),
            classes="paso",
        )

    @on(Button.Pressed, "#aceptar")
    def _aceptar(self) -> None:
        self.paso = 1
        self._render()

    @on(Button.Pressed, "#rechazar")
    def _rechazar(self) -> None:
        self.exit(message="Acceso denegado: no se aceptaron los términos.")

    # ---------- paso 1: variable (las 21) ----------
    def _opciones_var(self, filtro: str = "") -> list[Option]:
        f = filtro.strip().lower()
        ops = []
        for d in DATASETS_INFO:
            if f and f not in d["nombre"].lower():
                continue
            etiqueta = f"{emoji_de(d['nombre'])}  {d['nombre']}"
            if d.get("tipo") == "especial":
                etiqueta += "  [dim](especial)[/dim]"
            ops.append(Option(etiqueta, id=d["id"]))
        return ops or [Option("[dim](sin coincidencias)[/dim]", id="__none__")]

    def _variables(self) -> Vertical:
        return Vertical(
            Input(placeholder="🔍 filtrar variables…", id="buscar-var"),
            OptionList(*self._opciones_var(), id="lista-var"),
            classes="paso",
        )

    @on(Input.Changed, "#buscar-var")
    def _filtrar_var(self, ev: Input.Changed) -> None:
        ol = self.query_one("#lista-var", OptionList)
        ol.clear_options()
        ol.add_options(self._opciones_var(ev.value))

    # --- ayudas de flujo: qué pasos aplican según el dataset ---
    def _tiene_dep(self) -> bool:
        d = self.sel_dataset or {}
        return d.get("tipo") == "estandar" or bool(d.get("dep_col"))

    def _tiene_anios(self) -> bool:
        d = self.sel_dataset or {}
        return d.get("tipo") == "estandar" or bool(d.get("fecha_real"))

    def _dep_col(self) -> str:
        return (self.sel_dataset or {}).get("dep_col", "departamento")

    @on(OptionList.OptionSelected, "#lista-var")
    def _eligio_var(self, ev: OptionList.OptionSelected) -> None:
        if ev.option_id == "__none__":
            return
        dataset = next(d for d in DATASETS_INFO if d["id"] == ev.option_id)
        self.sel_dataset = dataset
        # limpiar estado de la consulta anterior
        self.sel_departamentos = []
        self.filtros_base, self.dict_reemplazo = [], {}
        self.avanzados, self.codigos_manuales = {}, set()
        self._anio_ini = self._anio_fin = ""
        if self._tiene_dep():
            self.paso = 2
        elif self._tiene_anios():
            self.paso = 3
        else:
            self.paso = 4  # especial sin filtros: descarga directa
        self._render()

    # ---------- paso 2: departamentos ----------
    def _departamentos(self) -> Vertical:
        sels = [Selection(dep.title(), dep) for dep in DEPARTAMENTOS]
        b_atras = Button("← Atrás", id="atras")
        b_atras.tooltip = "Vuelve a elegir la variable."
        b_cont = Button("Continuar →", id="cont-deptos", variant="success")
        b_cont.tooltip = "Pasa al rango de años." if self._tiene_anios() else "Pasa a la descarga."
        botones = [b_atras]
        if self.sel_dataset.get("tipo") == "estandar":
            b_filtros = Button("Filtros avanzados ⚙", id="filtros-av")
            b_filtros.tooltip = "Afina por zona hidrográfica, categoría, estación, corriente… (opcional)."
            botones.append(b_filtros)
        botones.append(b_cont)
        return Vertical(
            SelectionList(*sels, id="lista-deptos"),
            Horizontal(*botones, id="botones"),
            classes="paso",
        )

    def _filtro_dep_actual(self):
        """Construye el filtro de depto desde la selección actual (o None si vacía)."""
        sel = list(self.query_one("#lista-deptos", SelectionList).selected)
        if not sel:
            return None
        filtro, reemplazos, _ = build_department_filter(sel, MAPEO_DEPARTAMENTOS)
        dep_col = self._dep_col()
        if dep_col != "departamento":
            # datasets especiales con otro nombre de columna geográfica
            filtro = filtro.replace("upper(departamento)", f"upper({dep_col})")
        self.sel_departamentos = sel
        self.filtros_base = [filtro]
        self.dict_reemplazo = reemplazos
        return [filtro]

    @on(Button.Pressed, "#filtros-av")
    def _abrir_filtros(self) -> None:
        fdep = self._filtro_dep_actual()
        if fdep is None:
            self.notify("Marca al menos un departamento antes de filtrar.", severity="warning")
            return
        self.push_screen(FiltrosScreen(fdep))

    @on(Button.Pressed, "#cont-deptos")
    def _cont_deptos(self) -> None:
        if self._filtro_dep_actual() is None:
            self.notify("Marca al menos un departamento con Espacio.", severity="warning")
            return
        self.paso = 3 if self._tiene_anios() else 4
        self._render()

    @on(Button.Pressed, "#atras")
    def _btn_atras(self) -> None:
        self.action_atras()

    # ---------- paso 3: rango de años ----------
    def _anios(self) -> Vertical:
        descargar = Button("Descargar ⬇", id="descargar", variant="success", disabled=True)
        descargar.tooltip = "Inicia la descarga con los filtros elegidos."
        return Vertical(
            LoadingIndicator(id="rango-load"),
            Static("", id="rango-info", classes="pista"),
            Horizontal(
                Vertical(Label("Año inicio:"), Input(placeholder="…", id="f-ini")),
                Vertical(Label("Año fin:"), Input(placeholder="…", id="f-fin")),
                id="fila-fechas",
            ),
            SelectionList(
                Selection("También exportar CSV (además de Parquet)", "csv", False),
                id="lista-opciones",
            ),
            Static(AVISO_DHIME, id="aviso-dhime", classes="pista"),
            Horizontal(
                self._con_tip(Button("← Atrás", id="atras"), "Vuelve a departamentos."),
                descargar,
                id="botones",
            ),
            classes="paso",
        )

    @staticmethod
    def _con_tip(boton: Button, texto: str) -> Button:
        boton.tooltip = texto
        return boton

    @work(thread=True)
    def _detectar_anios(self) -> None:
        """Consulta min/max año del dataset, y la cobertura real del filtro elegido."""
        from .config import CLIENT
        from .core import intentar
        from .engine import cobertura_filtro
        import re

        col = self.sel_dataset["fecha_col"]
        ds = self.sel_dataset["id"]
        try:
            rmin = intentar(lambda: CLIENT.get(ds, select=col, order=f"{col} ASC", limit=1), "min")
            rmax = intentar(lambda: CLIENT.get(ds, select=col, order=f"{col} DESC", limit=1), "max")
            gmin = int(re.search(r"\d{4}", str(rmin[0].get(col))).group())
            gmax = int(re.search(r"\d{4}", str(rmax[0].get(col))).group())
        except Exception:  # noqa: BLE001
            gmin, gmax = 2001, 2026
        # la cobertura usa el Catálogo Nacional de Estaciones: solo aplica a los estándar
        es_estandar = self.sel_dataset.get("tipo") == "estandar"
        cob = cobertura_filtro(ds, col, self.filtros_base) if (self.filtros_base and es_estandar) else {}
        self.call_from_thread(self._fijar_rango, gmin, gmax, cob)

    def _fijar_rango(self, gmin: int, gmax: int, cob: dict | None = None) -> None:
        linea = f"[$text-muted]Histórico del dataset: [b]{gmin}–{gmax}[/b][/]"
        cob = cob or {}
        partes = []
        if cob.get("estaciones") is not None:
            est = f"[b]{cob['estaciones']}[/b] estaciones en tu selección"
            if cob.get("activas") is not None:
                est += f" ([b]{cob['activas']}[/b] activas)"
            partes.append(est)
        if cob.get("ini"):
            partes.append(f"con datos de [b]{cob['ini']} → {cob['fin']}[/b]")
            # prerrellenar con el rango REAL del filtro, no el global
            gmin = max(gmin, int(cob["ini"][:4]))
            gmax = min(gmax, int(cob["fin"][:4]))
        if partes:
            linea += f"\n[$accent]Tu filtro:[/] [$text-muted]" + " · ".join(partes) + "[/]"
        # ya no estamos cargando: oculta el spinner y muestra la info
        self.query_one("#rango-load", LoadingIndicator).display = False
        self.query_one("#rango-info", Static).update(linea)
        self.query_one("#f-ini", Input).value = str(gmin)
        self.query_one("#f-fin", Input).value = str(gmax)
        # Si el inicio REAL del filtro es ≥2010, casi seguro es una estación
        # automática instalada entonces: refuerza el aviso con el año concreto.
        try:
            ini_anio = int(cob["ini"][:4]) if cob.get("ini") else None
        except (TypeError, ValueError):
            ini_anio = None
        if ini_anio is not None and ini_anio >= 2010:
            self.query_one("#aviso-dhime", Static).update(
                f"ℹ Tu zona solo tiene datos desde [b]{ini_anio}[/b]: su estación "
                "automática se instaló entonces. Los registros convencionales "
                "anteriores están solo en el portal DHIME del IDEAM."
            )

    # --- validación en vivo del rango de años ---
    @on(Input.Changed, "#f-ini")
    @on(Input.Changed, "#f-fin")
    def _revalidar_anios(self, _ev: Input.Changed | None = None) -> None:
        try:
            ini_w = self.query_one("#f-ini", Input)
            fin_w = self.query_one("#f-fin", Input)
            btn = self.query_one("#descargar", Button)
        except Exception:  # noqa: BLE001
            return  # aún no montado
        ok = True
        try:
            ini = int(ini_w.value.strip())
            fin = int(fin_w.value.strip())
            ok = 1900 <= ini <= fin <= 2100
        except ValueError:
            ok = False
        ini_w.set_class(not ok, "error")
        fin_w.set_class(not ok, "error")
        btn.disabled = not ok

    @on(Button.Pressed, "#descargar")
    def _iniciar(self) -> None:
        try:
            ini = int(self.query_one("#f-ini", Input).value.strip())
            fin = int(self.query_one("#f-fin", Input).value.strip())
        except ValueError:
            self.notify("Escribe años válidos (ej. 2015).", severity="warning")
            return
        if ini > fin:
            self.notify("El año inicio debe ser menor o igual al año fin.", severity="warning")
            return
        self._anio_ini, self._anio_fin = ini, fin
        self._con_csv = "csv" in self.query_one("#lista-opciones", SelectionList).selected
        self.paso = 4
        self._render()

    # ---------- paso 4: descarga ----------
    def _descarga(self) -> Vertical:
        return Vertical(
            ProgressBar(
                total=100, show_eta=True, id="barra",
                gradient=Gradient.from_colors(ROJO, "#C9A227", AMARILLO),
            ),
            Static("Iniciando…", id="estado"),
            classes="paso",
        )

    @work(thread=True, exclusive=True)
    def _descargar_worker(self) -> None:
        from .engine import construir_tareas, descargar, resolver_pool_estaciones

        t0 = time.time()

        def on_progress(hechos, total, filas):
            elapsed = max(time.time() - t0, 0.001)
            rate = filas / elapsed
            eta = (total - hechos) / hechos * elapsed if hechos else 0
            pct = int(hechos / total * 100) if total else 100
            self.call_from_thread(self._set_prog, pct, filas, hechos, total, rate, eta)

        try:
            # para especiales sin fecha-timestamp se descarga directo (sin ventanas)
            col = self.sel_dataset["fecha_col"] if self._tiene_anios() else None
            pool = set(self.codigos_manuales)
            if any(self.avanzados.values()):
                self.call_from_thread(
                    self.query_one("#estado", Static).update, "Resolviendo estaciones por filtros…")
                pool |= resolver_pool_estaciones(self.filtros_base, self.avanzados)
            tareas = construir_tareas(
                self._anio_ini, self._anio_fin, self.filtros_base, pool, col)
            query_info = {
                "Variable": self.sel_dataset["nombre"],
                "Departamentos": ", ".join(self.sel_departamentos) or "Todos",
            }
            if self._anio_ini:
                query_info["Años solicitados"] = f"{self._anio_ini}–{self._anio_fin}"
            avanzados_activos = {k: v for k, v in self.avanzados.items() if v}
            if avanzados_activos:
                query_info["Filtros avanzados"] = "; ".join(
                    f"{k}: {', '.join(v)}" for k, v in avanzados_activos.items())
            if self.codigos_manuales:
                query_info["Estaciones manuales"] = ", ".join(sorted(self.codigos_manuales))
            r = descargar(
                self.sel_dataset["id"], col, tareas, self.dict_reemplazo,
                self.sel_dataset["nombre"], include_csv=self._con_csv,
                on_progress=on_progress, query_info=query_info,
            )
            self.call_from_thread(self._ok, r)
        except Exception as exc:  # noqa: BLE001
            self.call_from_thread(self._err, f"Error: {exc}")

    def _set_prog(self, pct: int, filas: int, hechos: int = 0, total: int = 0,
                  rate: float = 0.0, eta: float = 0.0) -> None:
        self.query_one("#barra", ProgressBar).update(progress=pct)
        bloques = f"bloque [b]{hechos}/{total}[/b]" if total else ""
        vel = f"[$text-muted]·[/] [$accent]{rate:,.0f} filas/s[/]" if rate else ""
        falta = f"[$text-muted]· ~{self._fmt_dur(eta)} restante[/]" if eta else ""
        self.query_one("#estado", Static).update(
            f"[$accent]{filas:,}[/] filas  [$text-muted]{bloques}[/]  {vel} {falta}".strip())

    @staticmethod
    def _fmt_dur(seg: float) -> str:
        seg = int(seg)
        if seg < 60:
            return f"{seg}s"
        if seg < 3600:
            return f"{seg // 60}m {seg % 60}s"
        return f"{seg // 3600}h {(seg % 3600) // 60}m"

    def _ok(self, r: dict) -> None:
        self.query_one("#barra", ProgressBar).update(progress=100)
        if r["rows"] == 0:
            msg = ("[$warning]Sin datos.[/] La consulta fue válida pero el IDEAM no tiene "
                   "registros de esa variable para ese departamento/periodo.")
            self.notify("Consulta válida, pero sin registros para ese filtro.",
                        title="Sin datos", severity="warning")
        else:
            msg = (
                f"[$success bold]✓ ¡DESCARGA COMPLETA![/]\n\n"
                f"[$text-muted]Filas únicas:[/] [b]{r['rows']:,}[/b]"
                + (f"   ([$text-muted]{r['duplicates']:,} duplicados depurados[/])" if r.get("duplicates") else "")
                + f"\n[$text-muted]Archivos:[/] {r['files_parquet']} parquet · {r['files_csv']} csv\n"
                f"[$text-muted]Carpeta:[/] [b]{Path(r['output_dir']).resolve()}[/b]\n"
                + (f"[$text-muted]Resumen de cobertura:[/] {Path(r['report']).name}\n" if r.get("report") else "")
                + f"[$text-muted]Tiempo:[/] {r['seconds']}s"
            )
            self.notify(f"Descarga completa: {r['rows']:,} filas", title="¡Listo!",
                        severity="information")
        self._ultimo_output = r.get("output_dir")
        estado = self.query_one("#estado", Static)
        estado.update(
            msg + f"\n\n[$text-muted]Pulsa [b]O[/b] abrir carpeta · [b]N[/b] otra consulta · "
            f"[b]Q[/b] salir · [b]Ctrl+P[/b] comandos[/]")
        # revelado suave del bloque de resultados (momento de recompensa)
        estado.styles.opacity = 0.0
        estado.styles.animate("opacity", value=1.0, duration=0.4)

    def _err(self, msg: str) -> None:
        self.query_one("#estado", Static).update(
            f"[$error]{msg}[/]\n\nPulsa N para reintentar o Q para salir.")
        self.notify(msg, title="Error en la descarga", severity="error")


def run() -> None:
    IdeamTUI().run()


if __name__ == "__main__":
    run()
