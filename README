# CEC Optimizer

## Descripción del proyecto

Este proyecto corresponde al Trabajo Fin de Grado del Grado en Ingeniería en Tecnologías de Telecomunicación (ICAI, Universidad Pontificia Comillas), y consiste en el desarrollo de una herramienta de optimización con interfaz web destinada a la asignación óptima de energía solar fotovoltaica entre los usuarios de una comunidad energética de autoconsumo colectivo.

El núcleo de la herramienta es un modelo de optimización lineal entera mixta (MILP), implementado en Pyomo, cuyo objetivo es minimizar el coste total de la energía para el conjunto de usuarios. El modelo calcula los coeficientes de reparto óptimos en cada período temporal, compitiendo directamente con el esquema de coeficientes fijos establecido por el Real Decreto 244/2019.

La diferencia fundamental entre el modelo ex ante fijo, impuesto por la normativa vigente, y el modelo dinámico propuesto reside en la capacidad de este último para redistribuir los excedentes de generación de forma interna, evitando que la energía no consumida se inyecte a la red a un precio muy inferior al de compra. La herramienta cuantifica este diferencial de eficiencia y lo presenta de forma visual a través de una interfaz Dash interactiva, accesible tanto para perfiles técnicos como para usuarios finales.

Adicionalmente, la herramienta incorpora un módulo de análisis de almacenamiento energético, que evalúa la viabilidad técnica y financiera de incorporar una batería comunitaria, incluyendo el cálculo del VAN, la TIR y el período de retorno de la inversión.

## Contenido del repositorio

- **`app.py`**: Punto de entrada de la aplicación. Inicializa el servidor Dash y registra todos los callbacks.
- **`optimizacion.py`**: Implementación del modelo MILP en Pyomo. Define las variables, restricciones y la función objetivo del problema de asignación energética.
- **`parameters.yaml`**: Archivo de configuración centralizado con los parámetros del modelo (eficiencias, límites, horizontes temporales, etc.).
- **`data_io.py`**: Módulo de lectura, validación y normalización de los datos de entrada (consumos, generación FV y precios).
- **`core/`**:
  - `run_pipeline.py`: Orquesta la ejecución del modelo para cada configuración seleccionada por el usuario.
- **`model/`**:
  - `parameters.py`: Clase de parámetros del modelo, con tipado, validación y carga desde `parameters.yaml`.
  - `validation.py`: Lógica de validación de los datos preparados (tipos, rangos, huecos temporales, etc.).
- **`ui/`**:
  - `layouts.py`: Define la estructura de todas las pestañas y páginas de la interfaz.
  - `callbacks.py`: Implementa la lógica reactiva de la aplicación (gráficos, KPIs, exportación, etc.).
  - `components.py`: Componentes reutilizables de la interfaz (tarjetas, controles, tablas).
- **`assets/`**: Estilos CSS personalizados, logo y recursos estáticos de la aplicación.
- **`inputs/`**: Datos de ejemplo incluidos en la distribución para explorar la herramienta sin necesidad de cargar ficheros propios. Contiene cuatro ficheros CSV: `perfiles_A.csv` (consumos horarios de 12 usuarios, año 2024), `pv_A.csv` (generación FV horaria), `precio_compra_2024.csv` y `precio_venta_2024.csv` (precios PVPC horarios de compra y venta). La ruta se configura en `parameters.yaml` bajo `paths.resources_dir`.

## Requisitos

- **Python**: >= 3.10
- Librerías principales:
  - Optimización: `pyomo`
  - Solver: `gurobi`, `cbc`, `glpk`
  - Interfaz web: `dash`, `dash-bootstrap-components`, `dash-mantine-components`
  - Visualización: `plotly`
  - Manipulación de datos: `pandas`, `numpy`
  - Exportación: `openpyxl`

## Instrucciones de uso

1. **Clonar el repositorio**:
   ```bash
   git clone https://github.com/ionatecrz/cec-optimizer.git
   cd cec-optimizer
   ```

2. **Instalar dependencias**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Ejecutar la aplicación**:
   ```bash
   python app.py
   ```
   Abrir el navegador en `http://localhost:8050`.

4. **Cargar datos o usar el ejemplo incluido**:
   - En la pestaña **Configuración**, cargar los ficheros CSV de consumos, generación FV y precios de compra/venta, o pulsar **Usar datos de ejemplo** para comenzar directamente con los datos de muestra incluidos en la carpeta `inputs/` (12 usuarios, año 2024, tarifa PVPC indexada).

5. **Ejecutar el modelo**:
   - Seleccionar el tipo de tarifa (indexada, mixta o fija), configurar las opciones avanzadas si se desea (modos dinámicos, solver, batería comunitaria) y pulsar **Ejecutar análisis**.

6. **Explorar los resultados**:
   - Navegar por las pestañas **Comparativa**, **Usuarios**, **Energía** y **Batería** para visualizar los resultados del modelo.
   - Exportar los resultados a Excel desde la sección **Exportar**.

## Funcionalidades de la herramienta

- **Configuración**:
  - Soporte para tarifas indexadas (PVPC horario), mixtas y fijas.
  - Carga de datos de consumo, generación fotovoltaica y precios mediante ficheros CSV.
  - Configuración del modo de actualización de coeficientes (ex ante RD 244/2019, ex ante rígido, dinámico horario/diario/semanal/mensual).
  - Módulo opcional de almacenamiento comunitario (batería), con configuración de capacidad, potencia máxima y eficiencias de carga y descarga.

- **Comparativa de modelos**:
  - Ranking de modelos por coste total con KPIs de ahorro absoluto y relativo frente al modelo ex ante de referencia.
  - Gráficos de ahorro acumulado en euros y en porcentaje a lo largo del período analizado.

- **Análisis por usuario**:
  - Coste individual por usuario para cada modelo ejecutado.
  - Métricas de equidad en el reparto.
  - Evolución temporal de los coeficientes alpha de reparto por usuario y modelo.

- **Flujos de energía**:
  - Perfil horario medio de precios de compra y venta.
  - Balance energético mensual: autoconsumo FV, importación de red y excedente exportado.
  - Estado de carga de la batería comunitaria (si está habilitada).
  - KPIs de generación FV total, demanda total y número de usuarios.

- **Análisis de batería**:
  - Estimación greedy de la capacidad óptima de batería.
  - Sensibilidad del ahorro al tamaño de la instalación FV (escenarios de 0.25× a 4× la potencia actual).
  - Análisis de viabilidad financiera: VAN, TIR y período de retorno en función de CAPEX, O&M, inflación del precio eléctrico, tasa de descuento y vida útil.
  - Gráficos de flujo de caja acumulado y desglose financiero (waterfall).

- **Exportación**:
  - Descarga de resultados en formato Excel (.xlsx) con selección granular de hojas: comparativa de modelos, series temporales, costes por usuario, coeficientes alpha y análisis financiero de la batería (parámetros, KPIs y flujo de caja anual) y estado de carga de la batería.

## Contexto normativo y motivación técnica

El Real Decreto 244/2019 establece en España un sistema de coeficientes de reparto fijos (ex ante) que limita la capacidad de las comunidades energéticas para redistribuir internamente los excedentes de generación. Como consecuencia, la energía no consumida por un usuario se inyecta a la red a un precio de venta típicamente 2.5-2.7 veces inferior al precio de compra (Eurostat, 2024; OMIE, 2024), en lugar de ser aprovechada por otro miembro con déficit de consumo.

Esta herramienta propone y evalúa un modelo de asignación dinámica que supera estas limitaciones, cuantificando el potencial de ahorro en escenarios reales y comparándolo de forma directa con la referencia normativa. El diseño es modular y escalable, en línea con los objetivos de la directiva europea RED III y la tendencia de los países más avanzados en gestión de comunidades energéticas (Francia, Italia, Portugal).

## Autor

- **Nombre**: Íñigo de Oñate Cruz
- **Contacto**: [LinkedIn](https://www.linkedin.com/in/%C3%AD%C3%B1igo-de-o%C3%B1ate-cruz-855b55263/)
- **Directores del TFG**: Rubén Rodríguez Vilches y Fernando Modrego Arceo
- **Centro**: ICAI, Escuela Técnica Superior de Ingeniería, Universidad Pontificia Comillas

## Licencia

Este proyecto está licenciado bajo la [MIT License](LICENSE), permitiendo su uso, modificación y distribución. 
