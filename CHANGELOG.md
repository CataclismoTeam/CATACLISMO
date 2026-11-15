# Changelog

## 1.0.0 (2026-11-15)


### Novedades

* **backend:** add continual learning, NRT live feed and documentation ([d00b799](https://github.com/CataclismoTeam/CATACLISMO/commit/d00b799bb8ad14d58bd343e9c555be809ec810f4))
* **backend:** despliegue en Render y conexión automática del front ([85c931f](https://github.com/CataclismoTeam/CATACLISMO/commit/85c931ff7b9410aa0a4d5e6a492746f8bd9d8564))
* **backend:** el front se conecta a la API de CATA, LUCIA y JULI ([5ca0283](https://github.com/CataclismoTeam/CATACLISMO/commit/5ca028301fccec8bd72b7227ba019966395d2e8d))
* **backend:** FIRMS en vivo cada 3 h y predicciones de CATA siempre disponibles ([45ae207](https://github.com/CataclismoTeam/CATACLISMO/commit/45ae20739e70c1b6f898a4c7be3d14bd65f8ad68))
* **calendario:** botón Maximizar/Minimizar en lugar de Plegar/Desplegar ([19845d6](https://github.com/CataclismoTeam/CATACLISMO/commit/19845d6fa2ef69022cd293af288406c205cde95b))
* **datos:** armonizar puntos calientes MODIS y VIIRS de FIRMS ([93548db](https://github.com/CataclismoTeam/CATACLISMO/commit/93548db21387dbd652745fce138abc950ab230a6))
* **front-v2:** 12 simulaciones, unidades por aire, tierra y mar, vías de escape del equipo y ajustes ([223c222](https://github.com/CataclismoTeam/CATACLISMO/commit/223c22203a04fa8aac6671546dbedcc47629d59c))
* **frontend:** shell de mando y calendario de actividad de fuego ([1e94bb7](https://github.com/CataclismoTeam/CATACLISMO/commit/1e94bb74da2172dd3475dd360d541d23ee58c49e))
* **i18n:** interfaz en español e inglés ([e0f9a92](https://github.com/CataclismoTeam/CATACLISMO/commit/e0f9a921c7b9a0b77c583e493183f0b9b0db2303))
* **mapa:** al ampliar sobre un incendio se abre su ficha ([ed6156f](https://github.com/CataclismoTeam/CATACLISMO/commit/ed6156ffd75afe0be7adc78b08cb45a3d797e965))
* **mapa:** avisos de núcleos en riesgo ([4e7ab4c](https://github.com/CataclismoTeam/CATACLISMO/commit/4e7ab4cdf25ceb57534a5d5062386c2ce33aac75))
* **mapa:** buscar, medir y compartir ([9f71cc6](https://github.com/CataclismoTeam/CATACLISMO/commit/9f71cc6fba34ddbd3f682fc48c413b3b839bdf7b))
* **mapa:** calendario y mapa conectados ([c28d4cf](https://github.com/CataclismoTeam/CATACLISMO/commit/c28d4cfdb3763f5a899669d3a6abb997d398792c))
* **mapa:** front v2, incendios reales por comunidad autónoma con superficie de calor ([961375a](https://github.com/CataclismoTeam/CATACLISMO/commit/961375a282ca7523b0c608985e9c89005e45539e))
* **mapa:** giro e inclinación menos accidentales ([e284ccd](https://github.com/CataclismoTeam/CATACLISMO/commit/e284ccd66b8d3774ca9dadb8747bf0de9e17de31))
* **mapa:** incendios reales apagados en gris ceniza ([845b2ff](https://github.com/CataclismoTeam/CATACLISMO/commit/845b2ff932b04c713fc00f6231335d53bebbc960))
* **mapa:** incendios reales en celdas rojas con halo de propagación; quita botones Incendios/Unidades ([6d179fb](https://github.com/CataclismoTeam/CATACLISMO/commit/6d179fb2d50ea95dfa157b0948e484284ed969e5))
* **mapa:** línea de tiempo del incendio simulado ([d27e62d](https://github.com/CataclismoTeam/CATACLISMO/commit/d27e62daed251b7e585a28706612629db086ccd7))
* **mapa:** mapa de mando con MapLibre y MapTiler, fuego real frente a predicción ([4baec53](https://github.com/CataclismoTeam/CATACLISMO/commit/4baec53acdb1544613485351d4e6a5274871f5ba))
* **mapa:** procedencia visible, fuentes enlazadas y halo ilustrativo ([5a2678e](https://github.com/CataclismoTeam/CATACLISMO/commit/5a2678e1622dbb51c8d6930a673173cdbf877e2e))
* **mapa:** salvamento solo por tierra y aire ([a537ae2](https://github.com/CataclismoTeam/CATACLISMO/commit/a537ae21b49089e3e1094d2e4c07e4dcc017aaed))
* **parser:** add initial MODIS and VIIRS data parser ([565b345](https://github.com/CataclismoTeam/CATACLISMO/commit/565b3450d589f5a1e3f7adb79617d5472132ce72))
* **shell:** el calendario empieza plegado también en escritorio ([1ae77a2](https://github.com/CataclismoTeam/CATACLISMO/commit/1ae77a238f61b775b23534a20328ae05f19e90cd))


### Correcciones

* **a11y:** todos los campos de formulario con name ([f7d164a](https://github.com/CataclismoTeam/CATACLISMO/commit/f7d164a074b13453b70618bbefeeb7168cbc78a4))
* **backend:** en Render la sincronización en vivo se activa sola ([341e301](https://github.com/CataclismoTeam/CATACLISMO/commit/341e301876ca3b62b36a6b51d51f76fdbddcd9d4))
* **backend:** la ruta de LUCIA valida la entrada antes de buscar predicciones ([36bd2e9](https://github.com/CataclismoTeam/CATACLISMO/commit/36bd2e9538d224f5e6438c2c88d6ad32f09832a0))
* **backend:** una URL guardada de antes ya no tapa el backend de producción ([cc8694a](https://github.com/CataclismoTeam/CATACLISMO/commit/cc8694ae627ad63b92a1c69d1880a772797a5edc))
* **ci:** el backend no frena el despliegue del frontend ([fa7ef02](https://github.com/CataclismoTeam/CATACLISMO/commit/fa7ef028373f4f6c77be2bfa3b8be046b36e7f64))
* **docs:** usar gemini-3.8-flash en la documentación automática ([#5](https://github.com/CataclismoTeam/CATACLISMO/issues/5)) ([5095a89](https://github.com/CataclismoTeam/CATACLISMO/commit/5095a89d3c5a369894793b8970d18c4e00b6bc44))
* **front:** tras un despliegue el calendario ya no se queda roto ([dd04cdb](https://github.com/CataclismoTeam/CATACLISMO/commit/dd04cdbfb7ebee05adc79b8bb22c2c2753d5187c))
* **mapa:** errores de carga visibles y sin manejadores duplicados ([d23c869](https://github.com/CataclismoTeam/CATACLISMO/commit/d23c8697decbb88d4778f43945aefc4b991c5713))
* **mapa:** fichas y paneles apilados por esquina, sin taparse ([86e126c](https://github.com/CataclismoTeam/CATACLISMO/commit/86e126c906e3b7d9cd8cce514e57595169aa660b))
* **mapa:** fuego en mancha sólida, sin rejilla ([0edf3fd](https://github.com/CataclismoTeam/CATACLISMO/commit/0edf3fd9697678189137690c2db0e1d18c627e23))
* **mapa:** predicción más legible y marcadores sin solaparse ([cf0b267](https://github.com/CataclismoTeam/CATACLISMO/commit/cf0b2678e7fad86ffdc67e3600888324b01d9b7e))
* **mapa:** vías de escape por carretera real y placas de unidades sin solapes ([9c37b7c](https://github.com/CataclismoTeam/CATACLISMO/commit/9c37b7c9849c76a03dbda74315181debd3b19b20))
* **nav:** barra inferior en móvil en lugar de los botones flotantes del mapa ([c8e40a8](https://github.com/CataclismoTeam/CATACLISMO/commit/c8e40a8ce01cd1309e6581d01c1107716e2bdb54))
* **rutas:** las vías de escape eligen refugios alcanzables por carretera ([9e989b6](https://github.com/CataclismoTeam/CATACLISMO/commit/9e989b63923a755e5583b4cd1a6384e6ddf2b5cb))
* **ux:** arreglos de la evaluación heurística ([7269414](https://github.com/CataclismoTeam/CATACLISMO/commit/72694145a165f67328988d79f04ab3a92434c50b))


### Rendimiento

* **front-v2:** Lighthouse de 0,37 a 0,93 y regresión visual al día ([4fa5a39](https://github.com/CataclismoTeam/CATACLISMO/commit/4fa5a39e7f4071ed490c74d5a8808def1b696530))


### Documentación

* actualizar el relevo con el estado del mapa ([d4b3a3f](https://github.com/CataclismoTeam/CATACLISMO/commit/d4b3a3fd1d463e50f355d00fe5d10fb4658e7baa))
* backend conectado y estado del Deploy ([7cd98df](https://github.com/CataclismoTeam/CATACLISMO/commit/7cd98df5f397fd9ba9429d0c5b89039081840c1e))
* backend publicado en Render y conectado solo ([5a1bb07](https://github.com/CataclismoTeam/CATACLISMO/commit/5a1bb07f10cb14753d18c8e513ea9ae7f3b95529))
* Deploy de main en verde ([1dc77d4](https://github.com/CataclismoTeam/CATACLISMO/commit/1dc77d4c01533b74fdf3e673e4c2d75b35133b8c))
* document FIRMS_MAP_KEY secret and CATA frontend data sources ([e9919c6](https://github.com/CataclismoTeam/CATACLISMO/commit/e9919c60913e04bf7c18d8dd48365a1e65a1edfb))
* evaluación heurística del front v2 ([692304a](https://github.com/CataclismoTeam/CATACLISMO/commit/692304acc2afb7f88311b08f90d116d69f6b5d19))
* hoja de ruta del front v2 y seguimiento ([359bbd4](https://github.com/CataclismoTeam/CATACLISMO/commit/359bbd4d02fac0a759bec0aa544f772ff7d8536f))
* README actualizado con arquitectura, datos en vivo y uso ([a6fa096](https://github.com/CataclismoTeam/CATACLISMO/commit/a6fa096f57bb3c92ae48143bf36c6d53b23ae854))
* relevo y README del preproceso con la front v2 ([ad57e4f](https://github.com/CataclismoTeam/CATACLISMO/commit/ad57e4f82a83c10ba8ec9905c5fca97d681265f1))
* usar la web en Google Chrome ([5c1f965](https://github.com/CataclismoTeam/CATACLISMO/commit/5c1f9654d289f66dee5aabe9b312bd3d84ca7b25))


### CI/CD

* apuntar al repo transferido a CataclismoTeam ([#4](https://github.com/CataclismoTeam/CATACLISMO/issues/4)) ([96339bd](https://github.com/CataclismoTeam/CATACLISMO/commit/96339bd83680d951a31ac726a32f5ab5ec457430))
* **docs:** reintentos, tolerancia a fallos de Gemini y límites de tamaño ([246d972](https://github.com/CataclismoTeam/CATACLISMO/commit/246d9726bd39ee3a27f4223954e594a3936a12c6))
* **release:** no romper si la salida del PR de release llega vacía ([#3](https://github.com/CataclismoTeam/CATACLISMO/issues/3)) ([d28f9fb](https://github.com/CataclismoTeam/CATACLISMO/commit/d28f9fb1ae2dae8949c33d6e12bde60c0ae6441d))


### Build y dependencias

* **ci:** decouple API runtime from trainer deps and split pytest ([7b8c4ef](https://github.com/CataclismoTeam/CATACLISMO/commit/7b8c4efec8aff6d6513e7ffb2f034dbddd2f6220))
