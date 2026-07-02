"""
Scraper para reencuentro.help — Portal de personas desaparecidas/localizadas
tras los terremotos de Venezuela del 24 de junio de 2026.

Fuente de datos: API REST de Supabase (sin autenticación requerida)
  POST https://rwqhswywmdjqyqnpsxqw.supabase.co/functions/v1/list-records
  Payload: {"kind": "missing"|"found", "page": int, "per_page": int}

Categorías:
  - kind=missing : personas buscadas (desaparecidas)
  - kind=found   : personas localizadas (se busca a su familia)

Esquema unificado: 16 campos estándar del proyecto.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

API_URL = "https://rwqhswywmdjqyqnpsxqw.supabase.co/functions/v1/list-records"
BASE_URL = "https://reencuentro.help"
PAGE_SIZE = 24          # El servidor siempre devuelve 24; no acepta valores mayores
REQUEST_DELAY = 0.5     # segundos entre peticiones (educado con el servidor)

KINDS = ["missing", "found"]

# Mapa de kind → estado normalizado
KIND_TO_STATUS = {
    "missing": "Desaparecido",
    "found":   "Localizado",
}

# Mapa de status interno → estado normalizado
STATUS_MAP = {
    "sin_contacto": "Desaparecido",
    "abierto":      "Localizado",
    "localizado":   "Localizado",
}

# Patrón para extraer teléfono desde el campo description
PHONE_RE = re.compile(
    r"(?:contacto[:\s]*)?(\+?\d[\d\s\-\(\)\.]{6,20}\d)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_phone(text: str | None) -> str | None:
    """Extrae el primer número de teléfono encontrado en un texto libre."""
    if not text:
        return None
    match = PHONE_RE.search(text)
    if match:
        return match.group(1).strip()
    return None


def _normalize_gender(gender: str | None) -> str | None:
    mapping = {"m": "Masculino", "f": "Femenino", "unknown": None}
    if gender is None:
        return None
    return mapping.get(gender.lower(), gender)


def _build_record(raw: dict[str, Any]) -> dict[str, Any]:
    """Transforma un registro crudo de la API al esquema unificado de 16 campos del proyecto."""

    # Edad: la API devuelve age_min / age_max (suelen ser iguales)
    age = raw.get("age_min") or raw.get("age_max")
    age_str = str(age) if age is not None else ""

    # Estado: priorizar el campo status interno; fallback al kind
    raw_status = raw.get("status", "")
    status = STATUS_MAP.get(raw_status, KIND_TO_STATUS.get(raw.get("kind", ""), "Desaparecido"))
    es_localizado = status == "Localizado"

    # Teléfono: no hay campo dedicado; extraer de description si existe
    phone = _extract_phone(raw.get("description")) or ""

    # Fecha: ISO 8601 → string legible
    reported_at_raw = raw.get("reported_at")
    if reported_at_raw:
        try:
            dt = datetime.fromisoformat(reported_at_raw.replace("Z", "+00:00"))
            fecha_registro = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            fecha_registro = reported_at_raw
    else:
        fecha_registro = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    resolved_at_raw = raw.get("resolved_at")
    if resolved_at_raw:
        try:
            dt = datetime.fromisoformat(resolved_at_raw.replace("Z", "+00:00"))
            fecha_resolucion = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            fecha_resolucion = resolved_at_raw
    else:
        fecha_resolucion = None

    # fecha_actualizacion: usamos la de resolución si existe (info más reciente), si no la de registro
    fecha_actualizacion = fecha_resolucion or fecha_registro

    record_id = raw.get("id", "")
    ubicacion = raw.get("region") or ""
    ubicacion_detalle = raw.get("location_detail") or ""

    # observaciones: descripción + señas particulares, si existen
    descripcion = raw.get("description") or ""
    senas = raw.get("senas") or ""
    observaciones = descripcion
    if senas:
        observaciones = f"{observaciones} | Señas particulares: {senas}".strip(" |")

    return {
        "id":                    record_id,
        "nombre":                raw.get("display_name") or "",
        "cedula":                raw.get("cedula") or "",
        "edad":                  age_str,
        "ultima_ubicacion":      f"{ubicacion_detalle} {ubicacion}".strip() or ubicacion,
        "telefono_contacto":     phone,
        "observaciones":         observaciones,
        "estado":                status,
        "ubicacion_encontrado":  ubicacion_detalle if es_localizado else "",
        "encontrado_por":        "",  # no disponible en esta fuente
        "encontrado_por_cedula": "",  # no disponible en esta fuente
        "foto_url":              raw.get("photo_url") or "",
        "fecha_registro":        fecha_registro,
        "fecha_actualizacion":   fecha_actualizacion,
        "es_menor":              False,  # no disponible en esta fuente
        "fuente":                "reencuentro.help",
        # --- campos extra fuera del esquema de 16 (trazabilidad, ignorados por el pipeline) ---
        "_genero":               _normalize_gender(raw.get("gender")),
        "_estado_interno":       raw_status,
        "_kind":                 raw.get("kind"),
        "_source":               raw.get("source"),
        "_posible_duplicado":    raw.get("posible_duplicado", False),
        "_url_perfil":           f"{BASE_URL}/persona/{record_id}/" if record_id else None,
    }


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------

def fetch_page(
    session: requests.Session,
    kind: str,
    page: int,
    retries: int = 3,
) -> dict[str, Any]:
    """Llama al endpoint y devuelve el JSON parseado. Reintenta en caso de error."""
    payload = {"kind": kind, "page": page, "per_page": PAGE_SIZE}
    for attempt in range(1, retries + 1):
        try:
            resp = session.post(API_URL, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise ValueError(f"API error: {data}")
            return data
        except (requests.RequestException, ValueError) as exc:
            if attempt == retries:
                raise
            wait = attempt * 2
            print(f"    [retry {attempt}/{retries}] {exc} — esperando {wait}s")
            time.sleep(wait)
    raise RuntimeError("Unreachable")


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def run(
    output_dir: str | Path,
    limit: int | None = None,
    only_smoke: bool = False,
) -> list[dict[str, Any]]:
    """
    Extrae registros de reencuentro.help y los guarda en output_dir/reencuentro.json.

    Args:
        output_dir:  Carpeta donde se guarda el JSON de salida.
        limit:       Número máximo de registros a extraer (None = todos).
        only_smoke:  Si True, descarga solo la primera página de cada kind (prueba rápida).

    Returns:
        Lista de registros normalizados (esquema de 16 campos).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "reencuentro.json"

    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Accept":       "application/json",
        "User-Agent":   "Mozilla/5.0 (compatible; ReencuentroScraper/1.0)",
        "Referer":      "https://reencuentro.help/",
        "Origin":       "https://reencuentro.help",
    })

    all_records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for kind in KINDS:
        print(f"\n[reencuentro] Descargando kind='{kind}'…")

        # Primera página para saber el total
        first_page = fetch_page(session, kind, page=1)
        total = first_page.get("total", 0)
        page_size = first_page.get("pageSize", PAGE_SIZE)
        total_pages = -(-total // page_size)  # ceil division

        print(f"  Total registros: {total} | Páginas: {total_pages}")

        # Límite de páginas si only_smoke
        max_page = 1 if only_smoke else total_pages

        # Límite global de registros
        remaining = None if limit is None else (limit - len(all_records))

        for page_num in range(1, max_page + 1):
            # Reusar la primera página ya descargada
            if page_num == 1:
                data = first_page
            else:
                time.sleep(REQUEST_DELAY)
                data = fetch_page(session, kind, page=page_num)

            page_records = data.get("records", [])
            if not page_records:
                break

            for raw in page_records:
                rid = raw.get("id")
                if rid in seen_ids:
                    continue
                seen_ids.add(rid)

                normalized = _build_record(raw)
                all_records.append(normalized)

                if remaining is not None:
                    remaining -= 1
                    if remaining <= 0:
                        break

            print(
                f"  Página {page_num}/{max_page} — {len(page_records)} registros "
                f"(acumulado: {len(all_records)})"
            )

            if remaining is not None and remaining <= 0:
                print(f"  Límite de {limit} registros alcanzado.")
                break

        if limit is not None and len(all_records) >= limit:
            break

    # Guardar resultado como LISTA de registros (sin wrapper de metadata)
    # Esto es lo que espera merge_all()
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_records, f, ensure_ascii=False, indent=2)

    print(f"\n[reencuentro] OK: {len(all_records)} registros guardados en {output_file}")
    return all_records


# ---------------------------------------------------------------------------
# Entrada directa
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scraper de reencuentro.help")
    parser.add_argument("--output-dir", default="output", help="Carpeta de salida")
    parser.add_argument("--limit", type=int, default=None, help="Máx. registros")
    parser.add_argument("--smoke", action="store_true", help="Solo primera página (prueba)")
    args = parser.parse_args()

    registros = run(
        output_dir=args.output_dir,
        limit=args.limit,
        only_smoke=args.smoke,
    )
    print(f"Total registros: {len(registros)}")
    if registros:
        print("Ejemplo de registro:")
        print(json.dumps(registros[0], ensure_ascii=False, indent=2))