"""
AUTOMATIZACIÓN INTELIGENTE PARA LA GESTIÓN VISUAL DE DATOS HÍDRICOS DEL IDEAM
Versión Dinámica: Consulta los metadatos (departamentos y años) directamente desde la API del gobierno.
Autor: Sergio Beltrán Coley
"""

# ==========================================
# IMPORTACIÓN DE LIBRERÍAS Y SUS FUNCIONES
# ==========================================
import csv              # Permite leer y escribir archivos estructurados por comas (como Excel plano).
import time             # Proporciona funciones relacionadas con el tiempo (cronómetros, pausas).
import calendar         # Utilizado para conocer propiedades del calendario (ej. cuántos días tiene febrero en un año bisiesto).
import requests         # Actúa como un "mensajero" que viaja a internet, hace solicitudes a páginas web y trae las respuestas.
import re               # Librería de Expresiones Regulares. Funciona como un filtro avanzado para buscar y reemplazar patrones de texto.
import sys              # Permite interactuar con el sistema operativo (ej. forzar el cierre del programa si el usuario lo desea).
from io import StringIO # Simula un archivo físico, pero lo mantiene en la memoria RAM (es como un bloc de notas invisible y ultrarrápido).
from pathlib import Path # Facilita la creación y manipulación de rutas de carpetas de forma segura en Windows, Mac o Linux.
from collections import defaultdict # Un diccionario inteligente que crea un espacio vacío automáticamente si se busca una llave que no existe.
from concurrent.futures import ThreadPoolExecutor # El "capataz" que permite dividir una tarea grande para que varios procesadores trabajen a la vez.
from tqdm import tqdm   # Genera la barra de progreso visual (la línea de carga) en la consola.

# -------------- CONFIGURACIÓN -----------------
# Token de acceso que identifica el programa ante los servidores del gobierno, aumentando el límite de descargas.
APP_TOKEN     = "SOCRATA_APP_TOKEN_REMOVED"
DOMAIN        = "www.datos.gov.co"
DATASET_ID    = "s54a-sgyg"
# Define la carpeta donde se guardará todo, construyendo la ruta relativa al lugar donde esté guardado este script.
CARPETA_BASE = Path(__file__).parent / "datos_hidricos"

# Parámetros de control de la API
LIMIT         = 50000 # Cantidad máxima de registros que el servidor permite pedir en una sola página.
MAX_WORKERS   = 30    # Cantidad de "trabajadores" simultáneos. Imagina 30 personas descargando un mes distinto al mismo tiempo.
TIMEOUT       = 120   # Tiempo máximo de paciencia (en segundos) antes de considerar que la página web se cayó.
REINTENTOS    = 3     # Oportunidades que tiene el programa para volver a intentar si el internet falla.
ESPERA_REINT  = 0     # Segundos que espera antes de intentar de nuevo.
PAUSA_API     = 0.1   # Un descanso microscópico entre peticiones para no saturar el servidor gubernamental y evitar bloqueos.
# ----------------------------------------------

# Construcción de los enlaces exactos donde viven los datos.
CSV_URL  = f"https://{DOMAIN}/resource/{DATASET_ID}.csv"
JSON_URL = f"https://{DOMAIN}/resource/{DATASET_ID}.json"

# Se abre una "Sesión". A diferencia de enviar mensajeros individuales, una sesión es como dejar una línea telefónica abierta, lo que hace el proceso más rápido.
SESSION = requests.Session()
# Se le pide al servidor que envíe los datos comprimidos (zip) para ahorrar internet y hacer la descarga más veloz.
SESSION.headers.update({"Accept-Encoding": "gzip"})

# ---------------- utilidades ------------------
def safe_text(t: str) -> str:
    """
    Limpia los nombres de los municipios para que el sistema operativo no arroje error al crear la carpeta.
    Ejemplo real: Si el municipio se llama "BOGOTÁ D.C.", el punto o caracteres raros podrían fallar. Esta función lo sanitiza.
    """
    return re.sub(r'[<>:"/\\|?*]', "_", t.strip())

def request_json(params: dict) -> list[dict]:
    """
    Solicita metadatos a la API y espera una respuesta estructurada en formato JSON (similar a un diccionario de Python).
    """
    for i in range(1, REINTENTOS + 1): # Intenta realizar la acción hasta el límite establecido.
        try:
            r = SESSION.get(JSON_URL, params=params, timeout=TIMEOUT) # Hace la petición.
            r.raise_for_status() # Verifica que la página no haya dado un error 404 (No encontrado) o 500 (Error de servidor).
            time.sleep(PAUSA_API)
            return r.json() # Traduce la respuesta a un formato legible para Python.
        except Exception as e:
            print(f"❌ {e}  (intento {i}/{REINTENTOS})")
            if i < REINTENTOS:
                time.sleep(ESPERA_REINT)
    raise RuntimeError("Se agotaron los reintentos")

def request_csv_text(params: dict) -> str | None:
    """
    Solicita los datos crudos a la API. Espera recibir un bloque masivo de texto separado por comas.
    """
    for i in range(1, REINTENTOS + 1):
        try:
            r = SESSION.get(CSV_URL, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            time.sleep(PAUSA_API)
            txt = r.text
            # Verifica si hay datos reales. Si solo trajo 1 línea, significa que solo trajo los encabezados (vacío).
            return txt if txt.count("\n") > 1 else None
        except Exception as e:
            print(f"❌ {e}  (intento {i}/{REINTENTOS})")
            if i < REINTENTOS:
                time.sleep(ESPERA_REINT)
    raise RuntimeError("Se agotaron los reintentos")

# --------- metadatos departamento / años ---------
def obtener_departamentos() -> list[str]:
    """
    Se conecta a la base de datos de Socrata y agrupa todos los departamentos existentes en el conjunto de datos hídricos.
    """
    print("\n🔄 Consultando lista de departamentos disponibles en el IDEAM…")
    datos = request_json({
        "$select": "departamento", # Solo trae la columna de departamento.
        "$group":  "departamento", # Agrupa los repetidos (como un 'Eliminar duplicados' en Excel).
        "$order":  "departamento", # Los ordena alfabéticamente.
        "$$app_token": APP_TOKEN,
    })
    return sorted(d["departamento"] for d in datos if d.get("departamento"))

def primer_ultimo_año(dep: str, asc: bool) -> int:
    """
    Busca la fecha más antigua (ascendente) o la más reciente (descendente) de un departamento específico para saber el rango temporal disponible.
    """
    order = "ASC" if asc else "DESC"
    datos = request_json({
        "$select": "fechaobservacion",
        "$where":  f"departamento='{dep}' AND fechaobservacion IS NOT NULL",
        "$order":  f"fechaobservacion {order}",
        "$limit":  1, # Solo necesitamos un registro (el primero o el último) para saber el año.
        "$$app_token": APP_TOKEN,
    })
    if not datos:
        raise RuntimeError("No se encontraron fechas")
    # La fecha llega como texto (ej. "2004-05-12"). La rebanamos [:4] para quedarnos solo con el "2004".
    return int(datos[0]["fechaobservacion"][:4])

def obtener_rango_anios(dep: str) -> list[int]:
    """
    Ejecuta las búsquedas de años y crea la lista completa que el programa deberá iterar.
    """
    print(f"\n🔍 Determinando rango de años con datos disponibles para {dep}…")
    a_ini = primer_ultimo_año(dep, asc=True)
    a_fin = primer_ultimo_año(dep, asc=False)
    # Rango de años consecutivos (ej. del 2004 al 2025).
    return list(range(a_ini, a_fin + 1))

# -------------- guardado en disco -------------
def guardar_chunk(chunk: str, dep: str):
    """
    Toma un bloque masivo de texto crudo, lo desmenuza, lo organiza por municipio y fecha, y lo guarda en el disco duro.
    """
    reader = csv.reader(StringIO(chunk)) # Simula que el texto es un archivo para que Python lo lea línea por línea.
    header = next(reader) # Extrae y guarda la primera fila (los nombres de las columnas).
    
    # Busca dinámicamente en qué columna exacta están el municipio y la fecha.
    i_m, i_f = header.index("municipio"), header.index("fechaobservacion")

    grupos = defaultdict(list)
    # Empieza a leer registro por registro.
    for fila in reader:
        muni, fecha = fila[i_m], fila[i_f]
        año, mes = fecha[:4], fecha[5:7] # Extrae año y mes.
        # Agrupa toda la fila dentro de una "caja" etiquetada con (municipio, año, mes).
        grupos[(muni, año, mes)].append(fila)

    # Ahora que todo está organizado en memoria, se procede a crear las carpetas físicas.
    for (muni, año, mes), filas_m in grupos.items():
        muni_s = safe_text(muni)
        carpeta = Path(CARPETA_BASE) / dep / muni_s
        carpeta.mkdir(parents=True, exist_ok=True) # Si la carpeta no existe, la crea. Si ya existe, sigue adelante.
        
        archivo = carpeta / f"{muni_s}_precipitacion_{año}_{mes}.csv"
        # Verifica si el archivo ya existe. Si sí, lo abre en modo "a" (añadir al final). Si no, en modo "w" (escribir desde cero).
        modo = "a" if archivo.exists() else "w"
        
        with archivo.open(modo, newline="", encoding="utf-8-sig") as f:
            wr = csv.writer(f)
            if modo == "w":
                wr.writerow(header) # Solo escribe los títulos de las columnas si el archivo es nuevo.
            wr.writerows(filas_m)   # Inyecta todos los datos aglomerados de golpe, lo que es extremadamente eficiente.
        print(f"✅ {muni} {año}-{mes} (+{len(filas_m):,} registros)")

# -------------- descarga completa --------------
def descargar_departamento(dep: str, anios: list[int]):
    """
    El motor principal. Crea la lista de misiones (meses y años) y envía a los trabajadores (hilos) a ejecutarlas en paralelo.
    """
    # Genera una lista de tuplas con todas las combinaciones posibles (Ej: [(2004, 1), (2004, 2)...])
    tareas = [(a, m) for a in anios for m in range(1, 13)]

    def trabajo(a_m):
        """Esta es la labor individual que ejecutará cada hilo de procesamiento de la computadora."""
        año, mes = a_m
        # Determina cuántos días tiene ese mes específico (Ej: febrero 2024 tiene 29).
        ultimo = calendar.monthrange(año, mes)[1]
        offset = 0 # Inicializador de la paginación de la API.
        
        while True: # Bucle infinito que solo se rompe cuando no hay más páginas de datos para ese mes.
            params = {
                "$where": (
                    f"departamento='{dep}' AND "
                    f"fechaobservacion between '{año}-{mes:02d}-01' "
                    f"and '{año}-{mes:02d}-{ultimo:02d}'"
                ),
                "$order":  "fechaobservacion, :id",  # ← FIX: orden estable requerido para que la paginación no se salte datos ni duplique.
                "$limit":  LIMIT,
                "$offset": offset, # Salto de página. Empieza en 0, luego pide desde el 50000, luego desde el 100000.
                "$$app_token": APP_TOKEN,
            }
            try:
                csv_text = request_csv_text(params)
            except RuntimeError as e:
                print(f"⚠ Error descargando {dep} {año}-{mes:02d}: {e}")
                return

            # Si el servidor no devolvió nada, termina el trabajo de este mes.
            if not csv_text:
                break

            # Cuenta las líneas para saber cuántos datos llegaron (restando la fila del encabezado).
            num_filas = csv_text.count("\n") - 1
            guardar_chunk(csv_text, dep) # Llama a la función de guardado en disco duro.

            # Si llegaron menos filas que el límite permitido, significa que era la última página.
            if num_filas < LIMIT:
                break
            offset += LIMIT # Si llegaron los 50.000 exactos, prepara el salto para pedir los siguientes 50.000.

    print(f"\n🚀 Iniciando descarga para {dep} ({len(anios)} años)…\n")
    t0 = time.time() # Inicia el cronómetro.
    
    # Aquí ocurre la magia de la concurrencia: El ThreadPoolExecutor asigna los meses a los diferentes núcleos del procesador.
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        list(tqdm(ex.map(trabajo, tareas), total=len(tareas), desc=dep)) # tqdm envuelve todo para mostrar la barra verde de progreso.
    print(f"\n✅ Descarga completada para {dep} en {(time.time()-t0)/60:.1f} minutos.\n")

# ------------- helper interactivo --------------
def intentar(func, desc: str):
    """
    Un escudo de protección. Si la ejecución inicial de red falla, le pregunta al usuario si desea reintentar en lugar de cerrar el programa abruptamente.
    """
    while True:
        try:
            return func() # Ejecuta la función que se le haya pasado por parámetro.
        except Exception as e:
            print(f"⛔ Error al obtener {desc}: {e}")
            if input("¿Intentar de nuevo? (s/n): ").strip().lower() != "s":
                sys.exit(1) # Cierra el programa.

# ------------------ MENÚ principal --------------
def main():
    """
    Función orquestadora. Presenta la interfaz de consola, interactúa con el usuario y dispara el proceso de descarga.
    """
    print("="*80)
    print("AUTOMATIZACIÓN INTELIGENTE PARA LA GESTIÓN VISUAL DE DATOS HÍDRICOS DEL IDEAM")
    print("Proyecto de tesis de pregrado – Ingeniería Civil")
    print("Autor: Sergio Beltrán Coley")
    print("Tutor: Ing. Carol Prada Sánchez")
    print("Cotutor: Ing. Sebastián Quintero Merchán")
    print("Universidad de la Costa – Departamento de Civil y Ambiental")
    print("Barranquilla, Colombia")
    print("="*80)
    print("\nInicializando sistema de descarga...\n")

    print("CWD:", Path.cwd()) # Muestra el directorio actual de trabajo (Current Working Directory).
    print("Guardará en:", Path(CARPETA_BASE).resolve()) # Muestra la ruta exacta absoluta donde se crearán las carpetas.

    departamentos = intentar(obtener_departamentos, "departamentos")

    while True:
        print("\n=== Departamentos disponibles ===")
        # Enumera la lista de departamentos iniciando en el número 1 para mostrarla en pantalla.
        for i, d in enumerate(departamentos, 1):
            print(f"{i:2d}. {d}")
        sel = input("\nElige un número: ").strip()
        # Verifica que el usuario haya escrito un número y que esté dentro del rango de opciones.
        if not (sel.isdigit() and 1 <= int(sel) <= len(departamentos)):
            print("⚠ Número inválido, intenta de nuevo.\n")
            continue
        dep = departamentos[int(sel) - 1] # Ajusta el número para que coincida con el índice de la lista interna (que empieza en 0).

        anios = intentar(lambda: obtener_rango_anios(dep), f"rango de años de {dep}")
        print(f"\nAños con datos en {dep}: {anios}\n")

        t0 = time.time()
        descargar_departamento(dep, anios)
        print(f"\n⏱ Tiempo total de descarga para {dep}: {(time.time()-t0)/60:.1f} min\n")

        # Bucle que permite seguir operando o finalizar la ejecución.
        if input("¿Descargar otro departamento? (s/n): ").strip().lower() != "s":
            print("\n🏁 Proceso finalizado.")
            print("\nGracias por utilizar esta herramienta de automatización.")
            print("Desarrollado como parte del proyecto de grado en Ingeniería Civil – CUC.")
            print("Datos obtenidos del IDEAM (www.datos.gov.co) bajo la Política de Datos Abiertos de Colombia, usados exclusivamente con fines académicos y de investigación.")
            print("© 2025 Sergio Beltrán Coley. Todos los derechos reservados.\n")
            break

# ---------------- EJECUCIÓN ---------------------
# Garantiza que el script principal (main) solo se ejecute si este archivo se corre directamente, no si se importa desde otro programa.
if __name__ == "__main__":
    main()