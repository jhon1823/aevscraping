# Scraper: reencuentra-ve.vercel.app

Personas registradas en hospitales/refugios/desaparecidos tras el sismo en
Venezuela. Next.js + Vercel, React Server Components. **No es un mirror de
tebusco.app** (error de una evaluación previa, corregido el 2026-07-02:
verificado en vivo que sirve HTML propio, sin ninguna referencia a "tebusco").

No requiere resolver Cloudflare Turnstile para leer datos — se probó en vivo
y la ruta de búsqueda responde sin challenge (Turnstile, si existe, parece
estar solo en el formulario de "Reportar").

## Endpoint

| Endpoint | Uso |
|---|---|
| `GET /buscar?q=&estado=&hospital=&n=` | Búsqueda/listado. Respuesta RSC (no JSON), hay que parsear con regex. |

Headers obligatorios: `RSC: 1`, `Next-Url: /buscar`. Sin autenticación.

`n` pide más resultados por consulta (probado hasta 200); el servidor topa
igual en **~85-90 resultados por combinación de filtros**, pero sin pasarlo
el default es ~20 (mucho peor). `estado` acepta: `a_salvo`, `hospitalizado`,
`herido`, `desaparecido`, `encontrado`, `fallecido`. `hospital` acepta
cualquiera de los ~1000 valores de la faceta "hospitales" (hospitales,
refugios, centros de acopio, y curiosamente también `male`/`female`).

## Formato de respuesta (RSC, no JSON)

Next.js sirve un payload de texto con los componentes React serializados.
La lista de resultados aparece como bloques con este patrón (simplificado):

```
["$","$L2","<uuid>",{"href":"/persona/<uuid>", ... "children":"<NOMBRE>"} ...
  ..."<A salvo|Hospitalizado|Herido|Desaparecido|Encontrado|Fallecido>"...
  ...[<edad>," años"]...  [null,["$","span",null,{"children":"<UBICACION>"}]]
```

`parse_records()` extrae `id/nombre/estado/edad/ubicacion` con regex sobre
este patrón. La faceta completa de centros (`"hospitales":[{"nombre","total"}]`)
también viene embebida como JSON válido en la primera respuesta y se extrae
con `fetch_facets()`.

**Limitación conocida:** cédula, teléfono, foto y fecha exacta de reporte no
aparecen en la vista de lista (solo en la ficha individual `/persona/<uuid>`,
que no se visita para no multiplicar las peticiones ×1000). Quedan con su
valor por defecto (`"N/D"` / `None` / fecha de la corrida).

## Estrategia de cobertura (el listado topa en ~85-90 por consulta)

Con ~95k personas registradas y un tope duro por consulta, hace falta
combinar filtros para maximizar cobertura:

1. Baseline sin filtro (`n=200`).
2. Barrido alfabético sin centro: `q=a..z,0..9` (36 consultas).
3. Por cada uno de los ~1000 centros de la faceta `hospitales`:
   - Si `total <= 80`: una sola consulta `hospital=<centro>`.
   - Si no: subdividir por `estado` (6 valores).
   - Si una combinación `(centro, estado)` sigue topando: subdividir además
     por letra inicial `q=<letra>`.
4. Deduplicación por `uuid` en todo el proceso.

Runtime aproximado de la corrida completa: ~1000-3000 peticiones, 20-40 min.

## Mapeo

- `estado`: `A salvo/Hospitalizado/Encontrado/Fallecido` → `Localizado`;
  `Desaparecido/Herido` → `Desaparecido`.
- `id`: `map_id(f"reencuentra-ve.vercel.app:<uuid>")` (mismo esquema bigint
  que el resto de fuentes).
- `cedula` no expuesta en el listado → `"N/D"`.
- `es_menor`: por edad `< 18`, o si el nombre viene prefijado `(Menor)`
  (dato sucio de la fuente, algunos registros solo tienen el prefijo sin edad).

## Uso

```bash
cd scrapers/reencuentra
python scraper.py --limit 5 --smoke   # solo baseline, prueba rápida
python scraper.py --limit 300         # prueba con más cobertura
python scraper.py                     # -> reencuentra.{json,csv}, corrida completa
```

`fuente = "reencuentra-ve.vercel.app"`.
