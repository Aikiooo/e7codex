

# E7 Codex — herramientas de compilación

El pipeline detrás de [e7codex.com](https://e7codex.com): un archivo estático navegable con arte de personajes/artefactos de Epic Seven y un visor de modelos Spine en vivo en el navegador. Este repositorio contiene las **herramientas**: transforma activos brutos extraídos del juego en el sitio estático terminado. **No incluye activos del juego**; debes proporcionarlos tú.

> **¿Qué hay aquí:** el indexador, el pipeline de preparación de activos + renderizado de poses, los convertidores SCSP→Spine (con atribución — ver `CREDITS.md`), y la interfaz del sitio.
>
> **¿Qué NO hay aquí (por diseño):** ningún activo de Epic Seven, el runtime en caché de spine-player y las bases de datos de nombres comunitarias. Los pasos siguientes obtienen o generan cada uno de ellos localmente.

## Cómo encaja todo

```
raw .scsp/.sct/.atlas  ──►  converters  ──►  staged Spine JSON  ──►  site/assets/<slug>/
   (you supply)            (this repo)        + decoded .png            │
                                                                        ▼
                          build_index.py  ──►  site/data/*.json  ◄── names from
                                                                      community DBs
                          render_poses.js ──►  pose.png thumbnails
                                                                        │
                                                                        ▼
                                              site/index.html + viewer.html
```

## Requisitos previos

- Python 3.11+ (`pip install lz4 pillow texture2ddecoder`)
- Node 18+ (`npm install` — descarga puppeteer + sharp para renderizado de miniaturas)
- Tus propios activos de Epic Seven extraídos (ver paso 2)

## Configuración

### 1. Cachear el runtime de Spine (una sola vez)

spine-player **no** se redistribuye aquí. Descarga la versión estándar 3.8 de Esoteric y aplica el parche de una línea para capturas de pantalla:

```powershell
curl -sSL -A "Mozilla/5.0" -o site/spine-player.js  https://esotericsoftware.com/files/spine-player/3.8/spine-player.js
curl -sSL -A "Mozilla/5.0" -o site/spine-player.css https://esotericsoftware.com/files/spine-player/3.8/spine-player.css
copy site\spine-player.js  tools\spine-player.js
copy site\spine-player.css tools\spine-player.css
```

Luego, en `site/spine-player.js` (alrededor de la línea 11071), habilita la lectura de búfer para que el botón de captura de pantalla del visor funcione:

```js
// find:    var webglConfig = { alpha: config.alpha };
// change:  var webglConfig = { alpha: config.alpha, preserveDrawingBuffer: true };
```

**Opcional — Herencia de escala sin cizalla para Spine-2.1.x.** Spine 2.1.x rastreaba la escala mundial como escalares y reconstruía una matriz limpia de rotación×escala por hueso, por lo que un padre rotado con escala no uniforme nunca aplicaba cizalla a sus hijos. spine-player 3.8 compone matrices completas 2×2, que *sí* acumulan cizalla allí — lo que explota mallas de armas de alto aspecto en algunos rigs de combate 2.1.27 convirtiéndolas en agujas. El convertidor marca los rigs afectados con `"e7v21x": true`; un visor estándar ignora la bandera (el bug de las agujas permanece). Para respetarla, en `site/spine-player.js` busca el inicio de `Bone.prototype.updateWorldTransformWith` — justo después de `var parent = this.parent;` (el 3.8 estándar lo sigue con `if (parent == null) {`) — e inserta esta rama condicionada *antes* de ese `if`:

```js
if (this.skeleton.data.e7v21x) {
    var sk = this.skeleton;
    var cosD = spine.MathUtils.cosDeg, sinD = spine.MathUtils.sinDeg;
    if (parent == null) {
        var wr = rotation, wsx = scaleX * sk.scaleX, wsy = scaleY * sk.scaleY;
        this._e7wr = wr; this._e7wsx = wsx; this._e7wsy = wsy;
        this.a = cosD(wr) * wsx; this.b = -sinD(wr) * wsy;
        this.c = sinD(wr) * wsx; this.d = cosD(wr) * wsy;
        this.worldX = x * sk.scaleX + sk.x;
        this.worldY = y * sk.scaleY + sk.y;
        return;
    }
    var pa = parent.a, pb = parent.b, pc = parent.c, pd = parent.d;
    this.worldX = pa * x + pb * y + parent.worldX;
    this.worldY = pc * x + pd * y + parent.worldY;
    var pwr = parent._e7wr || 0;
    var pwsx = parent._e7wsx != null ? parent._e7wsx : 1;
    var pwsy = parent._e7wsy != null ? parent._e7wsy : 1;
    var tm = this.data.transformMode;
    // Normal(0)/NoScale(3)/NoScaleOrReflection(4) inherit rotation;
    // Normal(0)/NoRotationOrReflection(2) inherit scale.
    var inhRot = (tm == 0 || tm == 3 || tm == 4);
    var inhScale = (tm == 0 || tm == 2);
    var wr = inhRot ? pwr + rotation : rotation;
    var wsx = inhScale ? pwsx * scaleX : scaleX;
    var wsy = inhScale ? pwsy * scaleY : scaleY;
    this._e7wr = wr; this._e7wsx = wsx; this._e7wsy = wsy;
    this.a = cosD(wr) * wsx; this.b = -sinD(wr) * wsy;
    this.c = sinD(wr) * wsx; this.d = cosD(wr) * wsy;
    return;
}
```

También necesitas que el cargador transmita la bandera: busca `skeletonData.imagesPath = skeletonMap.images;` y añade `skeletonData.e7v21x = skeletonMap.e7v21x;` después. La rama está condicionada por la bandera, por lo que los rigs 3.8.99 y cualquier hueso sin escala no uniforme bajo rotación quedan intactos.

### 2. Proporciona tus propios datos

Este es el paso que debes hacer tú mismo. Necesitas:

- **Rigs brutos** — los archivos de esqueleto `.scsp` del juego (+ texturas `.sct`, `.atlas`) para retratos y modelos de combate. Extraerlos del cliente es responsabilidad tuya; la herramienta comunitaria para ello es [EpicSevenAssetRipper](https://github.com/CeciliaBot/EpicSevenAssetRipper).
- **Nombres / slugs** — apunta el indexador a las bases de datos comunitarias públicas (ceciliabot, epic7rtastats). Ver `CREDITS.md`. No están incluidas.
  - *Opcional, autosuficiente:* si tienes tus propios datos de juego descifrados + claves configuradas (ver el pipeline de voces a continuación — mismo `voice_keys.json`), ejecuta `python tools/build_names.py` para extraer nombres + rareza/atributo/rol directamente del juego en `data_external/names_from_db.json`. El indexador lo superpone antes de las bases de datos comunitarias. Esto también escribe `unreleased_units.json` (unidades que el juego aún etiqueta como "Unknown Hero"); el indexador las descarta — el proyecto no publica unidades no anunciadas/dataminadas. Ambos archivos están gitignorados.
  - *Artefactos (misma configuración):* `python tools/build_artifacts.py` decodifica `equip_item.db` en `data_external/artifacts_from_db.json`, superpuesto antes de `Artifacts.json` comunitario para nombre/rareza/rol. Gitignorado.
  - *Localización (misma configuración):* `python tools/build_i18n.py` decodifica el `text.db` de cada idioma en superposiciones de nombres de visualización por idioma (`site/data/lang/<lang>.json`) que alimentan el cambiador de idioma del sitio (10 idiomas del juego + vietnamita no oficial). Necesita las mismas claves/datos que `build_names.py`, más traducciones de interfaz mantenidas manualmente (`data_external/i18n_ui/<lang>.json`, no incluidas). Sin las superposiciones, el cambiador aún se renderiza y todos los nombres vuelven a inglés.

Indica a la pipeline dónde están tus datos en **un solo lugar**: copia `tools/voice_keys.example.json` a `tools/voice_keys.json` (gitignorado) y configura `raw_dir` (tu `output/` extraído), `img_dir` (imágenes decodificadas) y `voice_dir` (directorio temporal de voces). `tools/paths.py` los resuelve para cada herramienta, por lo que no hay código que editar; las claves omitidas usan `dump_dir` por defecto.

### 3. Convertir y preparar

```powershell
python tools/prepare_assets.py --all          # retratos → site/assets/<slug>/
python tools/prepare_combat_assets.py --all    # rigs de combate (opcional)
```

`tools/scsp_to_json.py` detecta automáticamente la versión del rig (2.1.27, 3.8.x o 4.2.x) y envía a el convertidor correcto: los de terceros incluidos para 2.1.27 / 3.8.x, y `tools/skel42_to_json38.py` para rigs Spine 4.2 (un `.skel` estándar envuelto en E7, convertido a JSON compatible con 3.8 para que el mismo spine-player renderice todos los rigs).

### 4. Renderizar miniaturas de poses

```powershell
node tools/render_poses.js        # genera site/assets/<slug>/pose.png
```

Opcionalmente, genera miniaturas del hub solo de personaje más ajustadas (el sitio vuelve a `pose.png` cuando estas faltan). El recorte inteligente se aplica al PNG en tiempo de renderizado:

```powershell
node tools/render_thumbs.js       # site/assets/<slug>/thumb.png (FX/fondo eliminados, recorte inteligente)
```

### 5. Compilar el índice de datos

```powershell
python build_index.py --img <your_img_dir> --raw <your_raw_dir> --out ./site
```

### 6. Ejecutar localmente

```powershell
cd site
python -m http.server 8765
# visita http://localhost:8765/
```

> Nota: `site/index.html`, `viewer.html` y `404.html` hacen referencia a `favicon-16.png`, `favicon-32.png` y `apple-touch-icon.png`, que no se distribuyen. Coloca tus propios iconos en `site/` o elimina las etiquetas `<link rel="icon">` — el sitio funciona de ambas formas (el navegador solo mostrará un favicon por defecto).

## Opcional: pipeline de voces

El sitio puede mostrar créditos de dobladores por héroe y un catálogo clickeable de clips de voz. Este es un complemento **opcional** con requisitos adicionales, y como el resto del repositorio, **no incluye datos del juego ni claves** — debes proporcionar ambos.

Necesitarás:

- **vgmstream** — descarga una versión de lanzamiento de [vgmstream](https://github.com/vgmstream/vgmstream/releases) y descomprímela en `tools/vendor/vgmstream/` (para que exista `tools/vendor/vgmstream/vgmstream-cli.exe`).
- **FFmpeg** — instálalo y asegúrate de que `ffmpeg` esté en tu `PATH`.
- **Tus propias claves + datos** — copia `tools/voice_keys.example.json` a `tools/voice_keys.json` (gitignorado) y rellena los valores desde tu propia instalación: `dump_dir` (+ opcional `raw_dir` / `img_dir` / `voice_dir`), tu archivo de clave outer-XOR (`outer_key_file`), y la clave XXTEA por defecto (`default_xxtea_key`). Para `sync_voice_banks.py`, configura opcionalmente `game_sound_dir` (tu `<game install>/data.unpacked/sound` de solo lectura). Ninguno de estos se proporciona aquí.
- **Tus propios bancos de voz** — los archivos `.bank` de FMOD, bajo `<sound_dir>/<lang>/*.bank`.

Luego:

```powershell
# Créditos + un catálogo de respaldo desde tus archivos de datos locales → site/data/voices.json
python tools/build_voices.py

# (opcional) copia bancos FUERA de tu instalación del juego al árbol temporal de voces,
# con espera de descarga + verificación de actualización por idioma (nunca escribe en la carpeta del juego)
python tools/sync_voice_banks.py --extract       # sincroniza y encadena la extracción para idiomas modificados

# Decodifica los bancos de voz → OGG + un catálogo por idioma
python tools/extract_voice_audio.py --langs en --slugs c1001     # subconjunto / prueba piloto
python tools/extract_voice_audio.py --langs en ja ko --all       # completo
```

`extract_voice_audio.py` lee bancos desde / escribe OGGs a tu `voice_dir` configurado (desde `voice_keys.json`, por defecto `<dump_dir>/_voice_work`); anula por ejecución con `--sound` / `--out` (o las vars de entorno `E7_VOICE_SOUND` / `E7_VOICE_OUT`). El audio generado y el JSON permanecen locales — están gitignorados y no son parte de este repositorio.

## Despliegue

`site/` es un paquete estático independiente — sirvelo desde cualquier hosting estático (GitHub Pages, Cloudflare Pages, Netlify, un servidor web plano, etc.). Los activos Spine bajo `site/assets/` son grandes; para producción probablemente quieras descargarlos a almacenamiento de objetos y apuntar el visor a ese host en lugar de servirlos inline. Esa configuración queda a tu cargo.

## Créditos y licencias

Ver `CREDITS.md` para atribución completa y `LICENSE` para términos. En resumen: el código de E7 Codex es MIT; los convertidores incluidos mantienen los términos de sus autores originales; spine-player es de Esoteric Software; y los activos de Epic Seven pertenecen a Smilegate / Super Creative y no forman parte de este repositorio.
