"""Interfaz de terminal (TUI) estilo app para IDEAM Data Automator.

Construida con Textual (los autores de rich). Ofrece la experiencia tipo
Claude Code: cajas seleccionables, navegacion con flechas, marcado con
checkmarks y actualizacion en vivo, conservando la paleta de la Universidad
de la Costa. Usa el motor `batch.download` por debajo (modo quiet + callback).

Lanzar con:  ideam-socrata tui
"""

from __future__ import annotations

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
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

from .config import DATASETS_INFO, MAPEO_DEPARTAMENTOS

DATASETS_ESTANDAR = [d for d in DATASETS_INFO if d.get("tipo") == "estandar"]
DEPARTAMENTOS = sorted(MAPEO_DEPARTAMENTOS)

# Paleta Universidad de la Costa (CUC)
ROJO = "#A3161A"
AMARILLO = "#FCD116"
GRIS = "#A5A5A5"

BANNER = r"""
 ___ ____  _____ _    __  __
|_ _|  _ \| ____| |  |  \/  |   Data Automator
 | || | | |  _| | |  | |\/| |   Datos hidrometeorologicos del IDEAM
 | || |_| | |___| |__| |  | |   Universidad de la Costa
|___|____/|_____|_____|_|  |_|
"""


class IdeamTUI(App):
    TITLE = "IDEAM Data Automator"
    SUB_TITLE = "Asistente de descarga"

    CSS = f"""
    Screen {{ align: center top; }}
    #banner {{ color: {ROJO}; text-style: bold; padding: 0 1; }}
    .paso {{ border: round {AMARILLO}; padding: 1 2; margin: 1 2; height: auto; }}
    .titulo {{ color: {AMARILLO}; text-style: bold; margin-bottom: 1; }}
    .pista {{ color: {GRIS}; }}
    OptionList {{ height: auto; max-height: 16; }}
    SelectionList {{ height: auto; max-height: 18; }}
    Input {{ margin: 1 0; }}
    #fila-fechas {{ height: auto; }}
    #fila-fechas Vertical {{ width: 1fr; padding-right: 2; height: auto; }}
    #botones {{ height: auto; align: center middle; padding-top: 1; }}
    Button {{ margin: 0 1; }}
    #resumen {{ color: {GRIS}; padding: 0 2; }}
    ProgressBar {{ margin: 1 0; }}
    #estado {{ padding: 1 0; }}
    """

    BINDINGS = [
        ("q", "quit", "Salir"),
        ("escape", "atras", "Atrás"),
        ("n", "reiniciar", "Nueva descarga"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.paso = 0
        self.sel_dataset: dict | None = None
        self.sel_departamentos: list[str] = []
        self._inicio = self._fin = ""
        self._con_csv = False
        self._engine = "rapido"

    # ---------- composición base ----------
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(BANNER, id="banner")
        yield VerticalScroll(id="cuerpo")
        yield Footer()

    def on_mount(self) -> None:
        self._render_paso()

    # ---------- navegación ----------
    def _render_paso(self) -> None:
        cuerpo = self.query_one("#cuerpo", VerticalScroll)
        cuerpo.remove_children()
        builders = {
            0: self._paso_dataset,
            1: self._paso_departamentos,
            2: self._paso_opciones,
            3: self._paso_descarga,
        }
        cuerpo.mount(builders[self.paso]())
        # foco automatico al control principal de cada paso (mejor navegacion)
        foco = {0: "#lista-dataset", 1: "#lista-deptos", 2: "#f-inicio"}.get(self.paso)
        if foco:
            self.call_after_refresh(lambda sel=foco: self.query_one(sel).focus())
        if self.paso == 3:
            self._descargar_worker()

    def action_atras(self) -> None:
        if 0 < self.paso < 3:
            self.paso -= 1
            self._render_paso()

    def action_reiniciar(self) -> None:
        if self.paso == 3:
            self.paso = 0
            self.sel_dataset = None
            self.sel_departamentos = []
            self._render_paso()

    # ---------- paso 1: dataset ----------
    def _paso_dataset(self) -> Vertical:
        opciones = [
            Option(f"{d['nombre']}  ·  {d['id']}", id=d["id"]) for d in DATASETS_ESTANDAR
        ]
        return Vertical(
            Static("Paso 1 · Elige la variable a descargar", classes="titulo"),
            Static("↑↓ para navegar · Enter para elegir", classes="pista"),
            OptionList(*opciones, id="lista-dataset"),
            classes="paso",
        )

    @on(OptionList.OptionSelected, "#lista-dataset")
    def _eligio_dataset(self, ev: OptionList.OptionSelected) -> None:
        self.sel_dataset = next(d for d in DATASETS_ESTANDAR if d["id"] == ev.option_id)
        self.paso = 1
        self._render_paso()

    # ---------- paso 2: departamentos ----------
    def _paso_departamentos(self) -> Vertical:
        selecciones = [Selection(dep.title(), dep) for dep in DEPARTAMENTOS]
        return Vertical(
            Static(f"Paso 2 · Departamentos · {self.sel_dataset['nombre']}", classes="titulo"),
            Static("↑↓ navegar · Espacio para marcar ✓ · puedes elegir varios", classes="pista"),
            SelectionList(*selecciones, id="lista-deptos"),
            Horizontal(
                Button("← Atrás", id="atras"),
                Button("Continuar →", id="cont-deptos", variant="primary"),
                id="botones",
            ),
            classes="paso",
        )

    @on(Button.Pressed, "#cont-deptos")
    def _continuar_deptos(self) -> None:
        seleccion = self.query_one("#lista-deptos", SelectionList).selected
        if not seleccion:
            self.notify("Marca al menos un departamento con Espacio.", severity="warning")
            return
        self.sel_departamentos = list(seleccion)
        self.paso = 2
        self._render_paso()

    @on(Button.Pressed, "#atras")
    def _boton_atras(self) -> None:
        self.action_atras()

    # ---------- paso 3: fechas y opciones ----------
    def _paso_opciones(self) -> Vertical:
        return Vertical(
            Static("Paso 3 · Rango de fechas y formato", classes="titulo"),
            Static("Tab para cambiar de campo · formato YYYY-MM-DD", classes="pista"),
            Horizontal(
                Vertical(Label("Desde:"), Input(placeholder="2020-01-01", id="f-inicio")),
                Vertical(Label("Hasta (exclusivo):"), Input(placeholder="2024-12-31", id="f-fin")),
                id="fila-fechas",
            ),
            Label("Opciones:"),
            SelectionList(
                Selection("También exportar CSV (además de Parquet)", "csv", False),
                Selection("Motor rápido (gzip, recomendado)", "rapido", True),
                id="lista-opciones",
            ),
            Horizontal(
                Button("← Atrás", id="atras"),
                Button("Descargar ⬇", id="descargar", variant="primary"),
                id="botones",
            ),
            classes="paso",
        )

    @on(Button.Pressed, "#descargar")
    def _iniciar_descarga(self) -> None:
        from .batch import _validar_fechas

        inicio = self.query_one("#f-inicio", Input).value.strip()
        fin = self.query_one("#f-fin", Input).value.strip()
        try:
            _validar_fechas(inicio, fin)
        except SystemExit as exc:
            self.notify(str(exc), severity="error", timeout=8)
            return
        opciones = self.query_one("#lista-opciones", SelectionList).selected
        self._inicio, self._fin = inicio, fin
        self._con_csv = "csv" in opciones
        self._engine = "rapido" if "rapido" in opciones else "soda"
        self.paso = 3
        self._render_paso()

    # ---------- paso 4: descarga en vivo ----------
    def _paso_descarga(self) -> Vertical:
        return Vertical(
            Static(f"Descargando {self.sel_dataset['nombre']}", classes="titulo"),
            Static(
                f"{', '.join(self.sel_departamentos)} · {self._inicio} → {self._fin} "
                f"· motor {self._engine}",
                id="resumen",
            ),
            ProgressBar(total=100, show_eta=True, id="barra"),
            Static("Iniciando…", id="estado"),
            classes="paso",
        )

    @work(thread=True, exclusive=True)
    def _descargar_worker(self) -> None:
        from .batch import download

        def on_progress(hechos, total, filas):
            pct = int(hechos / total * 100) if total else 100
            self.call_from_thread(self._set_progreso, pct, filas)

        try:
            resumen = download(
                dataset_id=self.sel_dataset["id"],
                departments=self.sel_departamentos,
                start_date=self._inicio,
                end_date=self._fin,
                include_csv=self._con_csv,
                engine=self._engine,
                quiet=True,
                on_progress=on_progress,
            )
            self.call_from_thread(self._descarga_ok, resumen)
        except SystemExit as exc:
            self.call_from_thread(self._descarga_error, str(exc))
        except Exception as exc:  # noqa: BLE001
            self.call_from_thread(self._descarga_error, f"Error inesperado: {exc}")

    def _set_progreso(self, pct: int, filas: int) -> None:
        self.query_one("#barra", ProgressBar).update(progress=pct)
        self.query_one("#estado", Static).update(f"[{AMARILLO}]{filas:,} filas descargadas[/]")

    def _descarga_ok(self, r: dict) -> None:
        self.query_one("#barra", ProgressBar).update(progress=100)
        if r["rows"] == 0:
            msg = (
                f"[{AMARILLO}]Sin datos.[/] La consulta fue válida pero el IDEAM no tiene "
                "registros de esa variable para ese departamento/periodo "
                "(p. ej. municipios sin estación).\n\nPulsa N para otra descarga o Q para salir."
            )
        else:
            msg = (
                f"[{AMARILLO}]✓ Descarga completa[/]\n"
                f"Filas únicas: {r['rows']:,}\n"
                f"Archivos: {r['files_parquet']} parquet · {r['files_csv']} csv\n"
                f"Carpeta: {r['output_dir']}/  ·  {r['seconds']}s\n\n"
                "Pulsa N para otra descarga o Q para salir."
            )
        self.query_one("#estado", Static).update(msg)

    def _descarga_error(self, msg: str) -> None:
        self.query_one("#estado", Static).update(
            f"[{ROJO}]{msg}[/]\n\nPulsa N para reintentar o Q para salir."
        )


def run() -> None:
    IdeamTUI().run()


if __name__ == "__main__":
    run()
