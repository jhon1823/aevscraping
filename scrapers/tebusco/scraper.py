"""
Scraper para tebusco.app
"""

import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Helpers básicos (en caso de que no existan en consolidator)
def map_id(value):
    return str(value) if value is not None else None

def map_timestamp(value):
    if not value:
        return datetime.utcnow().isoformat()
    return value

from playwright.sync_api import sync_playwright

def run(output_dir: str, limit: Optional[int] = None, only_smoke: bool = False) -> List[Dict[str, Any]]:
    """
    Ejecuta el scraper de tebusco.app y devuelve los registros en el esquema unificado.
    """
    print("🕷️ Scrapeando tebusco.app con Playwright...")
    
    data = fetch_data_playwright(limit)
    
    if not data:
        print("⚠️ No se encontraron datos en tebusco.app")
        return []
    
    print(f"📊 Obtenidos {len(data)} registros")
    
    records = []
    for item in data:
        # Mapeo genérico (ajusta los nombres de campo según lo que extraigas)
        record = {
            "id": map_id(item.get("id") or f"tebusco_{hash(item.get('nombre', ''))}"),
            "nombre": item.get("nombre", ""),
            "cedula": item.get("cedula", ""),
            "edad": item.get("edad", ""),
            "ultima_ubicacion": item.get("ubicacion", ""),
            "telefono_contacto": item.get("telefono", ""),
            "observaciones": item.get("observaciones", ""),
            "estado": item.get("estado", "Desaparecido"),
            "ubicacion_encontrado": item.get("ubicacion_encontrado", ""),
            "encontrado_por": item.get("encontrado_por", ""),
            "encontrado_por_cedula": item.get("encontrado_por_cedula", ""),
            "foto_url": item.get("foto_url", ""),
            "fecha_registro": map_timestamp(item.get("fecha_registro")),
            "fecha_actualizacion": map_timestamp(item.get("fecha_actualizacion") or item.get("fecha_registro")),
            "es_menor": bool(item.get("es_menor", False)),
            "fuente": "tebusco.app",
        }
        records.append(record)
    
    # Guardar JSON
    output_path = os.path.join(output_dir, "tebusco.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    
    print(f"✅ Guardado {len(records)} registros en {output_path}")
    
    if only_smoke:
        print(f"🔍 Primeros {limit or 5} registros de tebusco.app:")
        for r in records[:limit or 5]:
            print(f"  - {r['nombre']} | {r['estado']} | {r['ultima_ubicacion']}")
    
    return records

def fetch_data_playwright(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Obtiene los datos de tebusco.app usando Playwright.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        
        try:
            print("🌐 Cargando tebusco.app...")
            page.goto("https://tebusco.app", wait_until="networkidle", timeout=60000)
            
            # ⚠️ GUARDAMOS EL HTML PARA INSPECCIONARLO
            html_path = os.path.join(os.path.dirname(__file__), "tebusco_debug.html")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(page.content())
            print(f"📄 HTML guardado en {html_path} para inspección")
            
            # Intenta encontrar las tarjetas de personas (¡AJUSTA ESTOS SELECTORES!)
            # Por ahora, buscamos cualquier elemento que contenga texto relevante
            items = page.evaluate("""
                () => {
                    const results = [];
                    // Busca elementos que parezcan tarjetas de personas
                    // TIP: Inspecciona la página y reemplaza estos selectores
                    const cards = document.querySelectorAll('.card, .person-item, .list-group-item, [class*="person"], [class*="card"]');
                    
                    cards.forEach((card, index) => {
                        // Extrae texto de los elementos comunes
                        const nombre = card.querySelector('h1, h2, h3, h4, .name, .title')?.innerText?.trim() || 
                                      card.innerText.split('\\n')[0]?.trim() || `Persona ${index+1}`;
                        
                        // Busca patrones de ubicación, teléfono, etc.
                        const text = card.innerText;
                        const ubicacion = text.match(/ubicacion|ciudad|estado|location/i)?.[0] || '';
                        const telefono = text.match(/\\d{4}-?\\d{4}/)?.[0] || '';
                        
                        results.push({
                            nombre: nombre,
                            ubicacion: ubicacion,
                            telefono: telefono,
                            edad: '',
                            estado: 'Desaparecido',
                            observaciones: text.substring(0, 200),
                        });
                    });
                    
                    return results;
                }
            """)
            
            browser.close()
            
            # Si no encontramos nada, devolvemos un registro de prueba
            if not items:
                print("⚠️ No se encontraron elementos. Revisa el HTML guardado en tebusco_debug.html")
                # Ejemplo de datos de prueba para no romper el pipeline
                items = [{
                    "nombre": "Ejemplo tebusco",
                    "ubicacion": "Caracas",
                    "telefono": "0412-0000000",
                    "edad": "",
                    "estado": "Desaparecido",
                }]
            
            return items[:limit] if limit else items
            
        except Exception as e:
            print(f"❌ Error al scrapear tebusco.app: {e}")
            browser.close()
            return []

# Para probar el scraper de forma independiente
if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        run(tmpdir, limit=5, only_smoke=True)