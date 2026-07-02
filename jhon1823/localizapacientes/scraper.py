"""
Scraper para localizapacientes.com
"""

import json
import os
import sys
import requests
from datetime import datetime
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

def map_id(value):
    return str(value) if value is not None else None

def map_timestamp(value):
    if not value:
        return datetime.now().isoformat()
    return value

def run(output_dir: str, limit: Optional[int] = None, only_smoke: bool = False) -> List[Dict[str, Any]]:
    print("🕵️ Scrapeando localizapacientes.com...")
    
    data = fetch_data(limit)
    
    if not data:
        print("⚠️ No se encontraron datos")
        return []
    
    records = []
    for item in data:
        # Mapeamos los campos del JSON al esquema unificado
        # El JSON trae: id, nombre, ciudad, estado, pacientesRegistrados, ultimaActualizacion
        record = {
            "id": map_id(item.get("id")),
            "nombre": item.get("nombre", ""),
            "cedula": "",  # No disponible en esta API
            "edad": "",    # No disponible
            "ultima_ubicacion": f"{item.get('ciudad', '')}, {item.get('estado', '')}",
            "telefono_contacto": "",
            "observaciones": f"Pacientes registrados: {item.get('pacientesRegistrados', 0)}",
            "estado": "Localizado" if item.get('pacientesRegistrados', 0) > 0 else "Desaparecido",
            "ubicacion_encontrado": "",
            "encontrado_por": "",
            "encontrado_por_cedula": "",
            "foto_url": "",
            "fecha_registro": map_timestamp(item.get("ultimaActualizacion")),
            "fecha_actualizacion": map_timestamp(item.get("ultimaActualizacion")),
            "es_menor": False,
            "fuente": "localizapacientes.com",
        }
        records.append(record)
    
    output_path = os.path.join(output_dir, "localizapacientes.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    
    print(f"✅ Guardado {len(records)} registros en {output_path}")
    
    if only_smoke:
        for r in records[:limit or 5]:
            print(f"  - {r['nombre']} | {r['estado']} | {r['ultima_ubicacion']}")
    
    return records

def fetch_data(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Obtiene los datos del endpoint /api/hospitals"""
    url = "https://localizapacientes.com/api/hospitals"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            print(f"✅ Datos obtenidos: {len(data)} hospitales")
            return data[:limit] if limit else data
        else:
            print(f"❌ Error HTTP: {resp.status_code}")
            return []
    except Exception as e:
        print(f"❌ Error al obtener datos: {e}")
        return []

if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        run(tmpdir, limit=5, only_smoke=True)