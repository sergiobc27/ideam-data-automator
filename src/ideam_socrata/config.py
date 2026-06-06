import logging
import os
from pathlib import Path
from sodapy import Socrata
from rich.console import Console
from rich.theme import Theme

# Cargar variables desde un archivo .env si existe (token de Socrata, etc.).
# Antes el README pedía crear .env pero NADIE lo leía: el token se ignoraba en
# silencio. Se busca en el directorio actual y hacia arriba. Sin python-dotenv
# instalado, simplemente se omite (las variables de entorno del sistema siguen).
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# -------------- CONFIGURACIÓN GLOBAL -----------------
APP_TOKEN     = os.getenv("SOCRATA_APP_TOKEN")
DOMAIN        = os.getenv("SOCRATA_DOMAIN", "www.datos.gov.co")
SOCRATA_USERNAME = os.getenv("SOCRATA_USERNAME")
SOCRATA_PASSWORD = os.getenv("SOCRATA_PASSWORD")
CATALOG_DATASET_ID = "hp9r-jxuu" # Catálogo Nacional Estaciones
BASE_DIR      = Path(__file__).parent.parent
CARPETA_BASE  = BASE_DIR / "data" / "processed" / "datos_ideam"

# Carpeta destino por defecto de las descargas: ruta ABSOLUTA y predecible bajo
# los Documentos del usuario (antes era 'data' relativo al terminal -> el usuario
# no programador no encontraba sus archivos). Configurable con IDEAM_OUTPUT_DIR.
DOWNLOAD_DIR = Path(
    os.getenv("IDEAM_OUTPUT_DIR", str(Path.home() / "Documents" / "IDEAM_Data"))
)

# Configuración de Logging
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    filename=LOG_DIR / 'automatizacion_ideam.log',
    filemode='a',
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

LIMIT         = int(os.getenv("SOCRATA_LIMIT", "50000"))
MAX_WORKERS   = int(os.getenv("SOCRATA_MAX_WORKERS", "20"))
TIMEOUT       = int(os.getenv("SOCRATA_TIMEOUT", "300"))
UPSERT_CHUNK_SIZE = int(os.getenv("SOCRATA_UPSERT_CHUNK_SIZE", "5000"))
EXCEL_MAX_ROWS = int(os.getenv("EXCEL_MAX_ROWS", "1048576"))

# -------------- TEMA UNIVERSIDAD DE LA COSTA -----------------
tema_uc = Theme({
    "primario": "#A3161A",
    "secundario": "#FCD116",
    "acento": "#C9A227",
    "exito": "#FCD116",
    "borde": "#595959",
    "texto": "#CCCCCC",
    "texto_oscuro": "#A5A5A5",
    "p_bold": "bold #A3161A",
    "s_bold": "bold #FCD116",
    "t_bold": "bold #CCCCCC"
})
# force_terminal=True forzaba colores ANSI SIEMPRE: al redirigir la salida
# (`ideam-socrata datasets > lista.txt`) el archivo salía lleno de códigos de
# escape. Dejar que rich detecte el destino y respetar la convención NO_COLOR.
console = Console(theme=tema_uc, no_color=bool(os.getenv("NO_COLOR")))

if not APP_TOKEN:
    logging.warning("SOCRATA_APP_TOKEN no esta definido; se usara lectura anonima si Socrata lo permite.")

def get_socrata_client(write=False):
    """Build a Socrata client for read or authenticated write operations."""
    if write:
        if not SOCRATA_USERNAME or not SOCRATA_PASSWORD:
            raise RuntimeError(
                "Para escribir en Socrata configure SOCRATA_USERNAME y SOCRATA_PASSWORD."
            )
        return Socrata(
            DOMAIN,
            APP_TOKEN,
            username=SOCRATA_USERNAME,
            password=SOCRATA_PASSWORD,
            timeout=TIMEOUT,
        )
    return Socrata(DOMAIN, APP_TOKEN, timeout=TIMEOUT)

CLIENT = get_socrata_client()

DATASETS_INFO = [
    {"nombre": "Precipitación", "id": "s54a-sgyg", "fecha_col": "fechaobservacion", "tipo": "estandar"},
    {"nombre": "Nivel del Mar", "id": "ia8x-22em", "fecha_col": "fechaobservacion", "tipo": "estandar"},
    {"nombre": "Dirección del Viento", "id": "kiw7-v9ta", "fecha_col": "fechaobservacion", "tipo": "estandar"},
    {"nombre": "Velocidad del Viento", "id": "sgfv-3yp8", "fecha_col": "fechaobservacion", "tipo": "estandar"},
    {"nombre": "Presión Atmosférica", "id": "62tk-nxj5", "fecha_col": "fechaobservacion", "tipo": "estandar"},
    {"nombre": "Humedad del Aire", "id": "uext-mhny", "fecha_col": "fechaobservacion", "tipo": "estandar"},
    {"nombre": "Temperatura Máxima del Aire", "id": "ccvq-rp9s", "fecha_col": "fechaobservacion", "tipo": "estandar"},
    {"nombre": "Temperatura Mínima del Aire", "id": "afdg-3zpb", "fecha_col": "fechaobservacion", "tipo": "estandar"},
    {"nombre": "Nivel Máximo del Rio", "id": "vfth-yucv", "fecha_col": "fechaobservacion", "tipo": "estandar"},
    {"nombre": "Nivel Instantáneo del Rio", "id": "bdmn-sqnh", "fecha_col": "fechaobservacion", "tipo": "estandar"},
    {"nombre": "Nivel Mínimo del Rio", "id": "pt9a-aamx", "fecha_col": "fechaobservacion", "tipo": "estandar"},
    {"nombre": "Nivel del Mar Máximo", "id": "uxy3-jchf", "fecha_col": "fechaobservacion", "tipo": "estandar"},
    {"nombre": "Nivel del Mar Mínimo", "id": "7z6g-yx9q", "fecha_col": "fechaobservacion", "tipo": "estandar"},
    
    # Datasets Especiales.
    # dep_col: columna de departamento (si existe) para poder filtrar.
    # fecha_real: la columna de fecha es timestamp (permite rango de años);
    #             si es False/ausente es un año/periodo en texto y se baja directo.
    {"nombre": "Calidad Del Aire Promedio Anual", "id": "kekd-7v7h", "fecha_col": "a_o", "tipo": "especial",
     "dep_col": "nombre_del_departamento"},
    {"nombre": "Calidad del Aire en Colombia", "id": "g4t8-zkc3", "fecha_col": "med_fecha_inicio", "tipo": "especial",
     "dep_col": "departamento", "fecha_real": True},
    {"nombre": "Data histórica de calidad de agua", "id": "62gv-3857", "fecha_col": "fecha", "tipo": "especial",
     "dep_col": "departamento", "fecha_real": True},
    {"nombre": "Zonificación Hidrográfica Colombia", "id": "5kjg-nuda", "fecha_col": None, "tipo": "especial"},
    {"nombre": "Normales Climatológicas de Colombia", "id": "nsz2-kzcq", "fecha_col": "ao", "tipo": "especial",
     "dep_col": "departamento"},
    {"nombre": "Inventario Nacional Gases Efecto Invernadero", "id": "6rff-a5ep", "fecha_col": "a_o", "tipo": "especial"},
    {"nombre": "Histórico mensual de escorrentía", "id": "kg4b-vx7j", "fecha_col": "mes_a_o", "tipo": "especial"},
    {"nombre": "Catálogo Nacional de Estaciones", "id": CATALOG_DATASET_ID, "fecha_col": None, "tipo": "especial",
     "dep_col": "departamento"}
]

MAPEO_DEPARTAMENTOS = {
    "ANTIOQUIA": ["ANTIOQUIA"],
    "VALLE DEL CAUCA": ["VALLE DEL CAUCA", "VALLE"],
    # San Andrés vive bajo MUCHOS nombres reales en la fuente (verificado en vivo
    # 2026-06-06: 4 variantes solo en presión, con/sin tilde y con/sin coma).
    "SAN ANDRES Y PROVIDENCIA": [
        "SAN ANDRES", "SAN ANDRES Y PROVIDENCIA", "SAN ANDRÉS Y PROVIDENCIA",
        "SAN ANDRES PROVIDENCIA", "SAN ANDRÉS PROVIDENCIA",
        "ARCHIPIELAGO DE SAN ANDRES PROVIDENCIA Y SANTA CATALINA",
        "ARCHIPIÉLAGO DE SAN ANDRES PROVIDENCIA Y SANTA CATALINA",
        "ARCHIPIÉLAGO DE SAN ANDRÉS PROVIDENCIA Y SANTA CATALINA",
        "ARCHIPIELAGO DE SAN ANDRES, PROVIDENCIA Y SANTA CATALINA",
        "ARCHIPIÉLAGO DE SAN ANDRÉS, PROVIDENCIA Y SANTA CATALINA",
    ],
    "BOGOTA D.C.": ["BOGOTA", "BOGOTÁ", "BOGOTÁ D.C.", "BOGOTA, D.C"],
    "AMAZONAS": ["AMAZONAS"], "ARAUCA": ["ARAUCA"], "ATLANTICO": ["ATLANTICO", "ATLÁNTICO"],
    "BOLIVAR": ["BOLIVAR", "BOLÍVAR"], "BOYACA": ["BOYACA", "BOYACÁ"], "CALDAS": ["CALDAS"],
    "CAQUETA": ["CAQUETA", "CAQUETÁ"], "CASANARE": ["CASANARE"], "CAUCA": ["CAUCA"],
    "CESAR": ["CESAR"], "CHOCO": ["CHOCO", "CHOCÓ"], "CORDOBA": ["CORDOBA", "CÓRDOBA"],
    "CUNDINAMARCA": ["CUNDINAMARCA"], "GUAINIA": ["GUAINIA", "GUAINÍA"], "GUAVIARE": ["GUAVIARE"],
    "HUILA": ["HUILA"], "LA GUAJIRA": ["LA GUAJIRA", "GUAJIRA"], "MAGDALENA": ["MAGDALENA"],
    "META": ["META"], "NARIÑO": ["NARIÑO", "NARINO"], "NORTE DE SANTANDER": ["NORTE DE SANTANDER"],
    "PUTUMAYO": ["PUTUMAYO"], "QUINDIO": ["QUINDIO", "QUINDÍO"], "RISARALDA": ["RISARALDA"],
    "SANTANDER": ["SANTANDER"], "SUCRE": ["SUCRE"], "TOLIMA": ["TOLIMA"],
    "VAUPES": ["VAUPES", "VAUPÉS"], "VICHADA": ["VICHADA"]
}
