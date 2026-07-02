"""
run_daily.py

Orquestador de la corrida diaria de scraping de personas desaparecidas Venezuela.
Ejecuta en secuencia todos los scrapers, consolida datos, aplica limpieza,
genera XLSX y llama a la API.

Uso manual:  python run_daily.py
Programado:  configurar con setup_tarea_diaria.ps1
"""

import subprocess
import sys
import json
import zipfile
import re
from collections import defaultdict
from pathlib import Path
from datetime import datetime, timezone

# ===== SCRAPERS UBICADOS EN LA CARPETA JHON1823 =====
from jhon1823.hospitalesenvenezuela import scraper as hospitalesenvenezuela
from jhon1823.localizapacientes import scraper as localizapacientes
from jhon1823.reencuentro import scraper as reencuentro
from jhon1823.tebusco import scraper as tebusco
from jhon1823.reencuentra import scraper as reencuentra
from jhon1823.reunevzla import scraper as reunevzla
from jhon1823.encuentralove import scraper as encuentralove
from jhon1823.terremotovenezuela import scraper as terremotovenezuela
# from jhon1823.venezuelareporta import scraper as venezuelareporta  # (descomentar cuando esté listo)

BASE_DIR   = Path(__file__).parent
AMILKIR    = BASE_DIR / "Amilkir"
CHIKI      = BASE_DIR / "chiki"
JHON1823   = BASE_DIR / "jhon1823"
DATOS      = BASE_DIR / "datos_consolidados"
LOGS       = BASE_DIR / "logs"

_log_lines = []


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    _log_lines.append(line)


def run_step(label, cmd, cwd=None):
    log(f">>> {label}")
    result = subprocess.run(cmd, cwd=str(cwd or BASE_DIR))
    if result.returncode != 0:
        log(f"ERROR: '{label}' terminó con código {result.returncode}")
        return False
    log(f"OK:  {label}")
    return True


# ============================================================
# LÓGICA DE LIMPIEZA
# ============================================================
def limpiar_y_deduplicar(records):
    """
    Aplica las reglas de limpieza y deduplicación acordadas en el equipo:
    1. Filtra registros sin nombre válido (excluye hospitales, centros, etc.)
    2. Separa nombres compuestos (ej. "Matias y Mateo Peña González")
    3. Deduplica priorizando "Localizado" sobre "Desaparecido"
    4. Usa nombre + edad + ciudad para no fusionar homónimos reales
    """
    print("🧹 Aplicando limpieza y deduplicación...")

    # FILTRAR REGISTROS QUE NO SEAN DICCIONARIOS O SEAN None
    records = [r for r in records if isinstance(r, dict)]

    # ===== PASO 1: Filtrar registros sin nombre válido =====
    def tiene_nombre_valido(r):
        nombre = str(r.get('nombre', '')).strip()
        if not nombre:
            return False
        if len(nombre) < 3:
            return False
        palabras = nombre.split()
        if len(palabras) == 1:
            if len(palabras[0]) < 3:
                return False
            # Evitar nombres genéricos de hospitales
            hospital_keywords = ['hospital', 'clinica', 'centro', 'maternidad', 'cdi', 'ambulatorio']
            if any(k in nombre.lower() for k in hospital_keywords):
                return False
            return True
        return True

    filtered = [r for r in records if tiene_nombre_valido(r)]
    print(f"  - Filtrados {len(records) - len(filtered)} registros sin nombre válido")

    # ===== PASO 2: Separar nombres compuestos =====
    def separar_nombres_compuestos(record):
        nombre = str(record.get('nombre', '')).strip()
        if ' y ' in nombre or ' & ' in nombre or ',' in nombre:
            nombre_limpio = re.sub(r'[,&]', ' y', nombre)
            partes = nombre_limpio.split(' y ')
            parte_con_apellido = None
            for parte in reversed(partes):
                if len(parte.strip().split()) > 1:
                    parte_con_apellido = parte.strip()
                    break
            if parte_con_apellido:
                palabras_apellido = parte_con_apellido.split()
                apellidos_heredados = ' '.join(palabras_apellido[1:]) if len(palabras_apellido) > 1 else ''
                resultados = []
                for parte in partes:
                    parte = parte.strip()
                    if len(parte.split()) == 1 and apellidos_heredados:
                        nuevo_nombre = f"{parte} {apellidos_heredados}".strip()
                    else:
                        nuevo_nombre = parte
                    nuevo_record = record.copy()
                    nuevo_record['nombre'] = nuevo_nombre
                    resultados.append(nuevo_record)
                return resultados
        return [record]

    expanded = []
    for r in filtered:
        expanded.extend(separar_nombres_compuestos(r))
    print(f"  - Separados nombres compuestos: {len(expanded)} registros generados")

    # ===== PASO 3: Deduplicar priorizando 'Localizado' =====
    grupos = defaultdict(list)
    for r in expanded:
        nombre = str(r.get('nombre', '')).strip().lower()
        edad = str(r.get('edad', '')).strip()
        ciudad = str(r.get('ultima_ubicacion', '')).strip().lower()
        if not ciudad:
            ciudad = str(r.get('ciudad', '')).strip().lower() or 'desconocida'
        clave = f"{nombre}|{edad}|{ciudad}"
        grupos[clave].append(r)

    prioridad = {'Localizado': 1, 'Desaparecido': 2}
    deduped = []
    for clave, grupo in grupos.items():
        if len(grupo) == 1:
            deduped.append(grupo[0])
            continue
        grupo_ordenado = sorted(
            grupo,
            key=lambda x: prioridad.get(x.get('estado', ''), 3)
        )
        deduped.append(grupo_ordenado[0])

    print(f"  - Deduplicados: {len(expanded) - len(deduped)} duplicados eliminados")
    print(f"  - Registros finales: {len(deduped)}")

    return deduped


def merge_all():
    """Combina los outputs de todos los scrapers y aplica limpieza."""
    DATOS.mkdir(exist_ok=True)
    todos_path = DATOS / "todos_registros.json"

    # Cargar store existente
    store = {}
    if todos_path.exists():
        try:
            for r in json.loads(todos_path.read_text(encoding="utf-8")):
                key = f"{r.get('id')}|{r.get('fuente', '')}"
                store[key] = r
            log(f"Store existente cargado: {len(store)} registros")
        except Exception as e:
            log(f"Advertencia al cargar store: {e}  (se iniciará vacío)")

    # Fuentes tradicionales (carpetas Amilkir y chiki)
    sources = [
        AMILKIR / "personas_venezuela.json",
        CHIKI   / "desaparecidos_redayudavenezuela.json",
        CHIKI   / "localizados_redayudavenezuela.json",
        CHIKI   / "personas_desaparecidas_venezuela_parsed.json",
    ]

    for src in sources:
        if not src.exists():
            log(f"  Omitiendo (no encontrado): {src.name}")
            continue
        try:
            records = json.loads(src.read_text(encoding="utf-8"))
            nuevos = 0
            for r in records:
                key = f"{r.get('id')}|{r.get('fuente', '')}"
                if key not in store:
                    nuevos += 1
                store[key] = r
            log(f"  {src.name}: {len(records)} registros ({nuevos} nuevos)")
        except Exception as e:
            log(f"  Error al procesar {src.name}: {e}")

    # ===== Fuentes desde la carpeta jhon1823 =====
    for json_file in JHON1823.glob("*.json"):
        if json_file.name == "todos_registros.json":
            continue
        try:
            records = json.loads(json_file.read_text(encoding="utf-8"))
            nuevos = 0
            for r in records:
                key = f"{r.get('id')}|{r.get('fuente', '')}"
                if key not in store:
                    nuevos += 1
                store[key] = r
            log(f"  {json_file.name}: {len(records)} registros ({nuevos} nuevos)")
        except Exception as e:
            log(f"  Error al procesar {json_file.name}: {e}")

    # ===== Fuentes desde datos_consolidados (scrapers nuevos) =====
    for json_file in DATOS.glob("*.json"):
        if json_file.name == "todos_registros.json":
            continue
        try:
            records = json.loads(json_file.read_text(encoding="utf-8"))
            nuevos = 0
            for r in records:
                key = f"{r.get('id')}|{r.get('fuente', '')}"
                if key not in store:
                    nuevos += 1
                store[key] = r
            log(f"  {json_file.name}: {len(records)} registros ({nuevos} nuevos)")
        except Exception as e:
            log(f"  Error al procesar {json_file.name}: {e}")

    all_records = list(store.values())

    # ===== APLICAR LIMPIEZA =====
    all_records_clean = limpiar_y_deduplicar(all_records)

    # Guardar JSON limpio
    todos_path.write_text(
        json.dumps(all_records_clean, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    log(f"Store consolidado y limpiado: {len(all_records_clean)} registros totales")
    return len(all_records_clean)


def compress_json():
    """Comprime el archivo JSON consolidado en un archivo ZIP."""
    todos_path = DATOS / "todos_registros.json"
    zip_path = DATOS / "todos_registros.zip"
    if not todos_path.exists():
        log(f"Advertencia: No se encontró {todos_path.name} para comprimir")
        return False
    try:
        log(f"Comprimiendo {todos_path.name} a {zip_path.name}...")
        t0 = datetime.now(timezone.utc)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(todos_path, arcname=todos_path.name)
        elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
        size_mb = zip_path.stat().st_size / (1024 * 1024)
        log(f"OK: ZIP generado ({size_mb:.2f} MB) en {elapsed:.1f}s")
        return True
    except Exception as e:
        log(f"Error al comprimir a ZIP: {e}")
        return False


def save_log():
    LOGS.mkdir(exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_path = LOGS / f"{date_str}.log"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write("\n".join(_log_lines) + "\n\n")
    print(f"Log guardado en: {log_path}")


def main():
    t0 = datetime.now(timezone.utc)
    log("=" * 52)
    log("INICIO CORRIDA DIARIA — SCRAPING VENEZUELA AEV")
    log("=" * 52)

    # ===== SCRAPERS DESDE CARPETA JHON1823 =====
    log("Ejecutando scrapers desde jhon1823...")

    # hospitalesenvenezuela
    try:
        log(">>> hospitalesenvenezuela")
        hosp_records = hospitalesenvenezuela.run(str(DATOS))
        log(f"OK: hospitalesenvenezuela -> {len(hosp_records)} registros")
    except Exception as e:
        log(f"ERROR en hospitalesenvenezuela: {e}")

    # localizapacientes
    try:
        log(">>> localizapacientes")
        loc_records = localizapacientes.run(str(DATOS))
        log(f"OK: localizapacientes -> {len(loc_records)} registros")
    except Exception as e:
        log(f"ERROR en localizapacientes: {e}")

    # reencuentro
    try:
        log(">>> reencuentro")
        reenc_records = reencuentro.run(str(DATOS))
        log(f"OK: reencuentro -> {len(reenc_records)} registros")
    except Exception as e:
        log(f"ERROR en reencuentro: {e}")

    # tebusco (fuente principal — API tebusco-portero.php)
    try:
        log(">>> tebusco")
        tebusco_records = tebusco.run(str(DATOS))
        log(f"OK: tebusco -> {len(tebusco_records)} registros")
    except Exception as e:
        log(f"ERROR en tebusco: {e}")

    # reencuentra-ve.vercel.app (mirror de tebusco.app)
    try:
        log(">>> reencuentra")
        reencuentra_records = reencuentra.run(str(DATOS))
        log(f"OK: reencuentra -> {len(reencuentra_records)} registros")
    except Exception as e:
        log(f"ERROR en reencuentra: {e}")

    # reunevzla.org (mirror de tebusco.app)
    try:
        log(">>> reunevzla")
        reunevzla_records = reunevzla.run(str(DATOS))
        log(f"OK: reunevzla -> {len(reunevzla_records)} registros")
    except Exception as e:
        log(f"ERROR en reunevzla: {e}")

    # encuentralove.com (redirige a tebusco.app)
    try:
        log(">>> encuentralove")
        encuentralove_records = encuentralove.run(str(DATOS))
        log(f"OK: encuentralove -> {len(encuentralove_records)} registros")
    except Exception as e:
        log(f"ERROR en encuentralove: {e}")

    # terremotovenezuela.app (redirige a tebusco.app)
    try:
        log(">>> terremotovenezuela")
        terremotovenezuela_records = terremotovenezuela.run(str(DATOS))
        log(f"OK: terremotovenezuela -> {len(terremotovenezuela_records)} registros")
    except Exception as e:
        log(f"ERROR en terremotovenezuela: {e}")

    # venezuelareporta (comentado hasta que esté listo)
    # try:
    #     log(">>> venezuelareporta")
    #     venezuela_records = venezuelareporta.run(str(DATOS))
    #     log(f"OK: venezuelareporta -> {len(venezuela_records)} registros")
    # except Exception as e:
    #     log(f"ERROR en venezuelareporta: {e}")

    # ===== SCRAPERS TRADICIONALES (Amilkir / chiki) =====
    # 1. Venezuela Te Busca (Node.js, modo incremental)
    run_step(
        "venezuelatebusca.com",
        ["node", "scraper.js", "--update"],
        cwd=AMILKIR
    )

    # 2. Red Ayuda Venezuela — activos
    run_step(
        "redayudavenezuela.com (activos)",
        [sys.executable, "scraper.py", "--status", "active",
         "--output", "desaparecidos_redayudavenezuela"],
        cwd=CHIKI
    )

    # 3. Red Ayuda Venezuela — localizados
    run_step(
        "redayudavenezuela.com (localizados)",
        [sys.executable, "scraper.py", "--status", "found",
         "--output", "localizados_redayudavenezuela"],
        cwd=CHIKI
    )

    # 4. Terremoto — Playwright headless
    ok_terremoto = run_step(
        "desaparecidosterremotovenezuela.com (Playwright)",
        [sys.executable, "scraper_terremoto.py"],
        cwd=CHIKI
    )

    # 5. Parse datos terremoto (depende del paso anterior)
    if ok_terremoto:
        run_step(
            "parse_desaparecidos.py",
            [sys.executable, "parse_desaparecidos.py"],
            cwd=CHIKI
        )
    else:
        log("SKIP: parse_desaparecidos.py (scraper terremoto falló)")

    # 6. Consolidar todos los datos
    log("Consolidando datos de todas las fuentes...")
    merge_all()

    # 6.5. Comprimir JSON a ZIP
    compress_json()

    # 7. Generar XLSX
    ok_xlsx = run_step(
        "generate_xlsx.py",
        [sys.executable, str(BASE_DIR / "generate_xlsx.py")]
    )

    # 8. Enviar a API
    if ok_xlsx:
        run_step(
            "send_to_api.py",
            [sys.executable, str(BASE_DIR / "send_to_api.py")]
        )
    else:
        log("SKIP: send_to_api.py (generación XLSX falló)")

    elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
    log(f"FIN CORRIDA DIARIA ({elapsed:.0f}s)")
    save_log()


if __name__ == "__main__":
    main()

