import os
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from rich.progress import Progress, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn
from rich.panel import Panel
from rich.live import Live
from rich.align import Align
from rich.table import Table
from rich.prompt import Prompt

# Importaciones locales
from .config import (
    console,
    CLIENT,
    LIMIT,
    MAX_WORKERS,
)
from .exporting import export_by_department_municipality
from .transform import deduplicate_observations, normalize_chunk

logger = logging.getLogger(__name__)

# DIRECTORIO DE DATOS
DATA_DIR = "data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

def intentar(func, descripcion, max_intentos=5):
    """Maneja reintentos con backoff exponencial para operaciones de red."""
    for i in range(max_intentos):
        try:
            return func()
        except Exception as e:
            error_str = str(e).lower()
            # Si es un error de límite de tasa (Rate Limit)
            if "429" in error_str or "too many requests" in error_str:
                espera = (i + 1) * 5  # Espera más larga para 429
                logger.warning("Limite de tasa detectado en %s. Esperando %ss...", descripcion, espera)
            else:
                espera = 2 ** i  # Backoff exponencial estándar: 1, 2, 4, 8...
            
            logger.exception("Error en %s (intento %s/%s)", descripcion, i + 1, max_intentos)
            
            if i == max_intentos - 1:
                console.print(f"[bold primario][!] Falló {descripcion} después de {max_intentos} intentos.[/bold primario]")
                return None
            
            time.sleep(espera)

def descargar_estandar_por_meses(dataset_id, col_fecha, tareas, dict_reemplazo, nombre_export, var_nombre):
    """Descarga datos usando multihilos por bloques de tiempo."""
    resultados = []
    t_inicio = time.time()
    
    progress = Progress(
        TextColumn("  [progress.description]{task.description}"),
        BarColumn(bar_width=None, pulse_style="secundario"),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TextColumn("• [bold secundario]{task.fields[filas]} filas brutas"),
        console=console,
        expand=True
    )
    
    with Live(Panel(progress, title="[bold primario] MOTOR DE EXTRACCIÓN PARALELA [/bold primario]", border_style="secundario"), console=console, refresh_per_second=10):
        main_task = progress.add_task(f"Descargando bloques...", total=len(tareas), filas=0)
        
        def bajar_bloque(anio, mes, filtros):
            f_mes = list(filtros)
            if anio and mes:
                f_mes.append(f"{col_fecha} >= '{anio}-{mes:02d}-01T00:00:00.000'")
                sig_anio, sig_mes = (anio, mes + 1) if mes < 12 else (anio + 1, 1)
                f_mes.append(f"{col_fecha} < '{sig_anio}-{sig_mes:02d}-01T00:00:00.000'")
            elif anio and not mes: # Cuando se agrupa por año
                f_mes.append(f"{col_fecha} >= '{anio}-01-01T00:00:00.000'")
                f_mes.append(f"{col_fecha} < '{anio+1}-01-01T00:00:00.000'")
            where_str = " AND ".join(f_mes) if f_mes else None
            
            all_data = []
            offset = 0
            while True:
                data = intentar(lambda: CLIENT.get(dataset_id, where=where_str, limit=LIMIT, offset=offset, order=":id"), var_nombre)
                if data is None:
                    return None # Fallo crítico real
                all_data.extend(data)
                if len(data) < LIMIT:
                    break
                offset += LIMIT
            return all_data

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_bloque = {executor.submit(bajar_bloque, t[0], t[1], t[2]): t for t in tareas}
            total_filas_brutas = 0
            for future in as_completed(future_to_bloque):
                data = future.result()
                if data is not None:
                    if data:
                        total_filas_brutas += len(data)
                        resultados.extend(data)
                else:
                    progress.print(f"[bold primario][!] Fallo crítico en descarga de bloque.[/bold primario]")
                    return
                progress.update(main_task, advance=1, filas=f"{total_filas_brutas:,}")

    if not resultados:
        console.print("[bold primario][!] No se obtuvieron resultados en el rango seleccionado.[/bold primario]")
        return

    with console.status("[bold secundario]Procesando y formateando datos finales...[/bold secundario]", spinner="dots12"):
        df_final = normalize_chunk(resultados, dataset_id, col_fecha, dict_reemplazo)
        filas_brutas = len(df_final)
        df_final, duplicados_eliminados = deduplicate_observations(df_final, col_fecha)
        filas_unificadas = len(df_final)

        duracion = (time.time() - t_inicio) / 60

    table_csv = Table(show_header=False, border_style="secundario")
    table_csv.add_row("1", "Sí, exportar copia a CSV")
    table_csv.add_row("2", "No, finalizar")
    console.print(Align.center(table_csv))
    opc_csv = Prompt.ask("[bold secundario]¿Desea exportar una copia a CSV?[/bold secundario]", choices=["1", "2"], default="2", show_choices=False, show_default=False)

    outputs = export_by_department_municipality(
        df_final,
        var_nombre,
        base_dir=DATA_DIR,
        include_csv=opc_csv == "1",
    )
    total_csv = sum(len(output["csv"]) for output in outputs)

    resumen_descarga = (
        f"[bold secundario]PROCESO FINALIZADO CON ÉXITO[/bold secundario]\n\n"
        f"[texto]Filas descargadas (brutas): {filas_brutas:,}\n"
        f"Filas únicas (procesadas): {filas_unificadas:,}\n"
        f"Duplicados eliminados: {duplicados_eliminados:,}\n\n"
        f"Archivos Parquet generados: {len(outputs):,}\n"
        f"Archivos CSV generados: {total_csv:,}\n"
        f"Tiempo total: {duracion:.2f} Minutos[/texto]"
    )
    console.print("\n")
    console.print(Align.center(Panel(resumen_descarga, border_style="secundario", expand=False, padding=(1, 2))))
    console.print("\n")

    console.print(Align.center(Panel(f"[bold exito]✔ EXPORTACIÓN EXITOSA[/bold exito]\n[texto]Carpetas generadas bajo: {DATA_DIR}[/texto]", border_style="exito", expand=False)))

def descargar_especial_directo(dataset_id, nombre_export, var_nombre, filtros_lista):
    """Descarga datos en paralelo con gestión de hilos optimizada."""
    resultados = []
    t_inicio = time.time()
    
    with console.status(f"[bold secundario]Descargando dataset: {var_nombre}...[/bold secundario]", spinner="arrow3"):
        for f in filtros_lista:
            where_str = " AND ".join(f) if f else None
            offset = 0
            while True:
                data = intentar(lambda: CLIENT.get(dataset_id, where=where_str, limit=LIMIT, offset=offset, order=":id"), var_nombre)
                if data is None:
                    # Fallo definitivo de un bloque: cancelar TODO en vez de
                    # exportar resultados parciales como si fueran completos.
                    console.print(
                        f"[bold #A3161A][!] Falló la descarga de {var_nombre} tras varios "
                        "reintentos. No se exporta nada para evitar datos incompletos; "
                        "intente de nuevo más tarde.[/bold #A3161A]"
                    )
                    return
                if data: resultados.extend(data)
                if len(data) < LIMIT: break
                offset += LIMIT

    if resultados:
        df = normalize_chunk(resultados, dataset_id, "fechaobservacion")
        duracion = (time.time() - t_inicio) / 60

        table_csv = Table(show_header=False, border_style="secundario")
        table_csv.add_row("1", "Sí, exportar copia a CSV")
        table_csv.add_row("2", "No, finalizar")
        console.print(Align.center(table_csv))
        export_csv = Prompt.ask("[bold #FCD116]¿Exportar CSV?[/bold #FCD116]", choices=["1", "2"], default="2", show_choices=False, show_default=False) == "1"
        outputs = export_by_department_municipality(df, var_nombre, base_dir=DATA_DIR, include_csv=export_csv)
        total_csv = sum(len(output["csv"]) for output in outputs)
        
        console.print(Panel(
            f"[bold secundario]DESCARGA ESPECIAL COMPLETADA[/bold secundario]\n"
            f"[texto]Variable: [bold]{var_nombre}[/bold]\n"
            f"Registros: [bold]{len(df):,}[/bold]\n"
            f"Tiempo: [bold]{duracion:.1f} Minutos[/bold]\n"
            f"Archivos Parquet: [bold secundario]{len(outputs):,}[/bold secundario]\n"
            f"Archivos CSV: [bold secundario]{total_csv:,}[/bold secundario][/texto]",
            border_style="exito", title="[bold exito] ÉXITO [/bold exito]"
        ))
    else:
        console.print("[bold #A3161A][!] No se encontraron datos.[/bold #A3161A]")
