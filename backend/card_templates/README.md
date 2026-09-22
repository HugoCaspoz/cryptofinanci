# Referencias de cartas

Por defecto se usa la baraja sintética generada en `app/card_detector/demo.py`.
No contiene referencias de ninguna plataforma real.

Para un perfil propio, crea una subcarpeta con `manifest.json` y 52 imágenes PNG
de cartas completas, verticales, de fondo claro, sin bordes externos ni mesa.
El índice debe estar en la zona superior y el palo ser visible debajo; el comparador
divide las referencias en esas dos zonas. No admite abanicos, inclinación o dorsos.

```json
{
  "name": "Mi baraja v1",
  "platform": "Nombre exacto del layout",
  "empty_bgr": [45, 80, 45],
  "empty_tolerance": 16
}
```

`empty_bgr` es el color real de las regiones de cartas vacías, en orden azul,
verde, rojo. La confirmación de vacío exige que el 98,5% del recorte coincida
con ese color dentro de la tolerancia; fondos complejos necesitarán otro detector.

Nombres: `2s.png` … `As.png`, y lo mismo para `h`, `d`, `c`.
Rangos: `23456789TJQKA`. Palos: `s` picas, `h` corazones, `d` diamantes, `c` tréboles.
Cada imagen debe medir entre 32 y 1024 píxeles por lado y ocupar como máximo 2 MB.

En local, configura `CARD_TEMPLATE_DIR` con la ruta de la subcarpeta antes de iniciar
el backend. En Compose, usa `/app/card_templates/mi_perfil` en `.env`; este directorio
se monta en modo lectura. El nombre de plataforma debe coincidir y el layout debe
estar calibrado. Reinicia la captura para cargar cambios. Un perfil inválido deja
el vídeo funcionando y muestra que el reconocimiento no está disponible.

Estas referencias solo preparan la comparación visual. Su precisión debe medirse
con capturas independientes de la plataforma antes de considerar el perfil validado.
