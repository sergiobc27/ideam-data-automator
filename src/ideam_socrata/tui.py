"""Interfaz de terminal (TUI) estilo app para IDEAM Data Automator.

Adaptación del asistente interactivo clásico (ideam_socrata.main) al estilo
Textual (cajas seleccionables, navegación por flechas, checkmarks, panel de
resumen en vivo), conservando logo CUC, aviso legal, las 21 variables y el
flujo de pasos. Se construye por etapas:
  Etapa 1 (esta): aviso legal + variables + departamentos + años + panel-resumen.
  Etapa 2: filtros avanzados (catálogo: zona, categoría, estación, ...).
  Etapa 3: motor de descarga (core.py en modo silencioso).

Lanzar con:  ideam-socrata tui
"""

from __future__ import annotations

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
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

# Paleta Universidad de la Costa (CUC)
ROJO = "#A3161A"
AMARILLO = "#FCD116"
GRIS = "#A5A5A5"

PRESENTACION = (
    "[bold]AUTOMATIZACIÓN INTELIGENTE PARA LA GESTIÓN VISUAL DE DATOS "
    "HÍDRICOS DEL IDEAM[/bold]\n"
    "Proyecto de Tesis de Pregrado – Ingeniería Civil\n\n"
    "Autor: Sergio Beltrán Coley\n"
    "Tutora: Ing. Carol Prada Sánchez   ·   Cotutor: Ing. Sebastián Quintero Merchán\n"
    "Universidad de la Costa – Barranquilla, Colombia"
)

AVISO_LEGAL = (
    "[bold]ACUERDO DE USO ACADÉMICO E INVESTIGATIVO[/bold]\n\n"
    "Al continuar, usted manifiesta estar de acuerdo con:\n"
    "  • El uso de los datos es exclusivamente para fines académicos e investigativos.\n"
    "  • La información proviene del IDEAM bajo la Política de Datos Abiertos de Colombia.\n"
    "  • El autor no se hace responsable del tratamiento posterior de la información.\n"
    "  • Se prohíbe el uso para fines comerciales no autorizados."
)


class ValuePicker(ModalScreen):
    """Selector multi-valor de un atributo del catálogo (carga en vivo)."""

    CSS = f"""
    ValuePicker {{ align: center middle; }}
    #vp {{ border: round {AMARILLO}; background: $surface; padding: 1 2; width: 70%; height: auto; max-height: 85%; }}
    #vp Button {{ margin: 1 1 0 0; }}
    """

    def __init__(self, etiqueta, col, filtros_dep, preseleccion):
        super().__init__()
        self.etiqueta, self.col, self.filtros_dep = etiqueta, col, filtros_dep
        self.preseleccion = set(preseleccion or [])

    def compose(self) -> ComposeResult:
        with Vertical(id="vp"):
            yield Static(f"[b]{self.etiqueta}[/b] — cargando opciones…", id="vp-tit")
            yield SelectionList(id="vp-list")
            with Horizontal():
                yield Button("Cancelar", id="vp-cancel")
                yield Button("Aceptar ✓", id="vp-ok", variant="primary")

    def on_mount(self) -> None:
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
        self.query_one("#vp-tit", Static).update(
            f"[b]{self.etiqueta}[/b] — Espacio marca ✓ · {len(vals)} opciones")

    @on(Button.Pressed, "#vp-ok")
    def _ok(self) -> None:
        self.dismiss(list(self.query_one("#vp-list", SelectionList).selected))

    @on(Button.Pressed, "#vp-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)


class FiltrosScreen(ModalScreen):
    """Menú de filtros avanzados: las 7 categorías + códigos manuales."""

    CSS = f"""
    FiltrosScreen {{ align: center middle; }}
    #fs {{ border: round {AMARILLO}; background: $surface; padding: 1 2; width: 80%; height: auto; max-height: 90%; }}
    #fs Button {{ width: 100%; margin: 0 0 1 0; }}
    #fs-volver {{ width: auto; }}
    """

    def __init__(self, filtros_dep):
        super().__init__()
        self.filtros_dep = filtros_dep

    @staticmethod
    def _lbl(etiqueta, n):
        return f"{etiqueta}" + (f"   ✓ {n}" if n else "")

    def compose(self) -> ComposeResult:
        with Vertical(id="fs"):
            yield Static("[b]Filtros avanzados[/b] · catálogo de estaciones (opcional)", classes="titulo")
            yield Static("Elige una categoría para filtrar; se combinan entre sí.", classes="pista")
            for etiqueta, col in ATRIBUTOS_AVANZADOS.items():
                n = len(self.app.avanzados.get(col, []))
                yield Button(self._lbl(etiqueta, n), id=f"attr-{col}")
            yield Label("Códigos de estación manuales (separados por coma):")
            yield Input(value=", ".join(sorted(self.app.codigos_manuales)), id="fs-codigos")
            yield Button("← Listo / Volver", id="fs-volver", variant="primary")

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


class IdeamTUI(App):
    TITLE = "IDEAM Data Automator"
    SUB_TITLE = "Asistente de descarga"

    CSS = f"""
    Screen {{ align: center top; }}
    #logo {{ color: {ROJO}; padding: 0; height: auto; }}
    #cuerpo {{ height: 1fr; }}
    .paso {{ border: round {AMARILLO}; padding: 1 2; margin: 1 2; height: auto; }}
    .legal {{ border: round {ROJO}; padding: 1 2; margin: 1 2; height: auto; }}
    .titulo {{ color: {AMARILLO}; text-style: bold; margin-bottom: 1; }}
    .pista {{ color: {GRIS}; }}
    .presentacion {{ color: {GRIS}; padding: 0 2; }}
    OptionList {{ height: auto; max-height: 18; }}
    SelectionList {{ height: auto; max-height: 18; }}
    Input {{ margin: 1 0; }}
    #fila-fechas {{ height: auto; }}
    #fila-fechas Vertical {{ width: 1fr; padding-right: 2; height: auto; }}
    #botones {{ height: auto; align: center middle; padding-top: 1; }}
    Button {{ margin: 0 1; }}
    #resumen {{ border: round {GRIS}; padding: 0 1; margin: 0 2; color: {GRIS}; height: auto; }}
    #estado {{ padding: 1 0; }}
    ProgressBar {{ margin: 1 0; }}
    """

    BINDINGS = [
        ("q", "quit", "Salir"),
        ("escape", "atras", "Atrás"),
        ("n", "reiniciar", "Nueva consulta"),
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

    # ---------- composición base ----------
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(id="resumen")
        yield VerticalScroll(id="cuerpo")
        yield Footer()

    def on_mount(self) -> None:
        self._render()

    # ---------- panel-resumen (siempre visible) ----------
    def _refrescar_resumen(self) -> None:
        var = self.sel_dataset["nombre"] if self.sel_dataset else "—"
        dep = ", ".join(self.sel_departamentos) if self.sel_departamentos else "—"
        anios = f"{self._anio_ini}–{self._anio_fin}" if self._anio_ini else "—"
        def marca(activo, hecho):
            return "[green]✔[/green]" if hecho else ("[yellow]➤[/yellow]" if activo else "·")
        linea = (
            f"{marca(self.paso==1, self.sel_dataset is not None)} Variable: [b]{var}[/b]   "
            f"{marca(self.paso==2, bool(self.sel_departamentos))} Deptos: [b]{dep}[/b]   "
            f"{marca(self.paso==3, bool(self._anio_ini))} Años: [b]{anios}[/b]"
        )
        self.query_one("#resumen", Static).update(linea)

    # ---------- navegación ----------
    def _render(self) -> None:
        self._refrescar_resumen()
        cuerpo = self.query_one("#cuerpo", VerticalScroll)
        cuerpo.remove_children()
        builder = {0: self._aviso, 1: self._variables, 2: self._departamentos,
                   3: self._anios, 4: self._descarga}[self.paso]
        cuerpo.mount(builder())
        foco = {1: "#lista-var", 2: "#lista-deptos", 3: "#f-ini"}.get(self.paso)
        if foco:
            self.call_after_refresh(lambda s=foco: self.query_one(s).focus())
        if self.paso == 3:
            self._detectar_anios()
        if self.paso == 4:
            self._descargar_worker()

    def action_atras(self) -> None:
        if 0 < self.paso < 4:
            self.paso -= 1
            self._render()

    def action_reiniciar(self) -> None:
        if self.paso == 4:
            self.paso, self.sel_dataset, self.sel_departamentos = 1, None, []
            self._inicio = self._fin = ""
            self._render()

    # ---------- paso 0: aviso legal + presentación ----------
    def _aviso(self) -> Vertical:
        return Vertical(
            Static(build_logo_text(), id="logo"),
            Static(PRESENTACION, classes="presentacion"),
            Static(AVISO_LEGAL, classes="legal"),
            Horizontal(
                Button("No acepto (salir)", id="rechazar"),
                Button("Acepto los términos →", id="aceptar", variant="primary"),
                id="botones",
            ),
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
    def _variables(self) -> Vertical:
        opciones = []
        for d in DATASETS_INFO:
            etiqueta = d["nombre"]
            if d.get("tipo") == "especial":
                etiqueta += "  [dim](especial)[/dim]"
            opciones.append(Option(etiqueta, id=d["id"]))
        return Vertical(
            Static("Paso 1 · Elige la variable a descargar", classes="titulo"),
            Static("↑↓ navegar · Enter elegir · (las 'especiales' se habilitan pronto)",
                   classes="pista"),
            OptionList(*opciones, id="lista-var"),
            classes="paso",
        )

    @on(OptionList.OptionSelected, "#lista-var")
    def _eligio_var(self, ev: OptionList.OptionSelected) -> None:
        dataset = next(d for d in DATASETS_INFO if d["id"] == ev.option_id)
        if dataset.get("tipo") != "estandar":
            self.notify("Las variables 'especiales' se habilitarán en la próxima etapa.",
                        severity="warning", timeout=6)
            return
        self.sel_dataset = dataset
        self.paso = 2
        self._render()

    # ---------- paso 2: departamentos ----------
    def _departamentos(self) -> Vertical:
        sels = [Selection(dep.title(), dep) for dep in DEPARTAMENTOS]
        return Vertical(
            Static(f"Paso 2 · Departamentos · {self.sel_dataset['nombre']}", classes="titulo"),
            Static("↑↓ navegar · Espacio marca ✓ · puedes elegir varios", classes="pista"),
            SelectionList(*sels, id="lista-deptos"),
            Horizontal(
                Button("← Atrás", id="atras"),
                Button("Filtros avanzados ⚙", id="filtros-av"),
                Button("Continuar →", id="cont-deptos", variant="primary"),
                id="botones",
            ),
            classes="paso",
        )

    def _filtro_dep_actual(self):
        """Construye el filtro de depto desde la selección actual (o None si vacía)."""
        sel = list(self.query_one("#lista-deptos", SelectionList).selected)
        if not sel:
            return None
        filtro, reemplazos, _ = build_department_filter(sel, MAPEO_DEPARTAMENTOS)
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
        self.paso = 3
        self._render()

    @on(Button.Pressed, "#atras")
    def _btn_atras(self) -> None:
        self.action_atras()

    # ---------- paso 3: rango de años ----------
    def _anios(self) -> Vertical:
        return Vertical(
            Static("Paso 3 · Rango de años", classes="titulo"),
            Static("Detectando años disponibles…", id="rango-info", classes="pista"),
            Horizontal(
                Vertical(Label("Año inicio:"), Input(placeholder="…", id="f-ini")),
                Vertical(Label("Año fin:"), Input(placeholder="…", id="f-fin")),
                id="fila-fechas",
            ),
            SelectionList(
                Selection("También exportar CSV (además de Parquet)", "csv", False),
                id="lista-opciones",
            ),
            Horizontal(
                Button("← Atrás", id="atras"),
                Button("Descargar ⬇", id="descargar", variant="primary"),
                id="botones",
            ),
            classes="paso",
        )

    @work(thread=True)
    def _detectar_anios(self) -> None:
        """Consulta min/max año del dataset y prerellena los campos."""
        from .config import CLIENT
        from .core import intentar
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
        self.call_from_thread(self._fijar_rango, gmin, gmax)

    def _fijar_rango(self, gmin: int, gmax: int) -> None:
        self.query_one("#rango-info", Static).update(
            f"Histórico disponible: [b]{gmin}–{gmax}[/b] · ajusta o deja así para todo")
        self.query_one("#f-ini", Input).value = str(gmin)
        self.query_one("#f-fin", Input).value = str(gmax)

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
            Static(f"Descargando {self.sel_dataset['nombre']}", classes="titulo"),
            ProgressBar(total=100, show_eta=True, id="barra"),
            Static("Iniciando…", id="estado"),
            classes="paso",
        )

    @work(thread=True, exclusive=True)
    def _descargar_worker(self) -> None:
        from .engine import construir_tareas, descargar, resolver_pool_estaciones

        def on_progress(hechos, total, filas):
            pct = int(hechos / total * 100) if total else 100
            self.call_from_thread(self._set_prog, pct, filas)

        try:
            col = self.sel_dataset["fecha_col"]
            pool = set(self.codigos_manuales)
            if any(self.avanzados.values()):
                self.call_from_thread(
                    self.query_one("#estado", Static).update, "Resolviendo estaciones por filtros…")
                pool |= resolver_pool_estaciones(self.filtros_base, self.avanzados)
            tareas = construir_tareas(
                self._anio_ini, self._anio_fin, self.filtros_base, pool, col)
            r = descargar(
                self.sel_dataset["id"], col, tareas, self.dict_reemplazo,
                self.sel_dataset["nombre"], include_csv=self._con_csv, on_progress=on_progress,
            )
            self.call_from_thread(self._ok, r)
        except Exception as exc:  # noqa: BLE001
            self.call_from_thread(self._err, f"Error: {exc}")

    def _set_prog(self, pct: int, filas: int) -> None:
        self.query_one("#barra", ProgressBar).update(progress=pct)
        self.query_one("#estado", Static).update(f"[{AMARILLO}]{filas:,} filas descargadas[/]")

    def _ok(self, r: dict) -> None:
        self.query_one("#barra", ProgressBar).update(progress=100)
        if r["rows"] == 0:
            msg = (f"[{AMARILLO}]Sin datos.[/] La consulta fue válida pero el IDEAM no tiene "
                   "registros de esa variable para ese departamento/periodo.")
        else:
            msg = (f"[{AMARILLO}]✓ Descarga completa[/]\nFilas: {r['rows']:,}  ·  "
                   f"{r['files_parquet']} parquet · {r['files_csv']} csv  ·  {r['seconds']}s\n"
                   f"Carpeta: {r['output_dir']}/")
        self.query_one("#estado", Static).update(msg + "\n\nPulsa N para otra consulta o Q para salir.")

    def _err(self, msg: str) -> None:
        self.query_one("#estado", Static).update(
            f"[{ROJO}]{msg}[/]\n\nPulsa N para reintentar o Q para salir.")


def run() -> None:
    IdeamTUI().run()


if __name__ == "__main__":
    run()
