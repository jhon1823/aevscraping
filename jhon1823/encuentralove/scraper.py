"""
Scraper para encuentralove.com

Verificado: este dominio redirige directamente a tebusco.app/index.html
(mismo bundle, misma config de PORTERO). No tiene backend ni datos
propios; todos los datos provienen del backend real en tebusco.app.

Este scraper delega la extracción a jhon1823/tebusco/scraper.py y
re-etiqueta el campo 'fuente' como 'encuentralove.com' para trazabilidad
(saber qué dominio referenció a cada persona).

Nota sobre deduplicación: como este scraper y el de tebusco.app comparten
el mismo backend, run_daily.py.limpiar_y_deduplicar() colapsará los
registros duplicados (mismo nombre/edad/ciudad) al consolidar, priorizando
'Localizado' sobre 'Desaparecido'.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from jhon1823.tebusco import scraper as tebusco_scraper

SOURCE_LABEL = "encuentralove.com"
OUTPUT_FILENAME = "encuentralove.json"


def run(output_dir, limit: Optional[int] = None, only_smoke: bool = False) -> list:
    """
    Extrae registros de encuentralove.com. Al redirigir a tebusco.app sin
    backend propio, delega la extracción real al scraper de tebusco.app y
    solo re-etiqueta la fuente.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / OUTPUT_FILENAME

    print(f"[encuentralove] NOTA: {SOURCE_LABEL} redirige a tebusco.app (mismo backend).")
    print("[encuentralove] Extrayendo datos vía tebusco.app/tebusco-portero.php …")

    records = tebusco_scraper.run(output_dir=output_dir, limit=limit, only_smoke=only_smoke)

    for rec in records:
        rec["fuente"] = SOURCE_LABEL

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"[encuentralove] OK: {len(records)} registros guardados en {output_file}")
    return records


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scraper de encuentralove.com")
    parser.add_argument("--output-dir", default="output", help="Carpeta de salida")
    parser.add_argument("--limit", type=int, default=None, help="Máx. registros")
    parser.add_argument("--smoke", action="store_true", help="Prueba rápida (solo 100 más recientes)")
    args = parser.parse_args()

    registros = run(output_dir=args.output_dir, limit=args.limit, only_smoke=args.smoke)
    print(f"Total registros: {len(registros)}")
