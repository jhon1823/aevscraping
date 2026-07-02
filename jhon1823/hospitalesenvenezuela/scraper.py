"""
Scraper para hospitalesenvenezuela.com (API de Supabase)
"""

import json
import os
import sys
import requests
from datetime import datetime
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Configuración de Supabase (obtenida del HTML)
SUPABASE_URL = "https://ozuxfepfkvnxkywdsqxy.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im96dXhmZXBma3ZueGt5d2RzcXh5Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODI0MjI5NTEsImV4cCI6MjA5Nzk5ODk1MX0.YhW0GalGkQZdO2NJTg_01C5XhdMmJ6RbNSNXXC0xG4o"

HEADERS = {
    "apikey": SUPABASE_ANON_KEY,
    "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
    "Content-Type": "application/json"
}

def map_id(value):
    return str(value) if value is not None else None

def map_timestamp(value):
    if not value:
        return datetime.now().isoformat()
    return value

def run(output_dir: str, limit: Optional[int] = None, only_smoke: bool = False) -> List[Dict[str, Any]]:
    """
    Ejecuta el scraper de hospitalesenvenezuela.com
    """
    print("🏥 Scrapeando hospitalesenvenezuela.com (API Supabase)...")
    
    # Obtener hospitales
    hospitals = fetch_hospitals()
    # Obtener pacientes (personas ingresadas)
    patients = fetch_patients()
    
    # Mapear hospitales al esquema unificado
    records = []
    for h in hospitals:
        record = {
            "id": map_id(h.get("id")),
            "nombre": h.get("nombre", ""),
            "cedula": "",
            "edad": "",
            "ultima_ubicacion": f"{h.get('ciudad', '')}, {h.get('estado', '')}",
            "telefono_contacto": h.get("telefono") or "",
            "observaciones": f"Tipo: {h.get('tipo', '')} | Estado operativo: {h.get('estado_operativo', '')}",
            "estado": "Localizado" if h.get("estado_operativo") == "abierto" else "Desaparecido",
            # Los hospitales no son personas, pero para el pipeline los marcamos como "Localizado" si están abiertos, para no duplicar con desaparecidos.
            "ubicacion_encontrado": "",
            "encontrado_por": "",
            "encontrado_por_cedula": "",
            "foto_url": "",
            "fecha_registro": map_timestamp(h.get("ultima_actualizacion")),
            "fecha_actualizacion": map_timestamp(h.get("ultima_actualizacion")),
            "es_menor": False,
            "fuente": "hospitalesenvenezuela.com",
        }
        records.append(record)
    
    # Mapear pacientes al esquema unificado
    for p in patients:
        # Buscar el hospital al que pertenece (por nombre)
        centro = p.get("centro", "")
        hospital = next((h for h in hospitals if h.get("nombre") == centro), {})
        record = {
            "id": map_id(p.get("id")),
            "nombre": p.get("nombre", ""),
            "cedula": p.get("cedula") or "",
            "edad": p.get("edad") or "",
            "ultima_ubicacion": centro,
            "telefono_contacto": hospital.get("telefono") or "",
            "observaciones": p.get("detalle") or "",
            "estado": "Localizado" if p.get("estado") in ["encontrada", "alta"] else "Desaparecido",
            # Aquí podríamos usar el estado real, pero el pipeline requiere un campo "estado" con "Desaparecido" o "Localizado".
            # Si está en un hospital, asumimos que está "Localizado" (encontrado), pero para conservar la distinción, podríamos usar un campo adicional.
            # Sin embargo, el pipeline está diseñado para personas desaparecidas/localizadas.
            "ubicacion_encontrado": "",
            "encontrado_por": "",
            "encontrado_por_cedula": "",
            "foto_url": "",
            "fecha_registro": map_timestamp(p.get("fecha_registro")),
            "fecha_actualizacion": map_timestamp(p.get("fecha_actualizacion") or p.get("fecha_registro")),
            "es_menor": False,
            "fuente": "hospitalesenvenezuela.com",
        }
        records.append(record)
    
    # Guardar JSON
    output_path = os.path.join(output_dir, "hospitalesenvenezuela.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    
    print(f"✅ Guardado {len(records)} registros en {output_path}")
    
    if only_smoke:
        print(f"🔍 Primeros {limit or 5} registros:")
        for r in records[:limit or 5]:
            print(f"  - {r['nombre']} | {r['estado']} | {r['ultima_ubicacion']}")
    
    return records

def fetch_hospitals() -> List[Dict[str, Any]]:
    """
    Obtiene la lista de hospitales desde la API de Supabase.
    """
    url = f"{SUPABASE_URL}/rest/v1/hospitales"
    params = {
        "select": "id,nombre,tipo,estado,ciudad,telefono,lat,lng,estado_operativo,capacidad,nota,confirmaciones,ultima_actualizacion,verificado,personal_salud",
        "activo": "eq.true"
    }
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        # Añadir conteo de pacientes por hospital (opcional, se puede hacer con otra llamada)
        return data
    except Exception as e:
        print(f"❌ Error al obtener hospitales: {e}")
        return []

def fetch_patients() -> List[Dict[str, Any]]:
    """
    Obtiene los pacientes (personas ingresadas) desde la API de Supabase.
    No hay un endpoint directo, pero podemos usar la función RPC buscar_paciente sin término para obtener todos.
    """
    # La función buscar_paciente requiere un término, pero podemos usar un término vacío para obtener todos (si la función lo soporta)
    # Alternativamente, podríamos hacer una consulta a la tabla 'pacientes' si existe.
    # Por simplicidad, devolvemos una lista vacía por ahora y lo dejamos para una segunda iteración.
    # Pero podemos intentar con un término genérico como "a" para obtener muchos.
    url = f"{SUPABASE_URL}/rest/v1/rpc/buscar_paciente"
    try:
        # Usamos un término corto para obtener muchos resultados
        resp = requests.post(url, headers=HEADERS, json={"p_term": "a"}, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"⚠️ No se pudieron obtener pacientes (status {resp.status_code})")
            return []
    except Exception as e:
        print(f"❌ Error al obtener pacientes: {e}")
        return []

if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        run(tmpdir, limit=5, only_smoke=True)