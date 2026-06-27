"""
send_to_api.py

Envía el archivo XLSX consolidado a la API de aquiestoyvenezuela.com.
Se ejecuta después de generate_xlsx.py en la corrida diaria.

Requiere: pip install requests
"""

import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("Error: requests no está instalado. Ejecuta: pip install requests", file=sys.stderr)
    sys.exit(1)

BASE_DIR = Path(__file__).parent
XLSX_FILE = BASE_DIR / "datos_consolidados" / "todos_registros.xlsx"

API_URL    = "https://aquiestoyvenezuela.com/api/post_carga_doc.php"
API_KEY    = "%iRjRkN&Ve8+YP9*U2R1voNvcQq1d^6F"
ID_USUARIO = "1"
ID_HOSPITAL = "1"


def main():
    print("====================================================")
    print("         ENVÍO DE DATOS A API                       ")
    print("====================================================")

    if not XLSX_FILE.exists():
        print(f"Error: No se encontró el archivo XLSX en {XLSX_FILE}", file=sys.stderr)
        sys.exit(1)

    size_kb = XLSX_FILE.stat().st_size / 1024
    print(f"Archivo: {XLSX_FILE.name} ({size_kb:.1f} KB)")
    print(f"Destino: {API_URL}")

    try:
        with open(XLSX_FILE, "rb") as f:
            response = requests.post(
                API_URL,
                headers={"X-API-Key": API_KEY},
                files={
                    "file": (
                        XLSX_FILE.name,
                        f,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                },
                data={
                    "id_usuario": ID_USUARIO,
                    "id_hospital": ID_HOSPITAL
                },
                timeout=120
            )

        print(f"Respuesta HTTP: {response.status_code}")
        # Mostrar solo los primeros 500 chars para no saturar el log
        print(f"Respuesta: {response.text[:500]}")

        if response.status_code == 200:
            print("Envío exitoso.")
        else:
            print(f"Error: la API respondió con HTTP {response.status_code}", file=sys.stderr)
            sys.exit(1)

    except requests.exceptions.Timeout:
        print("Error: timeout al conectar con la API (120s).", file=sys.stderr)
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"Error de conexión: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
