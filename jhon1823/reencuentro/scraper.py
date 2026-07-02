"""
Scraper para reencuentro.help
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
    print("🕵️ Scrapeando reencuentro.help...")
    
    data = fetch_data(limit)
    
    if not data:
        print("⚠️ No se encontraron datos")
        return []
    
    records = []
    for item in data:
        record = {
            "id": map_id(item.get("id")),
            "nombre": item.get("nombre", ""),
            "cedula": item.get("cedula", ""),
            "edad": item.get("edad", ""),
            "ultima_ubicacion": item.get("ubicacion", ""),
            "telefono_contacto": item.get("telefono", ""),
            "observaciones": item.get("observaciones", ""),
            "estado": item.get("estado", "Desaparecido"),
            "ubicacion_encontrado": "",
            "encontrado_por": "",
            "encontrado_por_cedula": "",
            "foto_url": "",
            "fecha_registro": map_timestamp(item.get("fecha_registro")),
            "fecha_actualizacion": map_timestamp(item.get("fecha_actualizacion") or item.get("fecha_registro")),
            "es_menor": bool(item.get("es_menor", False)),
            "fuente": "reencuentro.help",
        }
        records.append(record)
    
    output_path = os.path.join(output_dir, "reencuentro.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    
    print(f"✅ Guardado {len(records)} registros en {output_path}")
    
    if only_smoke:
        for r in records[:limit or 5]:
            print(f"  - {r['nombre']} | {r['estado']}")
    
    return records

def fetch_data(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    # Intenta con las rutas de API más probables
    urls = [
        "https://reencuentro.help/api/personas",
        "https://reencuentro.help/api/v1/personas",
        "https://reencuentro.help/data.json",
        "https://reencuentro.help/personas.json",
    ]
    for url in urls:
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                print(f"✅ API encontrada: {url}")
                if isinstance(data, dict) and 'data' in data:
                    return data['data'][:limit] if limit else data['data']
                if isinstance(data, list):
                    return data[:limit] if limit else data
        except Exception as e:
            print(f"Error con {url}: {e}")
            continue
    
    # Si no hay API, intentar con BeautifulSoup
    try:
        from bs4 import BeautifulSoup
        resp = requests.get("https://reencuentro.help", timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Busca contenedores de personas (ajusta los selectores según lo que veas)
        items = soup.find_all('div', class_=lambda c: c and ('person' in c.lower() or 'card' in c.lower() or 'item' in c.lower()))
        results = []
        for item in items:
            nombre = item.find(['h2', 'h3', 'h4', 'span'], class_=lambda c: c and ('name' in c.lower() or 'title' in c.lower()))
            nombre = nombre.get_text(strip=True) if nombre else ''
            ubicacion = item.find(['span', 'p'], class_=lambda c: c and ('location' in c.lower() or 'dir' in c.lower()))
            ubicacion = ubicacion.get_text(strip=True) if ubicacion else ''
            telefono = item.find(['span', 'p'], class_=lambda c: c and ('phone' in c.lower() or 'tel' in c.lower()))
            telefono = telefono.get_text(strip=True) if telefono else ''
            if nombre:
                results.append({
                    'nombre': nombre,
                    'ubicacion': ubicacion,
                    'telefono': telefono,
                    'estado': 'Desaparecido',
                    'fecha_registro': datetime.now().isoformat(),
                })
        return results[:limit] if limit else results
    except Exception as e:
        print(f"❌ Error con BeautifulSoup: {e}")
        return []

if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        run(tmpdir, limit=5, only_smoke=True)