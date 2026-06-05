from rich.text import Text
from rich.table import Table
from rich.panel import Panel
from rich.align import Align
from .config import console

def build_logo_text():
    """Construye el logo CUC como rich.Text reutilizable (consola y TUI)."""
    filas = [
        [("█", "#b60000"), ("█", "#b80000"), ("██", "#b60000"), ("████████████████████████", "#b80000"), ("███", "#b60000"), ("    ", "transparent"), ("█████████", "#b80000"), ("█", "#b60000"), ("█", "#b80000"), ("█", "#ba0000"), ("      ", "transparent"), ("█", "#b40000"), ("█", "#b80000"), ("█", "#b60000"), ("████████", "#b80000"), ("█", "#ba0000"), ("    ", "transparent"), ("█", "#b20000"), ("█", "#b40000"), ("█", "#b60000"), ("████████████████████████", "#b80000"), ("███", "#b60000"), ("█", "#b20000")],
        [("███████████████████████████████", "#b80000"), ("█", "#b40000"), ("  ", "transparent"), ("█", "#b60000"), ("███████████", "#b80000"), ("█", "#b60000"), ("█", "#b80000"), ("    ", "transparent"), ("█", "#b80000"), ("█", "#b60000"), ("██████████", "#b80000"), ("█", "#ba0000"), ("█", "#b60000"), ("  ", "transparent"), ("█", "#b40000"), ("███████████████████████████████", "#b80000")],
        [("█████████████████████████████", "#b80000"), ("█", "#b60000"), ("█", "#b80000"), ("█", "#ba0000"), (" ", "transparent"), ("█", "#b80000"), ("█", "#b40000"), ("███████████", "#b80000"), ("█", "#b60000"), ("█", "#b80000"), ("    ", "transparent"), ("█", "#b80000"), ("█", "#b60000"), ("███████████", "#b80000"), ("█", "#ba0000"), ("█", "#bd0000"), (" ", "transparent"), ("█", "#ba0000"), ("█", "#b80000"), ("█", "#b60000"), ("█████████████████████████████", "#b80000")],
        [("██████████████", "#b80000"), ("█", "#ba0000"), ("█", "#b80000"), ("█", "#ba0000"), ("████████████", "#b80000"), ("█", "#b60000"), ("█", "#b80000"), ("█", "#ba0000"), (" ", "transparent"), ("█", "#b80000"), ("█", "#b40000"), ("███████████", "#b80000"), ("█", "#b60000"), ("█", "#b80000"), ("    ", "transparent"), ("█", "#b80000"), ("█", "#b60000"), ("███████████", "#b80000"), ("█", "#ba0000"), ("█", "#bd0000"), (" ", "transparent"), ("█", "#ba0000"), ("█", "#b80000"), ("█", "#b60000"), ("████████████", "#b80000"), ("█", "#ba0000"), ("████████████████", "#b80000")],
        [("██████████", "#b80000"), ("█", "#ba0000"), ("██", "#b80000"), ("█", "#b60000"), ("   ", "transparent"), ("█", "#af0000"), ("█", "#b40000"), ("█", "#b60000"), ("█████████", "#b80000"), ("█", "#b60000"), ("█", "#b80000"), ("█", "#ba0000"), (" ", "transparent"), ("█", "#b80000"), ("█", "#b40000"), ("███████", "#b80000"), ("█", "#ba0000"), ("███", "#b80000"), ("█", "#b60000"), ("      ", "transparent"), ("██", "#b60000"), ("██", "#b80000"), ("█", "#ba0000"), ("███████", "#b80000"), ("█", "#ba0000"), ("█", "#bd0000"), (" ", "transparent"), ("█", "#ba0000"), ("█", "#b80000"), ("█", "#b60000"), ("█████████", "#b80000"), ("██", "#ba0000"), ("█", "#b60000"), ("   ", "transparent"), ("██", "#b40000"), ("█", "#b80000"), ("█", "#ba0000"), ("██████████", "#b80000")],
        [("█████████", "#b80000"), ("█", "#b60000"), ("█", "#ba0000"), ("         ", "transparent"), ("█", "#b80000"), ("█", "#b40000"), ("█", "#b60000"), ("█", "#b80000"), ("█", "#ba0000"), ("█████", "#b80000"), ("█", "#b60000"), ("█", "#b40000"), (" ", "transparent"), ("█", "#b80000"), ("█", "#b40000"), ("█████████", "#b80000"), ("█", "#b40000"), ("          ", "transparent"), ("█", "#b60000"), ("█", "#b80000"), ("█", "#b60000"), ("███████", "#b80000"), ("█", "#ba0000"), ("█", "#bd0000"), (" ", "transparent"), ("█", "#ba0000"), ("█", "#b80000"), ("█", "#b60000"), ("███████", "#b80000"), ("█", "#b60000"), ("█", "#b20000"), ("         ", "transparent"), ("██", "#ba0000"), ("█", "#b60000"), ("██████", "#b80000"), ("█", "#b60000"), ("█", "#b80000")],
        [("████████", "#b80000"), ("█", "#b40000"), ("             ", "transparent"), ("█", "#b60000"), ("█", "#b80000"), ("█", "#b60000"), ("███", "#b80000"), ("█", "#b60000"), ("█", "#ba0000"), ("█", "#b80000"), ("  ", "transparent"), ("█", "#b80000"), ("█", "#b40000"), ("████████", "#b80000"), ("█", "#ba0000"), ("             ", "transparent"), ("█", "#b80000"), ("█", "#b60000"), ("██████", "#b80000"), ("█", "#ba0000"), ("█", "#bd0000"), (" ", "transparent"), ("█", "#ba0000"), ("█", "#b80000"), ("█", "#b60000"), ("████", "#b80000"), ("█", "#ba0000"), ("█", "#b80000"), ("█", "#b60000"), ("             ", "transparent"), ("█", "#bb0000"), ("█", "#b80000"), ("█", "#b60000"), ("████", "#b80000"), ("█", "#b60000"), ("█", "#b10000")],
        [("███████", "#b80000"), ("█", "#ba0000"), ("                         ", "transparent"), ("█", "#b80000"), ("█", "#b40000"), ("████████", "#b80000"), ("              ", "transparent"), ("████████", "#b80000"), ("█", "#ba0000"), ("█", "#bd0000"), (" ", "transparent"), ("█", "#ba0000"), ("█", "#b80000"), ("█", "#b60000"), ("████", "#b80000"), ("█", "#b60000"), ("█", "#b80000"), ("█", "#ba0000"), ("                      ", "transparent")],
        [("███████", "#b80000"), ("█", "#b60000"), ("                         ", "transparent"), ("█", "#b80000"), ("█", "#b40000"), ("██████", "#b80000"), ("█", "#b60000"), ("█", "#b80000"), ("              ", "transparent"), ("█", "#b60000"), ("███████", "#b80000"), ("█", "#ba0000"), ("█", "#bd0000"), (" ", "transparent"), ("█", "#ba0000"), ("█", "#b80000"), ("█", "#b60000"), ("█████", "#b80000"), ("█", "#b60000"), ("█", "#b40000"), ("                      ", "transparent")],
        [("██████", "#b80000"), ("█", "#ba0000"), ("█", "#b80000"), ("█", "#b60000"), ("             ", "transparent"), ("█", "#b60000"), ("██", "#ba0000"), ("███", "#b60000"), ("█", "#b40000"), ("█", "#b60000"), ("   ", "transparent"), ("█", "#b80000"), ("█", "#b40000"), ("████████", "#b80000"), ("█", "#b60000"), ("             ", "transparent"), ("█", "#b80000"), ("█", "#b60000"), ("██████", "#b80000"), ("█", "#ba0000"), ("█", "#bd0000"), (" ", "transparent"), ("█", "#ba0000"), ("█", "#b80000"), ("█", "#b60000"), ("████", "#b80000"), ("█", "#ba0000"), ("█", "#b60000"), ("█", "#b80000"), ("             ", "transparent"), ("██", "#b80000"), ("█████", "#b60000"), ("█", "#b40000"), ("█", "#b10000")],
        [("██████████", "#b80000"), ("          ", "transparent"), ("█", "#b60000"), ("██", "#b80000"), ("█", "#b60000"), ("██████", "#b80000"), ("██", "#b60000"), (" ", "transparent"), ("█", "#b80000"), ("█", "#b40000"), ("█████████", "#b80000"), ("█", "#b60000"), ("          ", "transparent"), ("█", "#b80000"), ("█", "#ba0000"), ("████████", "#b80000"), ("█", "#ba0000"), ("█", "#bd0000"), (" ", "transparent"), ("█", "#ba0000"), ("█", "#b80000"), ("█", "#b60000"), ("███████", "#b80000"), ("██", "#b60000"), ("          ", "transparent"), ("███", "#b80000"), ("█", "#ba0000"), ("████", "#b80000"), ("█", "#ba0000"), ("█", "#b80000")],
        [("████████████", "#b80000"), ("█", "#b60000"), ("     ", "transparent"), ("█", "#b80000"), ("█", "#ba0000"), ("█", "#b60000"), ("████████", "#b80000"), ("█", "#b60000"), ("█", "#b80000"), ("█", "#ba0000"), (" ", "transparent"), ("█", "#b80000"), ("█", "#b40000"), ("███████", "#b80000"), ("█", "#ba0000"), ("███", "#b80000"), ("██", "#b60000"), ("    ", "transparent"), ("█", "#b80000"), ("█", "#ba0000"), ("███", "#b80000"), ("█", "#ba0000"), ("███████", "#b80000"), ("█", "#ba0000"), ("█", "#bd0000"), (" ", "transparent"), ("█", "#ba0000"), ("█", "#b80000"), ("█", "#b60000"), ("██████████", "#b80000"), ("█", "#ba0000"), ("     ", "transparent"), ("█", "#ba0000"), ("█", "#b60000"), ("███████████", "#b80000")],
        [("█████████████████████████████", "#b80000"), ("█", "#b60000"), ("█", "#b80000"), ("█", "#ba0000"), (" ", "transparent"), ("█", "#b80000"), ("█", "#b40000"), ("██████████████████████████████", "#b80000"), ("█", "#ba0000"), ("█", "#bd0000"), (" ", "transparent"), ("█", "#ba0000"), ("█", "#b80000"), ("█", "#b60000"), ("█████████████████████████████", "#b80000")],
        [("█████████████████████████████", "#b80000"), ("█", "#b60000"), ("█", "#b80000"), ("█", "#ba0000"), (" ", "transparent"), ("█", "#b80000"), ("█", "#b40000"), ("██████████████████████████████", "#b80000"), ("█", "#ba0000"), ("█", "#bd0000"), (" ", "transparent"), ("█", "#ba0000"), ("█", "#b80000"), ("█", "#b60000"), ("█████████████████████████████", "#b80000")],
        [("███████████████████████████████", "#b80000"), ("█", "#b40000"), ("  ", "transparent"), ("█", "#b60000"), ("█████████████████████████████", "#b80000"), ("█", "#ba0000"), ("█", "#b80000"), ("  ", "transparent"), ("█", "#b40000"), ("███████████████████████████████", "#b80000")],
        [("█", "#b40000"), ("█████████████████████████████", "#b80000"), ("█", "#b20000"), ("    ", "transparent"), ("██", "#b60000"), ("█", "#b80000"), ("█", "#ba0000"), ("██████████████████████", "#b80000"), ("█", "#ba0000"), ("███", "#b80000"), ("    ", "transparent"), ("█", "#b60000"), ("█", "#b80000"), ("██", "#ba0000"), ("█████████████████████████", "#b80000"), ("█", "#ba0000"), ("█", "#b80000")],
    ]
    img_text = Text(no_wrap=True, overflow="crop")
    for row_data in filas:
        for c, clr in row_data:
            # 'transparent' no es color válido en Textual; los espacios van sin estilo.
            img_text.append(c, style=None if clr == "transparent" else clr)
        img_text.append("\n")
    return img_text


def mostrar_logo():
    """Renderiza el logo CUC centrado en consola."""
    console.print(Align.center(build_logo_text()))

def espera_estetica(mensaje: str, spinner_type: str = "dots", tiempo: float = 0.4):
    """Muestra una animación corta para mejorar la fluidez visual."""
    import time
    with console.status(f"[s_bold]{mensaje}[/s_bold]", spinner=spinner_type):
        time.sleep(tiempo)

def mostrar_menu_opciones(titulo: str, opciones: list):
    """Muestra un menú numerado centrado."""
    table = Table(title=f"[p_bold]{titulo}[/p_bold]", show_header=False, border_style="borde")
    table.add_column("ID", style="s_bold", justify="right")
    table.add_column("Opción", style="t_bold")
    
    for i, opc in enumerate(opciones):
        table.add_row(str(i+1), opc)
    
    console.print(Align.center(table))

def mostrar_tabla_opciones(titulo: str, lista_opciones: list):
    """Muestra una tabla de 3 columnas centrada con opción de regreso incluida."""
    table = Table(title=f"[p_bold]{titulo}[/p_bold]", style="primario", show_lines=True)
    table.add_column("ID", style="s_bold", justify="right")
    table.add_column("Nombre", style="t_bold")
    table.add_column("ID", style="s_bold", justify="right")
    table.add_column("Nombre", style="t_bold")
    table.add_column("ID", style="s_bold", justify="right")
    table.add_column("Nombre", style="t_bold")
    
    for i in range(0, len(lista_opciones), 3):
        c1_id = f"{i+1}"
        c1_val = lista_opciones[i]
        
        c2_id = f"{i+2}" if i+1 < len(lista_opciones) else ""
        c2_val = lista_opciones[i+1] if i+1 < len(lista_opciones) else ""
        
        c3_id = f"{i+3}" if i+2 < len(lista_opciones) else ""
        c3_val = lista_opciones[i+2] if i+2 < len(lista_opciones) else ""
        
        table.add_row(c1_id, c1_val, c2_id, c2_val, c3_id, c3_val)
    
    table.add_row("0", "REGRESAR / CANCELAR", "", "", "", "", style="p_bold")
    console.print(Align.center(table))

def mostrar_tabla_simple(titulo: str, lista_opciones: list):
    """Muestra la lista de variables centrada."""
    table = Table(title=f"[p_bold]{titulo}[/p_bold]", style="primario")
    table.add_column("ID", style="s_bold", justify="right")
    table.add_column("Variable Climática / Hidrológica", style="t_bold")
    for i, opc in enumerate(lista_opciones):
        table.add_row(str(i+1), opc['nombre'])
    
    console.print(Align.center(table))

def extraer_ids_seleccionados(sel: str, lista_opciones: list) -> list:
    indices = [int(x.strip()) - 1 for x in sel.split(",") if x.strip().isdigit() and int(x.strip()) != 0]
    return [lista_opciones[i] for i in indices if 0 <= i < len(lista_opciones)]

def mostrar_panel_resumen(estado, paso_actual: int):
    """Muestra el resumen de búsqueda dinámico con indicadores de progreso."""
    res = estado["resumen"]
    table = Table(show_header=True, header_style="t_bold", border_style="borde", expand=True)
    table.add_column("PASO", style="bold", width=25)
    table.add_column("ESTADO / SELECCIÓN", style="texto_oscuro")
    
    # Lógica de colores e iconos
    # Paso 0: Variable (Siempre completado al llegar aquí)
    table.add_row("[bold green]✔ Variable Seleccionada[/bold green]", f"[bold white]{res.get('variable', 'N/A')}[/bold white]")
    
    # Paso 1: Departamentos
    if paso_actual == 1:
        table.add_row("[s_bold]➤ 1. Departamentos[/s_bold]", "[blink s_bold]Esperando selección...[/blink s_bold]")
    else:
        table.add_row("[bold green]✔ 1. Departamentos[/bold green]", f"[green]{res.get('deps', 'Todos')}[/green]")

    # Paso 2: Filtros Avanzados
    if paso_actual == 2:
        table.add_row("[s_bold]➤ 2. Filtros Especializados[/s_bold]", "[blink s_bold]Configurando filtros...[/blink s_bold]")
    elif paso_actual > 2:
        av = res.get("avanzados", {})
        text_av = " | ".join([f"{k}: {', '.join(v)}" for k, v in av.items()]) if av else "Ninguno"
        table.add_row("[bold green]✔ 2. Filtros Especializados[/bold green]", f"[green]{text_av}[/green]")

    # Paso 3: Rango de Años
    if paso_actual == 3:
        table.add_row("[s_bold]➤ 3. Temporalidad[/s_bold]", "[blink s_bold]Calculando años...[/blink s_bold]")
    elif paso_actual > 3:
        anios = f"{estado.get('anio_ini')} a {estado.get('anio_fin')}"
        table.add_row("[bold green]✔ 3. Temporalidad[/bold green]", f"[green]{anios}[/green]")

    # Paso 4: Descarga (Solo se muestra cuando llegamos al final)
    if paso_actual == 4:
        table.add_row("[s_bold]➤ 4. Preparación Final[/s_bold]", "[s_bold]Listo para descargar[/s_bold]")

    console.print(Align.center(Panel(table, title="[p_bold]PROGRESO DE LA CONFIGURACIÓN[/p_bold]", border_style="primario", expand=False)))
