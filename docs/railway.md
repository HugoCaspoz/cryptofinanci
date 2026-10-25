# Despliegue en Railway

Aplicación: https://poker-production-d993.up.railway.app/live

Proyecto: https://railway.com/project/344c5cac-566f-4f32-aaa8-9c444fd99a02

Desde 0.30.1 el acceso muestra un formulario y usa una cookie firmada de 12 horas. Requiere usuario `zeros` y la contraseña de `.railway-local/access.txt`, excluida de Git y del contexto de despliegue. Las credenciales de Railway y PostgreSQL tampoco se guardan en el código. La base de datos remota es independiente: no se ha migrado el historial local.

## Usar desde el móvil

Abre la URL HTTPS, autentícate y pulsa **Usar cámara**. No necesitas el certificado de Caddy local, la misma Wi-Fi que el PC ni Docker encendido en el ordenador. Las imágenes se procesan ahora en Railway. Mantén el móvil fijo y horizontal, y calibra las regiones de la mesa sobre la imagen recibida.

El modo sigue siendo `LIVE_REAL_MONEY`, con revisión estratégica diferida y cierre de sesión explícito. El explicador está configurado como `local`; se puede activar OpenAI con sus variables de servidor cuando se configure una clave.

## Arquitectura y persistencia

- Servicio `poker`: contenedor que compila React con Node 24 y ejecuta Nginx y FastAPI con un solo worker, supervisados para recibir señales y cerrar correctamente. Nginx escucha en `PORT` y sirve tanto la app como API/WebSocket, bajo el mismo dominio y contraseña. `/health` es público para las comprobaciones de disponibilidad.
- Servicio `Postgres`: base de datos de Railway, referenciada mediante `DATABASE_URL=${{Postgres.DATABASE_URL}}`, con su propio volumen.
- Volumen `poker-volume`: montado en `/data`. La calibración se guarda en `/data/table_layouts/platform_1920x1080.json`; se copia una semilla únicamente si todavía no existe. No se sustituye al reiniciar o desplegar. `TABLE_LAYOUT_PATH` permite configurar la ruta del almacén.
- Región `europe-west4-drams3a`, una réplica. La captura global y sus buffers son propios de esa instancia; los frames temporales no sobreviven al reinicio. Manos y evaluaciones permanecen en PostgreSQL.

Railway gestiona el HTTPS del dominio público. La app no expone el puerto interno de FastAPI. El proxy de cámara conserva los límites existentes del backend y permite WebSocket autenticado.

## Código de infraestructura y actualizaciones

La configuración actual está en `.railway/railway.ts` con el SDK `railway/iac`. Se usa un parcial `poker` para administrar solo el servicio de aplicación y su volumen. PostgreSQL fue creado con la plantilla oficial y queda fuera de ese parcial. Las variables se gestionan en Railway (`managed: false`); los secretos no se materializan en el archivo de infraestructura.

No se utiliza `railway.json`: la plataforma ha retirado ese formato para servicios nuevos. La imagen está en `infra/railway/Dockerfile`; arranque, Nginx y Supervisor en el mismo directorio. `.dockerignore`, `.railwayignore` y `.gitignore` excluyen contraseñas, certificados locales, datos de prueba y dependencias.

Desde PowerShell, con la cuenta Railway autenticada:

```powershell
npm ci
npm run deploy
```

El script `scripts/Deploy-Railway.ps1` enlaza explícitamente este proyecto, aplica la configuración sin autorizar eliminaciones y sube el código local. Si no dispone de la CLI nativa, la instala en `.railway-local/cli`, fuera de Git. Usa el ejecutable nativo para la comprobación de versión del SDK en Windows. Si falta autenticación, ejecuta `npx @railway/cli login` primero.

Se subió el árbol de trabajo local sin hacer push a GitHub: el remoto actual del repositorio apunta a otro proyecto. No hay autodespliegue desde ese remoto.

## Validación del despliegue

Despliegue confirmado `SUCCESS`: `b0a991e7-10ed-4aac-9a6c-26c78ead9092`.

- Imagen completa compilada y arrancada localmente con PostgreSQL de pruebas; API autenticada devuelve 200 y acceso sin contraseña 401.
- 27 pruebas de layout/API correctas, incluida la selección de ruta persistente por variable de entorno y la prioridad de una ruta explícita.
- Compilación de frontend, Prettier y `git diff --check` correctos.
- Prueba de navegador contra el dominio real: certificado HTTPS validado sin bypass, API de salud con PostgreSQL y modo correcto, protección de página/API, WebSocket conectado, cámara disponible y navegación de sesiones a 390 px sin desbordamiento ni errores JavaScript.
- Archivo de calibración verificado dentro de `/data/table_layouts` en el servicio remoto. `railway config plan` confirma que la configuración está actualizada.

No se han enviado imágenes de una cámara física al despliegue ni calibrado una mesa real. Esa validación sigue pendiente; el navegador automatizado comprobó el acceso y la disponibilidad del flujo, sin iniciar una captura de producción.

Referencias: [despliegue con CLI](https://docs.railway.com/cli/up), [infraestructura como código](https://docs.railway.com/infrastructure-as-code) y [healthchecks y PORT](https://docs.railway.com/deployments/healthchecks).

Actualización 0.30.1: [correcciones de la auditoría](repairs-2026-10-25.md). Sustituye la verificación Basic Auth en cada petición por sesión, añade perfiles de cartas persistentes y gestión de sesiones. Despliegue actual `edd36dca-cadf-4d0a-8b5b-0efbaecbe129`.
