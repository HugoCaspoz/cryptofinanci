# Cámara del móvil en directo

La app admite una nueva fuente `camera`: el navegador solicita la cámara sin micrófono, prefiere la trasera y envía JPEG al backend del ordenador. La misma aplicación puede seguir abierta en el PC para ver las imágenes y configurar las regiones de la mesa. No se añade una fase 31 ni se modifican las reglas de revisión en dinero real.

## Conectar

Con el ordenador y móvil en la misma red local y Docker Desktop iniciado, ejecuta desde la raíz:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/Start-Mobile.ps1
```

El script detecta la IPv4 de una interfaz con puerta de enlace, exige una dirección privada y levanta el gateway Caddy junto a los servicios existentes. Admite `-BindAddress 192.168.1.10` para elegir una interfaz concreta. Conserva la contraseña entre ejecuciones y la CA en un volumen Docker. Escribe `.mobile/access.txt` con la URL, usuario `zeros`, contraseña y pasos de instalación del certificado. `.mobile/` está excluido de Git.

1. Descarga en el móvil el certificado público desde la dirección `http://IP:5444/zeros-root.crt` indicada en ese archivo e instálalo como CA de esta instalación.
2. En iPhone, activa además la confianza SSL en Ajustes → General → Información → Ajustes de confianza de certificados. En Android, busca Certificado de CA en los ajustes de seguridad; el menú y la confianza del navegador dependen del dispositivo.
3. Abre `https://IP:5443/live`, introduce las credenciales y pulsa **Usar cámara**. Permite el acceso cuando lo solicite el navegador. El selector permite preferir trasera o frontal antes de iniciar.

La conexión debe estar validada por el navegador. Saltarse una advertencia de certificado no es el procedimiento de instalación. En el propio ordenador, `http://localhost:5173/live` permite probar una webcam sin configurar el gateway.

Si Windows bloquea el acceso desde otro dispositivo, ejecuta PowerShell **como administrador**:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/Start-Mobile.ps1 -ConfigureFirewall
```

La regla admite solo TCP 5443/5444, la IP/interfaz elegida y la subred local. No cambia la categoría de la red ni desactiva el firewall. No se ha podido crear automáticamente en esta ejecución porque la sesión no tiene privilegios de administrador. La conectividad desde un móvil físico sigue pendiente. Si el router aísla clientes o el teléfono no alcanza la red de su propio hotspot, conecta ambos a una Wi-Fi que permita comunicación entre dispositivos. Si cambia la IP del PC, ejecuta de nuevo el script.

Para desactivar únicamente el acceso LAN, `docker stop zeros-mobile-1`. No reenvíes estos puertos en el router. El backend y frontend HTTP habituales siguen publicados solo en localhost. El puerto HTTP adicional sirve únicamente el certificado público; no expone la app ni claves privadas. El acceso HTTPS a la app, API y WebSocket requiere contraseña.

## Encuadre y funcionamiento

- Móvil fijo, en horizontal y de frente al monitor; una mesa, sin reflejos y con texto legible. El selector prefiere una orientación de cámara; si el dispositivo no la tiene, el navegador puede elegir otra disponible.
- Ajusta las regiones de cartas, stacks, apuestas y bote en la configuración de la mesa usando la imagen recibida. No hay corrección automática de perspectiva. Mover el móvil o rotarlo requiere detener y revisar la calibración.
- Mantén la pestaña visible y la pantalla desbloqueada. Se solicita un bloqueo de suspensión cuando el navegador lo admite. Al ocultar la pestaña o cerrar la cámara se detiene el envío y se liberan sus pistas. La navegación dentro de React mantiene la captura; recargar/cerrar la pestaña la detiene.
- Puedes detener la fuente desde el PC. El móvil recibe el cambio por WebSocket y libera la cámara. Si se corta la red, el servidor declara error tras 15 segundos sin recibir imágenes.
- Se prefiere captura a 1920 × 1080, ajustada a lo que permita el dispositivo. El emisor limita las imágenes a ese rectángulo conservando la proporción, JPEG de calidad 0,85 y una única codificación/subida simultánea. El modo inteligente reutiliza el muestreo de 2/10 FPS. La fuente conserva solo el frame más reciente, sin cola creciente.
- Las marcas de tiempo de esta fuente reflejan la recepción en el servidor, no un reloj de exposición sincronizado del sensor. La cámara, enfoque, Wi-Fi y reflejos añaden límites que no aparecen al compartir una ventana directamente.

## Cambios y validación

Backend: `CameraCaptureSource`, `POST /api/capture/camera` y `POST /api/capture/{id}/camera-frame`. Conserva límites de 4 MiB por imagen, resolución máxima, validación, bloqueo de fuentes concurrentes y políticas de revisión. Los endpoints de pantalla y cámara rechazan imágenes de un tipo de fuente diferente o una captura anterior.

Frontend: permisos y elección de cámara en `CaptureProvider`/`CaptureControls`; emisor compartido con limpieza de vídeo, pistas y wake lock; identificación de fuente; guía `/mobile-setup.html`. Infraestructura opcional: `compose.mobile.yaml`, `infra/mobile/Caddyfile` y `scripts/Start-Mobile.ps1`. Caddy usa una CA local persistente y `default_sni` para clientes que acceden por IP sin enviar SNI.

Validación realizada:

- **662 pruebas de backend correctas**, con SQLite y PostgreSQL de pruebas exclusivo; incluye ocho nuevas de cámara, límites, desconexión y aislamiento de fuentes.
- **18 pruebas de navegador correctas**, incluidas cuatro nuevas con cámara simulada de Edge, codificación y subida real de JPEG, parada desde otro cliente, denegación de permisos, error del servidor y ocultación de pestaña; regresiones de sesiones, captura, historial, correcciones y muestreo.
- **Una prueba HTTPS correcta**: cadena y nombre del certificado comprobados por Node con la CA exportada, rechazo sin credenciales, aceptación autenticada y conexión WebSocket del navegador. El bypass de errores de certificado se usa solo en el contexto automatizado del navegador; no en el emisor de la app. Descarga HTTP del certificado comprobada.
- Compilación de producción, Prettier y `git diff --check` correctos. Gateway y servicios principales sanos; captura principal inactiva. Los ensayos de cámara se realizaron en un backend efímero separado de la base principal.

Estas pruebas no certifican compatibilidad con el teléfono del usuario, estabilidad prolongada de Safari/Chrome móvil ni precisión de reconocimiento al fotografiar un monitor. Esa es la siguiente validación manual.

Referencias oficiales: [getUserMedia y contexto seguro](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia), [HTTPS local de Caddy](https://caddyserver.com/docs/automatic-https), [default_sni](https://caddyserver.com/docs/caddyfile/options#default-sni) y [confianza de certificados en iOS](https://support.apple.com/en-us/102390).
