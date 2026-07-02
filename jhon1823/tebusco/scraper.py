"""
Scraper para tebusco.app — Portal de personas desaparecidas y localizadas.

Fuente ORIGINAL. Las siguientes páginas son alias/mirrors de tebusco.app y
comparten exactamente el mismo backend (mismo index.html, sin datos propios):
  - reencuentra-ve.vercel.app  -> sirve tebusco.app/index.html
  - reunevzla.org              -> sirve tebusco.app/index.html
  - encuentralove.com          -> redirige a tebusco.app/index.html
  - terremotovenezuela.app     -> redirige a tebusco.app/index.html
Esos 4 scrapers (jhon1823/reencuentra, jhon1823/reunevzla,
jhon1823/encuentralove, jhon1823/terremotovenezuela) delegan a este módulo.

API: POST https://tebusco.app/tebusco-portero.php  (body JSON: {"op": ..., ...})
  Operaciones públicas verificadas:
    op='desaparecidos'    -> 100 registros más recientes en estado 'search'
    op='buscar', q=texto  -> búsqueda libre (máx. ~80 filas por consulta), todos los estados
    op='contadores'       -> totales por estado (usado solo para diagnóstico)

No existe paginación/cursor. Estrategia de cobertura: combinar 'desaparecidos'
con 'buscar' recorriendo el alfabeto (a-z) y los dígitos (0-9), deduplicando
por 'uid'. Esto cubre varios cientos de registros (el total en la base de
datos es mucho mayor, pero el resto no es accesible vía la API pública).

Estados crudos del campo 'state' (verificados contra la API en vivo):
  search   -> No aparece / se busca      -> normalizado: "Desaparecido"
  hurt     -> Herido/a                   -> normalizado: "Desaparecido"
  located  -> Localizado/a (sin confirmar) -> normalizado: "Localizado"
  safe     -> A salvo                    -> normalizado: "Localizado"
  reunited -> Con familia / reencontrado -> normalizado: "Localizado"
  gone     -> Información sensible/caso cerrado -> normalizado: "Localizado"
El detalle del estado crudo se conserva en 'observaciones' y en el campo
extra '_state_raw' para no perder información al normalizar a los dos
estados que usa el pipeline (Desaparecido/Localizado).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

PORTERO_URL = "https://tebusco.app/tebusco-portero.php"
BASE_URL = "https://tebusco.app"
REQUEST_DELAY = 0.4  # segundos entre peticiones (cortesía con el servidor)
REQUEST_TIMEOUT = 30
RETRIES = 3

# Caracteres usados para recorrer op='buscar' y maximizar cobertura
SEARCH_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789"

# Mapa de 'state' crudo -> estado normalizado del esquema unificado
STATE_MAP = {
    "search": "Desaparecido",
    "hurt": "Desaparecido",
    "located": "Localizado",
    "safe": "Localizado",
    "reunited": "Localizado",
    "gone": "Localizado",
}

# Etiquetas legibles del estado crudo (para observaciones)
STATE_LABELS = {
    "search": "No aparece",
    "hurt": "Herido/a",
    "located": "Localizado/a (sin confirmar)",
    "safe": "A salvo",
    "reunited": "Con familia",
    "gone": "Información sensible",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts_to_iso(ts_ms) -> Optional[str]:
    """Convierte timestamp en milisegundos (epoch) a ISO 8601 UTC."""
    if not ts_ms:
        return None
    try:
        dt = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OSError, ValueError, TypeError):
        return None


def _normalize(raw: dict) -> dict:
    """Transforma un registro crudo de tebusco-portero.php al esquema unificado de 16 campos."""
    uid = raw.get("uid") or ""
    state_raw = raw.get("state") or ""
    estado = STATE_MAP.get(state_raw, "Desaparecido")
    place = raw.get("place") or ""

    msg = raw.get("msg") or ""
    label = STATE_LABELS.get(state_raw, state_raw)
    observaciones = f"[{label}] {msg}".strip() if label else msg

    es_localizado = estado == "Localizado"

    fecha_registro = _ts_to_iso(raw.get("ts")) or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fecha_actualizacion = raw.get("updated_at") or fecha_registro

    return {
        "id": uid,
        "nombre": raw.get("name") or "",
        "cedula": raw.get("cid") or "",
        "edad": "",  # no disponible en esta fuente
        "ultima_ubicacion": place,
        "telefono_contacto": raw.get("phone") or "",
        "observaciones": observaciones,
        "estado": estado,
        "ubicacion_encontrado": place if es_localizado else "",
        "encontrado_por": (raw.get("by_who") or "") if es_localizado else "",
        "encontrado_por_cedula": "",  # no disponible
        "foto_url": "",  # no disponible en la API pública
        "fecha_registro": fecha_registro,
        "fecha_actualizacion": fecha_actualizacion,
        "es_menor": False,  # no disponible en esta fuente
        "fuente": "tebusco.app",
        # --- campos extra fuera del esquema de 16 (trazabilidad, ignorados por el pipeline) ---
        "_uid": uid,
        "_state_raw": state_raw,
        "_color_pulsera": raw.get("color_pulsera"),
        "_codigo_pulsera": raw.get("codigo_pulsera"),
    }


# ---------------------------------------------------------------------------
# Fetcher con reintentos
# ---------------------------------------------------------------------------

def _post(session: requests.Session, payload: dict, retries: int = RETRIES) -> list:
    """POST al portero con reintentos y backoff. Devuelve lista de filas crudas (o [] en error)."""
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.post(PORTERO_URL, json=payload, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "error" in data:
                print(f"    [warn] API error para {payload}: {data['error']}")
                return []
            return []
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt == retries:
                print(f"    [error] {payload} -> {exc} (agotados {retries} intentos)")
                return []
            wait = attempt * 2
            print(f"    [retry {attempt}/{retries}] {payload} -> {exc} — esperando {wait}s")
            time.sleep(wait)
    print(f"    [error] {payload} -> {last_error}")
    return []


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def run(output_dir, limit: Optional[int] = None, only_smoke: bool = False) -> list:
    """
    Extrae registros de tebusco.app y los guarda en output_dir/tebusco.json.

    Estrategia de extracción:
      1. op='desaparecidos' -> 100 registros más recientes en estado 'search'.
      2. op='buscar' recorriendo a-z y 0-9 -> registros en todos los estados.
      (Se omite el paso 2 si only_smoke=True, para pruebas rápidas.)

    Args:
        output_dir:  Carpeta de salida.
        limit:       Máximo de registros a conservar (None = sin límite).
        only_smoke:  Si True, solo ejecuta el paso 1 (~100 registros) para prueba rápida.

    Returns:
        Lista de registros normalizados (esquema unificado de 16 campos).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "tebusco.json"

    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; TeBuscoScraper/1.0)",
        "Referer": "https://tebusco.app/",
        "Origin": "https://tebusco.app",
    })

    seen_uids = set()
    all_records = []

    def _add(raw_list):
        added = 0
        for raw in raw_list:
            uid = raw.get("uid")
            if not uid or uid in seen_uids:
                continue
            seen_uids.add(uid)
            all_records.append(_normalize(raw))
            added += 1
            if limit is not None and len(all_records) >= limit:
                break
        return added

    print("[tebusco] Paso 1: op=desaparecidos …")
    batch = _post(session, {"op": "desaparecidos"})
    added = _add(batch)
    print(f"  -> {added} registros nuevos (total: {len(all_records)})")

    if only_smoke or (limit is not None and len(all_records) >= limit):
        _save(all_records, output_file)
        _print_preview(all_records, limit)
        return all_records

    print(f"[tebusco] Paso 2: op=buscar recorriendo {len(SEARCH_CHARS)} caracteres …")
    for i, ch in enumerate(SEARCH_CHARS):
        time.sleep(REQUEST_DELAY)
        batch = _post(session, {"op": "buscar", "q": ch})
        added = _add(batch)
        if added > 0 or i % 10 == 0:
            print(f"  [{i + 1}/{len(SEARCH_CHARS)}] q='{ch}' -> +{added} (total: {len(all_records)})")
        if limit is not None and len(all_records) >= limit:
            print(f"  Límite de {limit} registros alcanzado.")
            break

    _save(all_records, output_file)
    _print_preview(all_records, limit)
    return all_records


def _save(records: list, path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"\n[tebusco] OK: {len(records)} registros guardados en {path}")


def _print_preview(records: list, limit: Optional[int]) -> None:
    print(f"[tebusco] Primeros {limit or 5} registros:")
    for r in records[: (limit or 5)]:
        print(f"  - {r['nombre']} | {r['estado']} | {r['ultima_ubicacion']}")


# ---------------------------------------------------------------------------
# Entrada directa
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scraper de tebusco.app")
    parser.add_argument("--output-dir", default="output", help="Carpeta de salida")
    parser.add_argument("--limit", type=int, default=None, help="Máx. registros")
    parser.add_argument("--smoke", action="store_true", help="Solo op=desaparecidos (prueba rápida)")
    args = parser.parse_args()

    registros = run(output_dir=args.output_dir, limit=args.limit, only_smoke=args.smoke)
    print(f"Total registros: {len(registros)}")
