import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scraper  # noqa: E402

MAX_BIGINT = 9223372036854775807
SCHEMA_FIELDS = [
    "id", "nombre", "cedula", "edad", "ultima_ubicacion", "telefono_contacto",
    "observaciones", "estado", "ubicacion_encontrado", "encontrado_por",
    "encontrado_por_cedula", "foto_url", "fecha_registro", "fecha_actualizacion",
    "es_menor", "fuente",
]

# Fragmento real (recortado) de una respuesta RSC de /buscar, tal como lo
# devuelve el servidor, para probar parse_records() sin red.
SAMPLE_RSC = (
    '["$","$L2","974981ec-4e60-42ee-b7c8-160470e7d14f",{"href":"/persona/'
    '974981ec-4e60-42ee-b7c8-160470e7d14f","className":"flex gap-3","children":'
    '[null,["$","div",null,{"className":"min-w-0 flex-1","children":[["$","div",'
    'null,{"className":"flex items-start justify-between gap-2","children":'
    '[["$","h3",null,{"className":"font-medium","children":"María Marín"}],'
    '["$","span",null,{"className":"shrink-0","children":["$","span",null,'
    '{"className":"bg-rose-50","children":[["$","span",null,{"className":"dot"}],'
    '"Desaparecido"]}]}]]}],["$","div",null,{"className":"mt-1.5 flex flex-wrap",'
    '"children":[["$","span",null,{"children":[18," años"]}],'
    '[null,["$","span",null,{"children":"La Guaira"}]]]}]]}]]}]'
)


class TestMapId(unittest.TestCase):
    def test_stable_and_in_range(self):
        v = "reencuentra-ve.vercel.app:974981ec-4e60-42ee-b7c8-160470e7d14f"
        self.assertEqual(scraper.map_id(v), scraper.map_id(v))
        self.assertTrue(0 <= scraper.map_id(v) < MAX_BIGINT)

    def test_empty_returns_zero(self):
        self.assertEqual(scraper.map_id(None), 0)
        self.assertEqual(scraper.map_id(""), 0)


class TestMapEstado(unittest.TestCase):
    def test_resueltos_son_localizado(self):
        for label in ("A salvo", "Hospitalizado", "Encontrado", "Fallecido"):
            self.assertEqual(scraper.map_estado(label), "Localizado")

    def test_activos_son_desaparecido(self):
        for label in ("Desaparecido", "Herido"):
            self.assertEqual(scraper.map_estado(label), "Desaparecido")


class TestParseRecords(unittest.TestCase):
    def test_extrae_campos_del_bloque_rsc(self):
        records = scraper.parse_records(SAMPLE_RSC)
        self.assertEqual(len(records), 1)
        r = records[0]
        self.assertEqual(r["id"], "974981ec-4e60-42ee-b7c8-160470e7d14f")
        self.assertEqual(r["nombre"], "María Marín")
        self.assertEqual(r["estado"], "Desaparecido")
        self.assertEqual(r["edad"], "18")
        self.assertEqual(r["ubicacion"], "La Guaira")


class TestMapRow(unittest.TestCase):
    def setUp(self):
        self.raw = {
            "id": "974981ec-4e60-42ee-b7c8-160470e7d14f",
            "nombre": "María Marín",
            "estado": "Desaparecido",
            "edad": "18",
            "ubicacion": "La Guaira",
        }

    def test_has_all_16_fields(self):
        row = scraper.map_row(self.raw)
        self.assertEqual(set(row.keys()), set(SCHEMA_FIELDS))

    def test_not_null_fields(self):
        row = scraper.map_row(self.raw)
        for f in ("nombre", "cedula", "estado", "fecha_registro",
                  "fecha_actualizacion", "es_menor", "fuente"):
            self.assertIsNotNone(row[f])

    def test_mapeo_basico(self):
        row = scraper.map_row(self.raw)
        self.assertEqual(row["nombre"], "María Marín")
        self.assertEqual(row["edad"], 18)
        self.assertEqual(row["ultima_ubicacion"], "La Guaira")
        self.assertEqual(row["estado"], "Desaparecido")
        self.assertEqual(row["cedula"], "N/D")
        self.assertEqual(row["fuente"], "reencuentra-ve.vercel.app")
        self.assertFalse(row["es_menor"])

    def test_menor_por_prefijo_sin_edad(self):
        raw = dict(self.raw, nombre="(Menor) Adrian Diaz", edad=None)
        row = scraper.map_row(raw)
        self.assertTrue(row["es_menor"])

    def test_localizado_llena_ubicacion_encontrado(self):
        raw = dict(self.raw, estado="A salvo")
        row = scraper.map_row(raw)
        self.assertEqual(row["estado"], "Localizado")
        self.assertEqual(row["ubicacion_encontrado"], "La Guaira")

    def test_desaparecido_no_llena_ubicacion_encontrado(self):
        row = scraper.map_row(self.raw)
        self.assertIsNone(row["ubicacion_encontrado"])


if __name__ == "__main__":
    unittest.main()
