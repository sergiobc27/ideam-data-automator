"""
AUTOMATIZACIÓN INTELIGENTE PARA LA GESTIÓN VISUAL DE DATOS HÍDRICOS DEL IDEAM
Versión Estática: Evita el escaneo inicial de la base de datos definiendo los departamentos manualmente.
Autor: Sergio Beltrán Coley
"""

# ==========================================
# IMPORTACIÓN DE LIBRERÍAS Y SUS FUNCIONES
# ==========================================
import csv              # Permite la estructuración y manipulación de archivos tipo CSV.
import time             # Manejo de tiempos, cronómetros de rendimiento y pausas operativas.
import calendar         # Provee inteligencia de calendario (días máximos por mes, años bisiestos).
import requests         # Librería HTTP esencial para ejecutar las solicitudes a la API de Socrata.
import re               # Expresiones Regulares para la limpieza y purificación de textos crudos.
import sys              # Comunicación directa con los comandos del sistema operativo.
from io import StringIO # Buffer que permite tratar cadenas de texto como si fuesen archivos físicos en memoria.
from pathlib import Path # Gestión de directorios y rutas locales de manera estructurada y segura.
from collections import defaultdict # Diccionarios con inicialización automática para evitar errores de llaves inexistentes.
from concurrent.futures import ThreadPoolExecutor # Gestor de hilos para procesamiento paralelo y descargas simultáneas.
from tqdm import tqdm   # Interfaz visual de progreso para consola.

# -------------- CONFIGURACIÓN -----------------
APP_TOKEN     = "SOCRATA_APP_TOKEN_REMOVED" # Identificador de aplicación para evitar "throttling" (estrangulamiento de red).
DOMAIN        = "www.datos.gov.co"          # Servidor origen.
DATASET_ID    = "s54a-sgyg"                 # ID del proyecto hidrológico en Datos Abiertos.
CARPETA_BASE = Path(__file__).parent / "datos_hidricos" # Ruta destino de extracción.

LIMIT         = 50000 # Cuota de paginación obligatoria de la API.
MAX_WORKERS   = 30    # Nivel de concurrencia de la CPU asignada a la descarga.
TIMEOUT       = 120   # Tiempo límite de espera por paquete de red.
REINTENTOS    = 3     # Tolerancia a fallos de conexión.
ESPERA_REINT  = 0     # Demora post-fallo.
PAUSA_API     = 0.1   # Mitigación de carga en servidor externo (evita ban de IP).
# ----------------------------------------------

CSV_URL  = f"https://{DOMAIN}/resource/{DATASET_ID}.csv"
JSON_URL = f"https://{DOMAIN}/resource/{DATASET_ID}.json"

SESSION = requests.Session() # Canal de conexión persistente para optimizar la latencia TCP/IP.
SESSION.headers.update({"Accept-Encoding": "gzip"}) # Petición de compresión de paquetes.

# ---------------- utilidades ------------------
def safe_text(t: str) -> str:
    """Remueve caracteres inválidos para el sistema de archivos del SO."""
    return re.sub(r'[<>:"/\\|?*]', "_", t.strip())

def request_json(params: dict) -> list[dict]:
    """Ejecuta consulta a la API esperando una respuesta JSON (Metadatos)."""
    for i in range(1, REINTENTOS + 1):
        try:
            r = SESSION.get(JSON_URL, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            time.sleep(PAUSA_API)
            return r.json()
        except Exception as e:
            print(f"❌ {e}  (intento {i}/{REINTENTOS})")
            if i < REINTENTOS:
                time.sleep(ESPERA_REINT)
    raise RuntimeError("Se agotaron los reintentos")

def request_csv_text(params: dict) -> str | None:
    """Ejecuta consulta a la API esperando el archivo crudo CSV (Datos masivos)."""
    for i in range(1, REINTENTOS + 1):
        try:
            r = SESSION.get(CSV_URL, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            time.sleep(PAUSA_API)
            txt = r.text
            return txt if txt.count("\n") > 1 else None
        except Exception as e:
            print(f"❌ {e}  (intento {i}/{REINTENTOS})")
            if i < REINTENTOS:
                time.sleep(ESPERA_REINT)
    raise RuntimeError("Se agotaron los reintentos")

# --------- metadatos departamento / años ---------
def obtener_departamentos() -> list[str]:
    """
    VERSION ESTÁTICA: A diferencia de la versión dinámica, aquí se define la lista dura en el código.
    Esto elimina el paso exploratorio que consume tiempo de consulta, permitiendo que el programa inicie al instante.
    Incluye las variaciones tipográficas exactas presentes en la base de datos oficial.
    """
    print("\n🔄 Cargando lista de departamentos (incluyendo variaciones tipográficas del IDEAM)…")
    return [
        "AMAZONAS", "ANTIOQUIA", "ARAUCA", 
        "ARCHIPIELAGO DE SAN ANDRES PROVIDENCIA Y SANTA CATALINA",
        "ARCHIPIELAGO DE SAN ANDRES, PROVIDENCIA Y SANTA CATALINA",
        "ARCHIPIÉLAGO DE SAN ANDRES PROVIDENCIA Y SANTA CATALINA",
        "ATLANTICO", "ATLÁNTICO", "BOGOTA", "BOGOTA D.C.", "BOGOTÁ", 
        "BOLIVAR", "BOLÍVAR", "BOYACÁ", "CALDAS", "CAQUETA", "CAQUETÁ", 
        "CASANARE", "CAUCA", "CESAR", "CHOCO", "CHOCÓ", "CORDOBA", 
        "CUNDINAMARCA", "CÓRDOBA", "GUAINÍA", "GUAVIARE", "HUILA", 
        "LA GUAJIRA", "MAGDALENA", "META", "NARINO", "NARIÑO", 
        "NORTE DE SANTANDER", "PUTUMAYO", "QUINDÍO", "RISARALDA", 
        "SAN ANDRÉS PROVIDENCIA", "SANTANDER", "SUCRE", "TOLIMA", 
        "VALLE DEL CAUCA", "VAUPES", "VAUPÉS", "VICHADA"
    ]

def obtener_rango_anios(dep: str) -> list[int]:
    """
    VERSIÓN MANUAL: Otorga el control total al usuario para definir el rango de investigación,
    evitando que el sistema busque las fechas extremas históricas por su cuenta.
    Útil cuando el investigador solo requiere analizar ventanas de tiempo muy específicas (ej. Fenómeno de La Niña en 2010).
    """
    print(f"\n📅 Define el rango de años a descargar para {dep}")
    while True: # Bucle de validación de entrada
        try:
            # Captura de datos vía consola
            a_ini = int(input("Ingresa el año inicial (ej. 2000): ").strip())
            a_fin = int(input("Ingresa el año final (ej. 2025): ").strip())
            
            # Filtro lógico de cronología
            if a_ini > a_fin:
                print("⚠ El año inicial no puede ser mayor al año final. Intenta de nuevo.")
                continue
            # Filtro lógico de validez temporal
            if a_ini < 1900 or a_fin > 2100:
                print("⚠ Ingresa un rango de años lógico y válido.")
                continue
            
            # Generación secuencial del rango
            return list(range(a_ini, a_fin + 1))
        except ValueError:
            print("⚠ Entrada inválida. Por favor ingresa números enteros (ej. 2015).")

# -------------- guardado en disco -------------
def guardar_chunk(chunk: str, dep: str):
    """Estructura y vuelca en el disco físico la matriz de datos almacenada temporalmente en RAM."""
    reader = csv.reader(StringIO(chunk))
    header = next(reader)
    i_m, i_f = header.index("municipio"), header.index("fechaobservacion")

    grupos = defaultdict(list) # Contenedor agrupador por municipio y fecha.
    for fila in reader:
        muni, fecha = fila[i_m], fila[i_f]
        año, mes = fecha[:4], fecha[5:7]
        grupos[(muni, año, mes)].append(fila)

    for (muni, año, mes), filas_m in grupos.items():
        muni_s = safe_text(muni)
        carpeta = Path(CARPETA_BASE) / dep / muni_s
        carpeta.mkdir(parents=True, exist_ok=True)
        archivo = carpeta / f"{muni_s}_precipitacion_{año}_{mes}.csv"
        modo = "a" if archivo.exists() else "w"
        
        with archivo.open(modo, newline="", encoding="utf-8-sig") as f:
            wr = csv.writer(f)
            if modo == "w":
                wr.writerow(header)
            wr.writerows(filas_m)
        print(f"✅ {muni} {año}-{mes} (+{len(filas_m):,} registros)")

# -------------- descarga completa --------------
def descargar_departamento(dep: str, anios: list[int]):
    """Motor ETL de extracción paralela y transformación estructurada."""
    tareas = [(a, m) for a in anios for m in range(1, 13)] # Matriz de carga de trabajo.

    def trabajo(a_m):
        """Operación atómica ejecutada asincrónicamente por cada hilo asignado."""
        año, mes = a_m
        ultimo = calendar.monthrange(año, mes)[1]
        offset = 0 # Controlador de paginación para evitar el desbordamiento (límite de 50.000).
        
        while True:
            params = {
                "$where": (
                    f"departamento='{dep}' AND "
                    f"fechaobservacion between '{año}-{mes:02d}-01' "
                    f"and '{año}-{mes:02d}-{ultimo:02d}'"
                ),
                "$order":  "fechaobservacion, :id",  # ← FIX: orden estable (Clave primaria virtual para evitar saltos).
                "$limit":  LIMIT,
                "$offset": offset,
                "$$app_token": APP_TOKEN,
            }
            try:
                csv_text = request_csv_text(params)
            except RuntimeError as e:
                print(f"⚠ Error descargando {dep} {año}-{mes:02d}: {e}")
                return

            if not csv_text:
                break # Fin de los datos disponibles para ese mes.

            num_filas = csv_text.count("\n") - 1
            guardar_chunk(csv_text, dep) # Ejecuta el volcado a disco duro.

            if num_filas < LIMIT:
                break # Si el paquete trajo menos de la cuota máxima, es la última página.
            offset += LIMIT # Suma la cuota límite para pedir el siguiente paquete en la siguiente iteración.

    print(f"\n🚀 Iniciando descarga para {dep} ({len(anios)} años)…\n")
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        list(tqdm(ex.map(trabajo, tareas), total=len(tareas), desc=dep))
    print(f"\n✅ Descarga completada para {dep} en {(time.time()-t0)/60:.1f} minutos.\n")

# ------------- helper interactivo --------------
def intentar(func, desc: str):
    """Capa de seguridad ante fallos de conexión (Manejo interactivo de excepciones)."""
    while True:
        try:
            return func()
        except Exception as e:
            print(f"⛔ Error al obtener {desc}: {e}")
            if input("¿Intentar de nuevo? (s/n): ").strip().lower() != "s":
                sys.exit(1)

# ------------------ MENÚ principal --------------
def main():
    """Centro de control y ejecución secuencial del programa."""
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

    print("CWD:", Path.cwd())
    print("Guardará en:", Path(CARPETA_BASE).resolve())

    departamentos = intentar(obtener_departamentos, "departamentos")

    while True: # Bucle del sistema principal operativo
        print("\n=== Departamentos disponibles ===")
        for i, d in enumerate(departamentos, 1):
            print(f"{i:2d}. {d}")
        sel = input("\nElige un número: ").strip()
        if not (sel.isdigit() and 1 <= int(sel) <= len(departamentos)):
            print("⚠ Número inválido, intenta de nuevo.\n")
            continue
        dep = departamentos[int(sel) - 1]

        anios = intentar(lambda: obtener_rango_anios(dep), f"rango de años de {dep}")
        print(f"\nAños con datos en {dep}: {anios}\n")

        t0 = time.time()
        descargar_departamento(dep, anios)
        print(f"\n⏱ Tiempo total de descarga para {dep}: {(time.time()-t0)/60:.1f} min\n")

        if input("¿Descargar otro departamento? (s/n): ").strip().lower() != "s":
            print("\n🏁 Proceso finalizado.")
            print("\nGracias por utilizar esta herramienta de automatización.")
            print("Desarrollado como parte del proyecto de grado en Ingeniería Civil – CUC.")
            print("Datos obtenidos del IDEAM (www.datos.gov.co) bajo la Política de Datos Abiertos de Colombia, usados exclusivamente con fines académicos y de investigación.")
            print("© 2025 Sergio Beltrán Coley. Todos los derechos reservados.\n")
            break

# ---------------- EJECUCIÓN ---------------------
if __name__ == "__main__":
    main()