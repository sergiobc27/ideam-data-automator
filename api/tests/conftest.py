"""Config de pytest para los tests de candados de la API.

Estos tests NO requieren Postgres ni pyarrow: importan únicamente los módulos
livianos (ratelimit, settings) y/o mockean el pool de conexiones.
"""

import sys
from pathlib import Path

# Permite `import app...` ejecutando pytest desde api/ o desde la raíz del repo.
API_DIR = Path(__file__).resolve().parents[1]
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))
