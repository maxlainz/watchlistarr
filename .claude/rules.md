# Reglas de código, git y estilo

## Git

- Rama de trabajo: `dev`. Nunca commitear directamente a `main`.
- Tras cada edición de código → commit en `dev` → `git push` inmediato.
- Merge a `main` solo si el usuario lo pide explícitamente. El mensaje debe resumir todo lo nuevo desde el anterior commit en `main`.
- `CLAUDE.md` y `.claude/` **sí** entran a `main` en este repo (no se excluyen en el merge).
- Commits en español, mensaje corto y descriptivo. Prefijos convencionales (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`) bienvenidos pero no obligatorios.

## Idioma

- Documentación, comentarios (cuando existan) y mensajes de commit: español.
- Código, identificadores, nombres de archivos, branches y variables de entorno: inglés.

## Lenguaje y tipado

> **TBD** — pendiente de elegir stack backend (Python / Node-TS / Go / otro).
> Cuando se decida, rellenar aquí: versión, gestor de paquetes, linter, formatter, type checker.

Reglas vigentes sin importar el stack:
- Si el lenguaje soporta tipado estático, usarlo en todo el código de aplicación. No `any` / `interface{}` salvo en fronteras serializadas.
- Configuración (puertos, paths, intervalos, credenciales) **siempre** vía variables de entorno o archivo de config — nunca hardcoded.

## Estilo de código

- Módulos pequeños y nombres descriptivos. Una función hace una cosa.
- Sin frameworks de UI complejos. Frontend = HTML server-rendered + HTMX para interactividad puntual.
- Sin CSS-in-JS ni utility frameworks pesados; un único stylesheet global salvo motivo concreto.

## Comentarios

- Por defecto, sin comentarios.
- Solo añadir uno cuando el WHY no es obvio: restricción de la web de Letterboxd, workaround de un bug concreto, invariante sutil, rate limit no evidente.
- Nunca explicar el QUÉ — el nombre de la función ya lo dice.

## Abstracciones

- Sin abstracciones prematuras. Tres líneas similares son preferibles a un helper genérico si no hay reutilización real.
- No añadir manejo de errores para escenarios imposibles. Confiar en las garantías del framework.
- Validación solo en fronteras del sistema: input de usuario en la UI, respuesta del scraper sobre Letterboxd, payload que se envía a Radarr.
- Sin feature flags ni shims de retrocompatibilidad mientras no haya usuarios externos. Cambiar el código directamente.

## Scraping de Letterboxd

Letterboxd no ofrece API pública estable; el proyecto entero se apoya en scraping del HTML público y el RSS de usuario. Reglas operativas permanentes:

- **Rate limit**: una request cada X segundos como mínimo (ajustar empíricamente, empezar conservador con 2-3 s). Nunca paralelizar peticiones a la misma cuenta de Letterboxd.
- **User-Agent**: identificarse con `watchlistarr/<version> (+<repo-url>)`. No suplantar navegador.
- **Caché**: cachear respuestas durante el ciclo de scraping. Si una lista no ha cambiado (mismo número de items, mismo orden) no re-scrapear sus detalles.
- **Robustez al cambio de HTML**: si un selector falla, fallar ruidosamente y loggear suficiente contexto para reparar el selector. No intentar "adivinar" estructura alternativa.
- **Datos mínimos**: extraer solo lo que se necesita (TMDB ID, título, año). No clonar metadatos enteros que Radarr ya tiene de TMDB.
