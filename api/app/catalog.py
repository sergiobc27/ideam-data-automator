"""Port de website/src/worker/catalogConfig.js: datasets, departamentos y filtros."""

DATASETS = [
    {"name": "Precipitacion", "id": "s54a-sgyg", "dateColumn": "fechaobservacion", "category": "Hidrometeorologia"},
    {"name": "Nivel del Mar", "id": "ia8x-22em", "dateColumn": "fechaobservacion", "category": "Oceanografia"},
    {"name": "Direccion del Viento", "id": "kiw7-v9ta", "dateColumn": "fechaobservacion", "category": "Meteorologia"},
    {"name": "Velocidad del Viento", "id": "sgfv-3yp8", "dateColumn": "fechaobservacion", "category": "Meteorologia"},
    {"name": "Presion Atmosferica", "id": "62tk-nxj5", "dateColumn": "fechaobservacion", "category": "Meteorologia"},
    {"name": "Humedad del Aire", "id": "uext-mhny", "dateColumn": "fechaobservacion", "category": "Meteorologia"},
    {"name": "Temperatura Maxima del Aire", "id": "ccvq-rp9s", "dateColumn": "fechaobservacion", "category": "Meteorologia"},
    {"name": "Temperatura Minima del Aire", "id": "afdg-3zpb", "dateColumn": "fechaobservacion", "category": "Meteorologia"},
    {"name": "Nivel Maximo del Rio", "id": "vfth-yucv", "dateColumn": "fechaobservacion", "category": "Hidrologia"},
    {"name": "Nivel Instantaneo del Rio", "id": "bdmn-sqnh", "dateColumn": "fechaobservacion", "category": "Hidrologia"},
    {"name": "Nivel Minimo del Rio", "id": "pt9a-aamx", "dateColumn": "fechaobservacion", "category": "Hidrologia"},
    {"name": "Nivel del Mar Maximo", "id": "uxy3-jchf", "dateColumn": "fechaobservacion", "category": "Oceanografia"},
    {"name": "Nivel del Mar Minimo", "id": "7z6g-yx9q", "dateColumn": "fechaobservacion", "category": "Oceanografia"},
]

DATASETS_BY_ID = {d["id"]: d for d in DATASETS}

# canonico (como lo conoce el frontend) -> variantes historicas (tildes, mojibake)
DEPARTMENT_MAP = {
    "AMAZONAS": ["AMAZONAS"],
    "ANTIOQUIA": ["ANTIOQUIA"],
    "ARAUCA": ["ARAUCA"],
    "ATLANTICO": ["ATLANTICO", "ATLÁNTICO", "ATLÃƒÂNTICO"],
    "BOLIVAR": ["BOLIVAR", "BOLÍVAR", "BOLÃƒÂVAR"],
    "BOGOTA D.C.": ["BOGOTA", "BOGOTÁ", "BOGOTÁ D.C.", "BOGOTA, D.C", "BOGOTÃƒÂ", "BOGOTÃƒÂ D.C."],
    "BOYACA": ["BOYACA", "BOYACÁ", "BOYACÃƒÂ"],
    "CALDAS": ["CALDAS"],
    "CAQUETA": ["CAQUETA", "CAQUETÁ", "CAQUETÃƒÂ"],
    "CASANARE": ["CASANARE"],
    "CAUCA": ["CAUCA"],
    "CESAR": ["CESAR"],
    "CHOCO": ["CHOCO", "CHOCÓ", "CHOCÃƒâ€œ"],
    "CORDOBA": ["CORDOBA", "CÓRDOBA", "CÃƒâ€œRDOBA"],
    "CUNDINAMARCA": ["CUNDINAMARCA"],
    "GUAINIA": ["GUAINIA", "GUAINÍA", "GUAINÃƒÂA"],
    "GUAVIARE": ["GUAVIARE"],
    "HUILA": ["HUILA"],
    "LA GUAJIRA": ["LA GUAJIRA", "GUAJIRA"],
    "MAGDALENA": ["MAGDALENA"],
    "META": ["META"],
    "NARINO": ["NARIÑO", "NARINO", "NARIÃƒâ€˜O"],
    "NORTE DE SANTANDER": ["NORTE DE SANTANDER"],
    "PUTUMAYO": ["PUTUMAYO"],
    "QUINDIO": ["QUINDIO", "QUINDÍO", "QUINDÃƒÂO"],
    "RISARALDA": ["RISARALDA"],
    "SAN ANDRES Y PROVIDENCIA": ["SAN ANDRES", "SAN ANDRÉS Y PROVIDENCIA", "SAN ANDRÃƒâ€°S Y PROVIDENCIA"],
    "SANTANDER": ["SANTANDER"],
    "SUCRE": ["SUCRE"],
    "TOLIMA": ["TOLIMA"],
    "VALLE DEL CAUCA": ["VALLE DEL CAUCA", "VALLE"],
    "VAUPES": ["VAUPES", "VAUPÉS", "VAUPÃƒâ€°S"],
    "VICHADA": ["VICHADA"],
}

CATALOG_FILTERS = [
    {"key": "municipalities", "label": "Municipio", "column": "municipio"},
    {"key": "hydrologicZones", "label": "Zona hidrografica", "column": "zonahidrografica"},
    {"key": "stations", "label": "Codigo de estacion", "column": "codigoestacion", "labelColumn": "nombreestacion"},
    {"key": "stationNames", "label": "Nombre de estacion", "column": "nombreestacion"},
]

CATALOG_FILTERS_BY_KEY = {f["key"]: f for f in CATALOG_FILTERS}
