# Workflows: desarrollo, deploy y operaciones

## Desarrollo local

> **TBD** — comandos exactos dependen del stack elegido. Cuando se decida, rellenar:

```bash
# Setup (placeholder)
cp .env.example .env
# Editar .env con LETTERBOXD_USER, intervalos, puerto

# Arrancar (placeholder)
docker compose up --build
# o, sin Docker, comandos nativos del stack
```

Servicio disponible en `http://localhost:<HTTP_PORT>` (puerto definido en `.env`).

## Añadir una lista nueva

1. Abrir la UI (`http://localhost:<HTTP_PORT>`).
2. Ir a "Listas → Añadir".
3. Pegar la URL de la lista pública de Letterboxd (`https://letterboxd.com/{user}/list/{slug}/`).
4. Configurar política: sort order (Letterboxd / random / reverse), max items servidos, regla de rotación al ver una película.
5. Guardar. El siguiente ciclo de scraping la ingiere.
6. Copiar la URL del endpoint generado y pegarla en Radarr → Custom Lists.

## Conectar con Radarr

1. En Radarr: Settings → Lists → Add List → "Custom List".
2. URL: `http://<host-watchlistarr>:<HTTP_PORT>/list/<list_id>`.
   - Si Radarr y watchlistarr corren en la misma red Docker, usar el nombre de servicio (`http://watchlistarr:<HTTP_PORT>/...`).
3. Quality profile, root folder, minimum availability: a gusto del usuario.
4. Test → Save. Radarr empezará a importar películas en su siguiente sync.

## Forzar refresco manual

- Desde la UI: botón "Refrescar" en cada lista (lanza el scraper de esa lista fuera de su ciclo).
- Desde CLI: TBD según stack (`docker exec watchlistarr <comando>` o endpoint admin).

## Deploy con Docker

```bash
docker compose up -d
docker compose logs -f watchlistarr
docker compose down
```

Volumen persistente en `./data` (o el path configurado) para la DB.
Actualización: `docker compose pull && docker compose up -d`.

## Merge a producción (`main`)

Solo cuando el usuario lo pide explícitamente:

```bash
git checkout main
git merge dev
git push origin main
```

- Mensaje de merge: resume todo lo nuevo desde el anterior commit en `main`.
- **No** excluir `CLAUDE.md` ni `.claude/` (a diferencia de otros proyectos personales): aquí ambos viajan a `main`.

## Variables de entorno

| Variable | Uso | Secreto |
|---|---|---|
| `LETTERBOXD_USER` | Usuario cuyo RSS se monitoriza para rotación de vistos | No |
| `SCRAPE_INTERVAL` | Frecuencia del ciclo de scraping (ej. `30m`) | No |
| `RSS_INTERVAL` | Frecuencia del polling del RSS de usuario (ej. `15m`) | No |
| `HTTP_PORT` | Puerto donde se sirve UI + API | No |
| `LOG_LEVEL` | Nivel de log (`debug` / `info` / `warn` / `error`) | No |
| `USER_AGENT` | UA usado en requests a Letterboxd (default `watchlistarr/<ver>`) | No |
| `DATABASE_PATH` | Path del fichero/host de la DB (TBD según motor) | No |

> Rellenar y reordenar cuando se concrete el stack. Añadir filas para tokens si en el futuro se expone la API fuera de la red Docker.
