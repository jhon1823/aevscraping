"""
Scraper para reencuentra-ve.vercel.app

NO es un mirror de tebusco.app (error previo corregido el 2026-07-02: se
verificó en vivo que sirve HTML propio, sin ninguna referencia a "tebusco").
Es una fuente real e independiente, Next.js + Vercel, ~95k personas
registradas (hospitales, refugios, desaparecidos, encontrados).

No requiere resolver Cloudflare Turnstile para leer datos (se probó en vivo:
la ruta de búsqueda responde sin challenge). El frontend usa React Server
Components (RSC): las páginas se piden por GET con el header `RSC: 1` y
devuelven un payload de texto (no JSON convencional) que hay que parsear con
regex en vez de json.loads().

Endpoint: GET /buscar?q=<texto>&estado=<filtro>&hospital=<centro>
  Headers: {"RSC": "1", "Next-Url": "/buscar"}
  Sin autenticación.

Tope de cobertura: cada combinación de filtros devuelve como máximo ~85-90
resultados (el parámetro `n` no lo evita). Estrategia de cobertura:
  1. La propia respuesta RSC trae embebida la lista de "hospitales" (centros/
     tags) con su conteo total: hasta 1000 entradas.
  2. Para cada centro con total <= 80: una sola consulta (`hospital=<centro>`).
  3. Para centros con total > 80: se subdivide por `estado` (6 valores).
  4. Si una combinación (centro, estado) sigue topando el límite, se subdivide
     además por letra inicial (`q=<letra>`).
  5. Aparte, un barrido alfabético sin filtro de centro para capturar personas
     sin centro asignado.
  Deduplicación por uuid en todo el proceso.

Datos disponibles en la vista de lista (no se visita la ficha individual de
cada persona para no multiplicar las peticiones x1000): nombre, estado, edad
y ubicación son best-effort (algunos registros no muestran edad/ubicación en
la lista). cédula, teléfono, foto y fecha exacta no están en la lista y se
dejan vacíos/con valor por defecto, igual que en el resto de fuentes del
proyecto donde la fuente no las expone de forma masiva.
"""

import argparse
import csv
import hashlib
import json
import re
import sys
import time
import uuid
from datetime import datetime, timezone

import requests

FUENTE = "reencuentra-ve.vercel.app"
BASE = "https://reencuentra-ve.vercel.app"
SEARCH_URL = f"{BASE}/buscar"
RSC_HEADERS = {
    "RSC": "1",
    "Next-Url": "/buscar",
    "User-Agent": "Mozilla/5.0 (compatible; CentralizadorHumanitario/1.0)",
}
CAP_SAFE = 80          # por debajo del tope observado (~85-90); margen de seguridad
REQUEST_DELAY = 0.25
REQUEST_TIMEOUT = 30
RETRIES = 3

ESTADOS = ["a_salvo", "hospitalizado", "herido", "desaparecido", "encontrado", "fallecido"]
ESTADO_LABELS = ["A salvo", "Hospitalizado", "Herido", "Desaparecido", "Encontrado", "Fallecido"]
SEARCH_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789"

ESTADO_RE = re.compile(r'"(' + '|'.join(ESTADO_LABELS) + r')"')
UUID_RE = re.compile(
    r'"\$","\$L2","([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",'
    r'\{"href":"/persona/\1"'
)
NOMBRE_RE = re.compile(r'"h3",null,\{"className":"[^"]*","children":"((?:[^"\\]|\\.)*)"\}')
EDAD_RE = re.compile(r'\[(\d+),"\s*a.os')
UBIC_RE = re.compile(r'\[null,\["\$","span",null,\{"children":"([^"]*)"\}\]\]')
HOSPITALES_RE = re.compile(r'"hospitales":(\[\{.*?\}\])')

CANONICAL_COLUMNS = [
    "id", "nombre", "cedula", "edad", "ultima_ubicacion", "telefono_contacto",
    "observaciones", "estado", "ubicacion_encontrado", "encontrado_por",
    "encontrado_por_cedula", "foto_url", "fecha_registro", "fecha_actualizacion",
    "es_menor", "fuente",
]

# Estados que consideramos "resuelto" (persona ya no está en búsqueda activa)
ESTADO_LOCALIZADO = {"A salvo", "Hospitalizado", "Encontrado", "Fallecido"}


# ---------------------------------------------------------------------------
# Mapeo al esquema unificado
# ---------------------------------------------------------------------------

def map_id(val):
    if not val:
        return 0
    try:
        return uuid.UUID(str(val)).int % 9223372036854775807
    except ValueError:
        h = hashlib.sha256(str(val).encode("utf-8")).hexdigest()
        return int(h, 16) % 9223372036854775807


def map_timestamp(val):
    if not val:
        return datetime.now(timezone.utc).isoformat()
    try:
        s = str(val).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).isoformat()
    except Exception:
        return str(val)


def map_estado(label):
    return "Localizado" if label in ESTADO_LOCALIZADO else "Desaparecido"


def map_row(raw):
    """Transforma un registro crudo (ya parseado del RSC) al esquema de 16 campos."""
    nombre = (raw.get("nombre") or "").strip() or "Desconocido"
    estado_label = raw.get("estado") or "Desaparecido"
    estado = map_estado(estado_label)
    edad = None
    if raw.get("edad"):
        try:
            edad = int(raw["edad"])
        except (ValueError, TypeError):
            edad = None
    ubicacion = (raw.get("ubicacion") or "").strip() or None
    es_menor = (edad is not None and edad < 18) or nombre.lower().startswith("(menor)")

    return {
        "id": map_id(f"{FUENTE}:{raw.get('id')}"),
        "nombre": nombre,
        "cedula": "N/D",
        "edad": edad,
        "ultima_ubicacion": ubicacion,
        "telefono_contacto": None,
        "observaciones": None,
        "estado": estado,
        "ubicacion_encontrado": ubicacion if estado == "Localizado" else None,
        "encontrado_por": None,
        "encontrado_por_cedula": None,
        "foto_url": None,
        "fecha_registro": map_timestamp(None),
        "fecha_actualizacion": map_timestamp(None),
        "es_menor": es_menor,
        "fuente": FUENTE,
    }


# ---------------------------------------------------------------------------
# Fetch + parseo del payload RSC
# ---------------------------------------------------------------------------

def parse_records(content, window=1600):
    """Extrae registros crudos (id/nombre/estado/edad/ubicacion) de un payload RSC."""
    matches = list(UUID_RE.finditer(content))
    records = []
    for i, m in enumerate(matches):
        start = m.end()
        next_start = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        end = min(next_start, start + window)
        block = content[start:end]
        nm = NOMBRE_RE.search(block)
        es = ESTADO_RE.search(block)
        ed = EDAD_RE.search(block)
        ub = UBIC_RE.search(block)
        records.append({
            "id": m.group(1),
            "nombre": nm.group(1) if nm else None,
            "estado": es.group(1) if es else None,
            "edad": ed.group(1) if ed else None,
            "ubicacion": ub.group(1) if ub else None,
        })
    return records


def fetch_facets(session):
    """Descarga la lista de 'hospitales' (centros/tags) con su conteo, embebida
    en la respuesta base de /buscar."""
    content = _get(session, {})
    if not content:
        return []
    m = HOSPITALES_RE.search(content)
    if not m:
        return []
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return []


def _get(session, params, retries=RETRIES):
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(SEARCH_URL, params=params, headers=RSC_HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            # El servidor no siempre declara charset=utf-8 en el Content-Type, y
            # requests adivina mal (latin-1) -> nombres con acentos salen mojibake.
            # El payload RSC es UTF-8 real; forzarlo explícitamente.
            return resp.content.decode("utf-8")
        except requests.RequestException as e:
            if attempt == retries:
                print(f"    [error] {params} -> {e}", file=sys.stderr)
                return None
            wait = attempt * 2
            print(f"    [retry {attempt}/{retries}] {params} -> {e} — esperando {wait}s", file=sys.stderr)
            time.sleep(wait)
    return None


# ---------------------------------------------------------------------------
# Estrategia de cobertura (crawl adaptativo por facetas)
# ---------------------------------------------------------------------------

def crawl(limit=None, only_smoke=False):
    session = requests.Session()
    seen_ids = set()
    all_raw = []

    def _add(raws):
        added = 0
        for r in raws:
            rid = r.get("id")
            if not rid or rid in seen_ids:
                continue
            seen_ids.add(rid)
            all_raw.append(r)
            added += 1
            if limit is not None and len(all_raw) >= limit:
                return added
        return added

    def _done():
        return limit is not None and len(all_raw) >= limit

    def _query(params):
        time.sleep(REQUEST_DELAY)
        # 'n' pide más resultados por consulta; el servidor topa igual en ~85-90,
        # pero sin pasarlo el default es ~20 (mucho peor cobertura por request).
        full_params = {"n": 200, **params}
        content = _get(session, full_params)
        if not content:
            return []
        return parse_records(content)

    # Paso 1: baseline sin filtro (agarra lo más reciente / sin centro asignado)
    print("[reencuentra] Paso 1: baseline sin filtro…")
    base = _query({})
    added = _add(base)
    print(f"  -> {added} nuevos (total: {len(all_raw)})")

    if only_smoke:
        return all_raw

    # Paso 2: barrido alfabético sin filtro de centro
    print(f"[reencuentra] Paso 2: barrido alfabético (sin centro) {len(SEARCH_CHARS)} consultas…")
    for ch in SEARCH_CHARS:
        if _done():
            break
        added = _add(_query({"q": ch}))
        if added:
            print(f"  q='{ch}' -> +{added} (total: {len(all_raw)})")

    # Paso 3: facetas por centro/hospital (hasta 1000), con sub-división si topa el cupo
    if not _done():
        print("[reencuentra] Paso 3: descargando lista de centros/facetas…")
        facets = fetch_facets(session)
        print(f"  {len(facets)} centros encontrados")

        for i, f in enumerate(facets):
            if _done():
                break
            nombre_centro = f.get("nombre")
            total = f.get("total", 0)
            if not nombre_centro:
                continue

            if total <= CAP_SAFE:
                added = _add(_query({"hospital": nombre_centro}))
            else:
                added = 0
                for estado_val in ESTADOS:
                    if _done():
                        break
                    sub = _query({"hospital": nombre_centro, "estado": estado_val})
                    added += _add(sub)
                    if len(sub) >= CAP_SAFE:
                        # aún topa: subdividir además por letra inicial
                        for ch in SEARCH_CHARS:
                            if _done():
                                break
                            added += _add(_query({
                                "hospital": nombre_centro, "estado": estado_val, "q": ch,
                            }))

            if added or i % 50 == 0:
                print(f"  [{i + 1}/{len(facets)}] {nombre_centro!r} (~{total}) -> +{added} (total: {len(all_raw)})")

    return all_raw


def write_outputs(rows, base):
    """Escribe <base>.json y <base>.csv en el directorio actual (misma
    convención que el resto de scrapers/*: sin ruta, solo nombre base)."""
    out_json = f"{base}.json"
    out_csv = f"{base}.csv"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CANONICAL_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return out_json, out_csv


# ---------------------------------------------------------------------------
# Compatibilidad con jhon1823/run_daily.py (mientras no se migra a run.py)
# ---------------------------------------------------------------------------

def run(output_dir, limit=None, only_smoke=False):
    import os
    all_raw = crawl(limit=limit, only_smoke=only_smoke)
    rows = [map_row(r) for r in all_raw]
    os.makedirs(output_dir, exist_ok=True)
    write_outputs(rows, os.path.join(output_dir, "reencuentra"))
    print(f"[reencuentra] OK: {len(rows)} registros guardados en {output_dir}")
    return rows


# ---------------------------------------------------------------------------
# Entrada CLI (misma convención que el resto de scrapers/*)
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Scraper de reencuentra-ve.vercel.app")
    parser.add_argument("--limit", type=int, default=None, help="Límite máximo de registros (para pruebas).")
    parser.add_argument("--output", default=FUENTE.split("-")[0].split(".")[0], help="Nombre base de salida sin extensión.")
    parser.add_argument("--smoke", action="store_true", help="Solo el baseline sin filtro (prueba rápida).")
    args = parser.parse_args()

    base = args.output
    for ext in (".json", ".csv"):
        if base.endswith(ext):
            base = base[: -len(ext)]

    print("====================================================")
    print("     SCRAPER reencuentra-ve.vercel.app -> ESQUEMA    ")
    print("====================================================")

    all_raw = crawl(limit=args.limit, only_smoke=args.smoke)
    rows = [map_row(r) for r in all_raw]
    write_outputs(rows, base)

    estados = {}
    for r in rows:
        estados[r["estado"]] = estados.get(r["estado"], 0) + 1

    print(f"\nRegistros exportados: {len(rows)}")
    for estado, n in sorted(estados.items()):
        print(f"   {estado:<15}{n}")
    print(f"Archivos generados: {base}.json / {base}.csv")


if __name__ == "__main__":
    main()
