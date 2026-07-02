import json
import csv
import sys
import argparse
import time
import uuid
import hashlib
from datetime import datetime, timezone

import requests

# NOTA (2026-07-02): redayudavenezuela.com migró de exponer su tabla de
# Supabase directamente al cliente (vía anon key) a un endpoint propio
# '/api/data' que hace de proxy — el mismo patrón que adoptó tebusco.app
# con su 'tebusco-portero.php'. La anon key vieja ya no tiene permisos
# (401 'permission denied for table missing_persons': el rol 'anon' fue
# revocado en Supabase). El sitio ahora sirve los datos vía POST JSON a
# este endpoint, sin autenticación, con paginación de 40 registros/página.
API_URL = "https://redayudavenezuela.com/api/data"
PAGE_SIZE = 40
REQUEST_DELAY = 0.15  # segundos entre páginas (cortesía con el servidor)
REQUEST_TIMEOUT = 30
RETRIES = 3

def map_id(val):
    if not val:
        return 0
    try:
        # Convert UUID to bigint (signed 64-bit integer: max 9223372036854775807)
        return uuid.UUID(str(val)).int % 9223372036854775807
    except ValueError:
        # Fallback to standard SHA-256 hash if not a valid UUID string
        h = hashlib.sha256(str(val).encode('utf-8')).hexdigest()
        return int(h, 16) % 9223372036854775807

def map_timestamp(val):
    if not val:
        return datetime.now(timezone.utc).isoformat()
    # If it's a number (milliseconds Unix timestamp)
    if isinstance(val, (int, float)) or (isinstance(val, str) and val.isdigit()):
        try:
            return datetime.fromtimestamp(float(val) / 1000.0, timezone.utc).isoformat()
        except Exception:
            pass
    # If it's already an ISO or date string
    try:
        s = str(val).strip()
        if s.endswith('Z'):
            s = s[:-1] + '+00:00'
        dt = datetime.fromisoformat(s)
        return dt.isoformat()
    except Exception:
        return str(val)

def map_row(item):
    # nombre: text, NOT NULL
    nombre = item.get("name")
    if not nombre:
        nombre = "Desconocido"
    else:
        nombre = str(nombre).strip()
        
    # cedula: text, NOT NULL
    cedula = "N/D" # Default placeholder
    
    # edad: integer, YES NULL
    edad_raw = item.get("age")
    edad = None
    if edad_raw is not None and str(edad_raw).strip() != "":
        try:
            edad = int(float(str(edad_raw).strip()))
        except ValueError:
            pass
            
    # ultima_ubicacion: text, YES NULL
    ultima_ubicacion = item.get("last_seen")
    if ultima_ubicacion:
        ultima_ubicacion = str(ultima_ubicacion).replace("\n", " ").strip()
    else:
        ultima_ubicacion = None
        
    # telefono_contacto: text, YES NULL
    telefono_contacto = item.get("contact")
    if telefono_contacto:
        telefono_contacto = str(telefono_contacto).replace("\n", " ").strip()
    else:
        telefono_contacto = None
        
    # observaciones: text, YES NULL
    observaciones = item.get("description")
    if observaciones:
        observaciones = str(observaciones).replace("\n", " ").strip()
    else:
        observaciones = None
        
    # estado: text, NOT NULL
    status = item.get("status")
    if status == "found":
        estado = "Localizado"
    else:
        estado = "Desaparecido"

    # ubicacion_encontrado, encontrado_por, encontrado_por_cedula: YES NULL
    # (la API nueva sí entrega found_note/found_by/found_contact cuando el
    # registro está 'found'; antes no había forma de obtenerlos)
    if status == "found":
        ubicacion_encontrado = item.get("found_note") or ultima_ubicacion
        encontrado_por = item.get("found_by")
    else:
        ubicacion_encontrado = None
        encontrado_por = None
    encontrado_por_cedula = None

    # foto_url: text, YES NULL
    foto_url = item.get("photo_url")
    if foto_url:
        foto_url = str(foto_url).strip()
    else:
        foto_url = None

    # fecha_registro: timestamptz, NOT NULL
    fecha_registro = map_timestamp(item.get("ext_created"))

    # fecha_actualizacion: timestamptz, NOT NULL
    # (para 'found', preferimos located_at si existe: es la fecha real de localización)
    fecha_actualizacion = map_timestamp(item.get("located_at") or item.get("synced_at"))
    if not item.get("located_at") and not item.get("synced_at"):
        fecha_actualizacion = fecha_registro
        
    # es_menor: boolean, NOT NULL
    es_menor = bool(item.get("is_child", False))
    
    return {
        "id": map_id(item.get("id")),
        "nombre": nombre,
        "cedula": cedula,
        "edad": edad,
        "ultima_ubicacion": ultima_ubicacion,
        "telefono_contacto": telefono_contacto,
        "observaciones": observaciones,
        "estado": estado,
        "ubicacion_encontrado": ubicacion_encontrado,
        "encontrado_por": encontrado_por,
        "encontrado_por_cedula": encontrado_por_cedula,
        "foto_url": foto_url,
        "fecha_registro": fecha_registro,
        "fecha_actualizacion": fecha_actualizacion,
        "es_menor": es_menor,
        "fuente": "redayudavenezuela"
    }

def fetch_page(session, status, page, retries=RETRIES):
    """Descarga una página (40 registros) desde /api/data. Reintenta con backoff."""
    payload = {"op": "missing_search", "term": "", "status": status, "page": page}
    for attempt in range(1, retries + 1):
        try:
            resp = session.post(API_URL, json=payload, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                print(f"\nError de API en página {page}: {data}", file=sys.stderr)
                return None
            return data.get("data") or []
        except (requests.RequestException, ValueError) as e:
            if attempt == retries:
                print(f"\nError fetching página {page}: {e}", file=sys.stderr)
                return None
            wait = attempt * 2
            print(f"\n[retry {attempt}/{retries}] página {page}: {e} — esperando {wait}s", file=sys.stderr)
            time.sleep(wait)
    return None

def main():
    parser = argparse.ArgumentParser(description="Exporta la lista de personas desaparecidas de Red Ayuda Venezuela y la adapta al esquema de base de datos.")
    parser.add_argument("--status", default="active", choices=["active", "found"], help="Estado de las personas a exportar (default: active).")
    parser.add_argument("--limit", type=int, default=None, help="Límite máximo de registros a descargar (para pruebas).")
    parser.add_argument("--output", default="desaparecidos", help="Nombre base de los archivos de salida sin extensión (default: desaparecidos).")
    args = parser.parse_args()

    # Determine base name for outputs
    output_base = args.output
    if output_base.endswith('.csv'):
        output_base = output_base[:-4]
    elif output_base.endswith('.json'):
        output_base = output_base[:-5]

    output_csv = f"{output_base}.csv"
    output_json = f"{output_base}.json"

    print("====================================================")
    print("      EXPORTADOR ADAPTADO A ESQUEMA BBDD            ")
    print("====================================================")
    print(f"Estado a descargar: {args.status}")
    print(f"Archivo CSV de salida: {output_csv}")
    print(f"Archivo JSON de salida: {output_json}")
    if args.limit:
        print(f"Límite de descarga: {args.limit} registros")
    print("----------------------------------------------------")

    page = 0
    total_written = 0
    all_rows = []

    headers = [
        "id", "nombre", "cedula", "edad", "ultima_ubicacion",
        "telefono_contacto", "observaciones", "estado",
        "ubicacion_encontrado", "encontrado_por", "encontrado_por_cedula",
        "foto_url", "fecha_registro", "fecha_actualizacion", "es_menor", "fuente"
    ]

    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; RedAyudaVenezuelaScraper/1.0)",
        "Referer": "https://redayudavenezuela.com/desaparecidos",
    })

    try:
        while True:
            if args.limit and total_written >= args.limit:
                print(f"\nLímite de {args.limit} registros alcanzado.")
                break

            print(f"\rDescargando página {page} (acumulado: {total_written})... ", end="", flush=True)

            chunk = fetch_page(session, args.status, page)
            if chunk is None:
                print("Error persistente. Deteniendo descarga.")
                break

            if not chunk:
                print("\nNo hay más registros disponibles.")
                break

            for item in chunk:
                row = map_row(item)
                all_rows.append(row)
                total_written += 1
                if args.limit and total_written >= args.limit:
                    break

            # Si la página vino incompleta, era la última.
            if len(chunk) < PAGE_SIZE:
                break

            page += 1
            time.sleep(REQUEST_DELAY)

        # Write files if we have data
        if all_rows:
            # 1. Write CSV
            with open(output_csv, "w", newline="", encoding="utf-8-sig") as csv_file:
                csv_writer = csv.DictWriter(csv_file, fieldnames=headers, extrasaction="ignore")
                csv_writer.writeheader()
                csv_writer.writerows(all_rows)
            
            # 2. Write JSON
            with open(output_json, "w", encoding="utf-8") as json_file:
                json.dump(all_rows, json_file, indent=2, ensure_ascii=False)

            print(f"\nDescarga finalizada con éxito. Se guardaron {len(all_rows)} registros en:")
            print(f"  - CSV: '{output_csv}'")
            print(f"  - JSON: '{output_json}'")
        else:
            print("\nNo se encontraron registros para exportar.")

    except KeyboardInterrupt:
        print("\nDescarga cancelada por el usuario.")

if __name__ == "__main__":
    main()
