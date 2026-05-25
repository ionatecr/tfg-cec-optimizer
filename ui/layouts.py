import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash import dcc, html

from ui.components import (
    kpi_card, upload_box, tarifas_card, run_controls,
    sample_data_section,
)

PAGES = [
    ("config",      "bi bi-sliders",         "Configuración"),
    ("comparativa", "bi bi-speedometer2",    "Comparativa"),
    ("usuarios",    "bi bi-people",          "Usuarios"),
    ("energia",     "bi bi-sun",             "Energía"),
    ("escenarios",  "bi bi-battery-charging","Batería"),
]

_DEFAULT_PAGE = "config"


def tarjeta_grafico(title: str, graph_id: str, height: int = 320, note: str = ""):
    children = [
        html.Div(
            [html.Div(title, className="chart-title")],
            className="chart-header",
        )
    ]
    if note:
        children.append(html.Div(note, className="chart-note"))
    children.append(
        dcc.Graph(
            id=graph_id,
            config={"displayModeBar": False},
            style={"height": f"{height}px"},
        )
    )
    return dbc.Card(dbc.CardBody(children), className="chart-card mt-3")


def tarjeta_dmc(title: str, component, note: str = ""):
    children = [html.Div(title, className="chart-title")]
    if note:
        children.append(html.Div(note, className="chart-note mt-1"))
    children.append(html.Div(component, className="dmc-chart-wrap"))
    return dbc.Card(dbc.CardBody(children), className="chart-card mt-3")


def barra_lateral():
    nav_items = []
    nav_items.append(html.Div("Análisis", className="sidebar-section-label"))
    for page_id, icon_cls, label in PAGES:
        btn = html.Button(
            [
                html.I(className=f"{icon_cls} nav-icon"),
                html.Span(label),
            ],
            id=f"nav-{page_id}",
            className="nav-item-btn",
            n_clicks=0,
        )
        if page_id == "escenarios":
            nav_items.append(html.Div(btn, id="nav-bateria-wrap", style={"display": "none"}))
        else:
            nav_items.append(btn)

    return html.Div(
        [
            html.Div(
                [
                    html.Img(src="/assets/icai_logo.png", className="sidebar-logo"),
                    html.Div("TFG · ICAI", className="sidebar-product"),
                    html.Div("CEC Optimizer", className="sidebar-product-name"),
                ],
                className="sidebar-brand",
            ),
            html.Div(nav_items, className="sidebar-nav"),
            html.Div(
                html.Button(
                    [
                        html.I(className="bi bi-file-earmark-excel",
                               style={"fontSize": "16px", "flexShrink": "0"}),
                        html.Span("Exportar"),
                    ],
                    id="nav-export",
                    className="nav-item-btn",
                    n_clicks=0,
                    style={
                        "width": "100%",
                        "background": "#c9900f",
                        "color": "#ffffff",
                        "border": "none",
                        "fontWeight": "700",
                        "justifyContent": "center",
                        "gap": "8px",
                    },
                ),
                style={"padding": "0 10px 10px 10px"},
            ),
            html.Div(
                [
                    html.Span("Íñigo de Oñate Cruz"),
                    html.Span("2026"),
                ],
                className="sidebar-footer",
            ),
        ],
        className="sidebar",
    )


def barra_superior():
    return html.Div(
        [
            html.Div(
                [
                    html.Div(id="topbar-title", className="top-bar-title",
                             children="CEC Optimizer"),
                    html.Div(id="topbar-subtitle", className="top-bar-subtitle",
                             children="Optimización MILP de asignación de energía FV"),
                ]
            ),
            html.Div(
                [
                    html.Div(id="status-dot", className="status-dot"),
                    html.Div(id="status-label", children="Sin resultados",
                             style={"fontSize": "12.5px", "fontWeight": "600",
                                    "color": "var(--text-muted)"}),
                ],
                className="top-bar-status",
            ),
        ],
        className="top-bar",
    )


def tarjeta_bateria():
    return dbc.Card(
        dbc.CardBody([
            html.Div(
                [
                    html.Div(
                        [
                            html.I(className="bi bi-battery-charging",
                                   style={"fontSize": "18px", "color": "#18BC9C",
                                          "marginRight": "10px"}),
                            html.Div([
                                html.Div("Almacenamiento comunitario",
                                         style={"fontSize": "13px", "fontWeight": "700",
                                                "color": "var(--text)"}),
                                html.Div("Batería compartida para almacenar excedente FV",
                                         style={"fontSize": "11px", "color": "var(--text-muted)",
                                                "marginTop": "1px"}),
                            ]),
                        ],
                        style={"display": "flex", "alignItems": "center", "flex": "1"},
                    ),
                    dbc.Checklist(
                        options=[{"label": "", "value": "enabled"}],
                        value=[],
                        id="battery-enabled",
                        switch=True,
                        className="flex-shrink-0",
                    ),
                ],
                style={"display": "flex", "alignItems": "center",
                       "justifyContent": "space-between", "marginBottom": "12px"},
            ),
            dbc.Collapse(
                dbc.Row([
                    dbc.Col([
                        html.Div("Capacidad (kWh)", className="param-label"),
                        dbc.Input(id="bat-capacity", type="number", value=10.0,
                                  min=1, max=500, step=1,
                                  className="param-input"),
                    ], md=6),
                    dbc.Col([
                        html.Div("Potencia máx. (kW)", className="param-label"),
                        dbc.Input(id="bat-power", type="number", value=5.0,
                                  min=0.5, max=250, step=0.5,
                                  className="param-input"),
                    ], md=6),
                    dbc.Col([
                        html.Div("Eficiencia carga (%)", className="param-label"),
                        dcc.Slider(id="bat-eta-c", min=70, max=99, step=1, value=95,
                                   marks={70: "70%", 85: "85%", 95: "95%", 99: "99%"},
                                   className="app-slider",
                                   tooltip={"always_visible": False}),
                    ], md=6, className="mt-2"),
                    dbc.Col([
                        html.Div("Eficiencia descarga (%)", className="param-label"),
                        dcc.Slider(id="bat-eta-d", min=70, max=99, step=1, value=95,
                                   marks={70: "70%", 85: "85%", 95: "95%", 99: "99%"},
                                   className="app-slider",
                                   tooltip={"always_visible": False}),
                    ], md=6, className="mt-2"),
                    dbc.Col([
                        dbc.Alert(
                            [
                                html.I(className="bi bi-info-circle me-2"),
                                html.Span(
                                    "El modelo con batería añade variables de carga/descarga/SOC al LP "
                                    "y puede requerir mayor tiempo de cómputo. "
                                    "Se ejecuta combinado con el modo dinámico seleccionado."
                                ),
                            ],
                            color="info",
                            className="alert-enterprise mt-2",
                            style={"fontSize": "11px", "padding": "8px 12px"},
                        ),
                    ], md=12),
                ], className="g-2 mt-1"),
                id="battery-params-collapse",
                is_open=False,
            ),
        ]),
        className="chart-card mt-3",
    )


def pagina_config():
    return html.Div(
        [
            html.Div("Tipo de tarifa", className="section-title"),
            tarifas_card(),

            html.Div("Datos de entrada", className="section-title"),
            dbc.Row(
                [
                    dbc.Col(
                        upload_box(
                            "upload-cons", "Consumos",
                            "CSV con columna Time y columnas cons_u1…cons_uN. "
                            "Si las columnas no tienen prefijo cons_ se renombran automáticamente.",
                        ),
                        md=6, lg=3,
                    ),
                    dbc.Col(
                        upload_box(
                            "upload-pv", "Fotovoltaica",
                            "CSV con columna Time y columna de generación (pv_kWh, G_kWh, pv, …).",
                        ),
                        md=6, lg=3,
                    ),
                    dbc.Col(
                        dbc.Collapse(
                            upload_box(
                                "upload-buy", "Precio compra (CSV)",
                                "CSV con Time y columna de precio de compra (p_buy, buy_eur_kWh, …).",
                            ),
                            id="buy-upload-wrap",
                            is_open=True,
                        ),
                        md=6, lg=3,
                    ),
                    dbc.Col(
                        dbc.Collapse(
                            upload_box(
                                "upload-sell", "Precio venta (CSV)",
                                "CSV con Time y columna de precio de venta (p_sell, sell_eur_kWh, …).",
                            ),
                            id="sell-upload-wrap",
                            is_open=True,
                        ),
                        md=6, lg=3,
                    ),
                ],
                className="g-3",
            ),

            html.Div(className="mt-3"),
            sample_data_section(),

            html.Div("Ejecución", className="section-title"),
            run_controls(),
        ],
        id="page-config",
        className="inner-page",
    )


def pagina_comparativa():
    return html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(kpi_card("kpi-best-model",  "Mejor modelo",       variant="brand",   show_icon=False), md=6, lg=3),
                    dbc.Col(kpi_card("kpi-best-cost",   "Coste total",        variant="accent",  show_icon=False), md=6, lg=3),
                    dbc.Col(kpi_card("kpi-saving-pct",  "Ahorro vs ex ante",  variant="success", show_icon=False), md=6, lg=3),
                    dbc.Col(kpi_card("kpi-co2-avoided", "Importación evitada", variant="warning", show_icon=False), md=6, lg=3),
                ],
                className="g-3",
            ),

            dbc.Row(
                [
                    dbc.Col(
                        html.Div([
                            dbc.Card(
                                dbc.CardBody([
                                    html.Div("Ranking de modelos por coste total",
                                             className="chart-title mb-3"),
                                    html.Div(id="ranking-display"),
                                ]),
                                className="chart-card mt-3",
                            ),
                        ]),
                        md=6,
                    ),
                    dbc.Col(
                        html.Div([
                            tarjeta_dmc(
                                "Ahorro acumulado (%) vs referencia",
                                dmc.AreaChart(
                                    id="chart-cumulative-pct",
                                    data=[],
                                    dataKey="date",
                                    series=[{"name": "Ahorro (%)", "color": "teal.6"}],
                                    curveType="monotone",
                                    withDots=False,
                                    fillOpacity=0.15,
                                    gridAxis="y",
                                    tickLine="x",
                                    yAxisProps={"tickCount": 4, "tickSuffix": "%"},
                                    xAxisProps={"interval": 6},
                                    style={"height": "185px"},
                                ),
                            ),
                            tarjeta_dmc(
                                "Ahorro acumulado (€) vs referencia",
                                dmc.AreaChart(
                                    id="chart-cumulative-eur",
                                    data=[],
                                    dataKey="date",
                                    series=[{"name": "Ahorro (€)", "color": "blue.7"}],
                                    curveType="monotone",
                                    withDots=False,
                                    fillOpacity=0.15,
                                    gridAxis="y",
                                    tickLine="x",
                                    yAxisProps={"tickCount": 4, "tickSuffix": "€"},
                                    xAxisProps={"interval": 6},
                                    style={"height": "185px"},
                                ),
                            ),
                        ]),
                        md=6,
                    ),
                ],
                className="g-3 mt-1",
            ),

            html.Div(
                [
                    html.I(className="bi bi-trophy empty-state-icon"),
                    html.Div("Sin resultados aún", className="empty-state-title"),
                    html.Div(
                        "Ve a Configurar, carga los datos y ejecuta el modelo para ver la comparativa.",
                        className="empty-state-body",
                    ),
                ],
                id="comparativa-empty",
                className="empty-state",
            ),
        ],
        id="page-comparativa",
        className="inner-page",
        style={"display": "none"},
    )


def pagina_usuarios():
    return html.Div(
        [
            html.Div("Coste por usuario", className="section-title"),
            html.Div(id="user-cost-cards"),

            html.Div(id="user-equidad-display", className="mt-3"),

            html.Div("Coeficientes de reparto energético", className="section-title"),
            dbc.Card(
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col(
                            html.Div(
                                "Distribución del coeficiente alpha por usuario y período",
                                className="chart-title",
                            ),
                            md=8,
                        ),
                        dbc.Col(
                            dcc.Dropdown(
                                id="alpha-model-selector",
                                placeholder="Selecciona modelo…",
                                clearable=False,
                                style={"fontSize": "12px"},
                            ),
                            md=4,
                        ),
                    ], align="center", className="mb-1"),
                    dcc.Graph(
                        id="fig-alpha-evolution",
                        config={"displayModeBar": False},
                        style={"height": "300px"},
                    ),
                ]),
                className="chart-card",
            ),
            dbc.Card(
                dbc.CardBody([
                    html.Div(id="alpha-mean-table"),
                ]),
                className="chart-card mt-3",
            ),

            html.Div("Evolución de coeficientes por rango de fechas", className="section-title"),
            dbc.Card(
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col(
                            html.Div(
                                "Evolución de los coeficientes de reparto en el tiempo",
                                className="chart-title",
                            ),
                            md=12,
                        ),
                    ], className="mb-2"),
                    dbc.Row([
                        dbc.Col([
                            html.Div("Modelo", className="param-label"),
                            dcc.Dropdown(
                                id="alpha-daterange-model",
                                placeholder="Selecciona modelo…",
                                clearable=False,
                                style={"fontSize": "12px"},
                            ),
                        ], md=4),
                        dbc.Col([
                            html.Div("Fecha inicio", className="param-label"),
                            dbc.Input(
                                id="alpha-daterange-start",
                                type="date",
                                className="param-input",
                                style={"width": "100%"},
                            ),
                        ], md=4),
                        dbc.Col([
                            html.Div("Fecha fin", className="param-label"),
                            dbc.Input(
                                id="alpha-daterange-end",
                                type="date",
                                className="param-input",
                                style={"width": "100%"},
                            ),
                        ], md=4),
                    ], className="g-2 mb-2"),
                    dcc.Graph(
                        id="fig-alpha-daterange",
                        config={"displayModeBar": False},
                        style={"height": "300px"},
                    ),
                ]),
                className="chart-card mt-3",
            ),
        ],
        id="page-usuarios",
        className="inner-page",
        style={"display": "none"},
    )


def pagina_energia():
    return html.Div(
        [
            html.Div("Flujos de energía", className="section-title"),

            html.Div(id="explorer-stats-row", className="stats-grid"),

            dbc.Row(
                [
                    dbc.Col(
                        tarjeta_grafico(
                            "Perfil de precios horario medio (€/kWh)",
                            "fig-explorer-price",
                            height=240),
                        md=8,
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody([
                                html.Div("Balance energético del mejor modelo",
                                         className="chart-title mb-2"),
                                html.Div(id="energy-balance-display",
                                         style={"padding": "8px 0"}),
                            ]),
                            className="chart-card mt-3",
                        ),
                        md=4,
                    ),
                ],
                className="g-3 mt-1",
            ),

            dbc.Card(
                dbc.CardBody([
                    html.Div("Balance mensual (kWh)", className="chart-title mb-1"),
                    html.Div([
                        html.Span("● ", style={"color": "#18BC9C", "fontWeight": "700"}),
                        html.Span("Autoconsumo FV", style={"marginRight": "14px"}),
                        html.Span("● ", style={"color": "#E74C3C", "fontWeight": "700"}),
                        html.Span("Importación red", style={"marginRight": "14px"}),
                        html.Span("● ", style={"color": "#F39C12", "fontWeight": "700"}),
                        html.Span("Excedente FV", style={"marginRight": "14px"}),
                        html.Span("— % cobertura FV mensual", style={"color": "#18BC9C", "fontWeight": "700"}),
                    ], className="chart-note mb-3"),
                    html.Div(id="monthly-balance-cards", className="monthly-cards-grid"),
                ]),
                className="chart-card mt-3",
            ),

            dbc.Collapse(
                dbc.Card(
                    dbc.CardBody([
                        html.Div("Estado de carga de la batería",
                                 className="chart-title mb-1"),
                        html.Div(
                            "Evolución del nivel de carga de la batería comunitaria a lo largo del año.",
                            className="chart-note mb-2",
                        ),
                        dcc.Graph(
                            id="fig-battery-soc",
                            config={"displayModeBar": False},
                            style={"height": "240px"},
                        ),
                    ]),
                    className="chart-card mt-3",
                ),
                id="battery-soc-collapse",
                is_open=False,
            ),

            html.Div(
                "Ejecuta el modelo en Configurar para ver los flujos de energía.",
                id="explorer-placeholder",
                className="text-muted small text-center mt-4",
            ),
        ],
        id="page-energia",
        className="inner-page",
        style={"display": "none"},
    )


def fila_param(label, component):
    return html.Div([
        html.Div(label, className="param-label"),
        component,
    ], className="mb-2")


def pagina_escenarios():
    return html.Div(
        [

            dbc.Row([
                dbc.Col(kpi_card("bat-kpi-fin-payback",  "Período de retorno",  variant="brand",   show_icon=False), md=6, lg=3),
                dbc.Col(kpi_card("bat-kpi-fin-npv",      "VAN",                 variant="success", show_icon=False), md=6, lg=3),
                dbc.Col(kpi_card("bat-kpi-fin-irr",      "TIR",                 variant="accent",  show_icon=False), md=6, lg=3),
                dbc.Col(kpi_card("bat-kpi-fin-savings",  "Ahorro anualizado",variant="warning", show_icon=False), md=6, lg=3),
            ], className="g-2"),

            dbc.Row([
                dbc.Col(
                    dbc.Card(
                        dbc.CardBody([
                            html.Div("Parámetros de inversión en batería",
                                     className="chart-title mb-2"),
                            fila_param("CAPEX batería (€/kWh)",
                                html.Div(id="bat-fin-capex-display",
                                         style={"fontSize": "13px", "fontWeight": "700",
                                                "color": "var(--text)", "paddingTop": "4px"})),
                            fila_param("Capacidad instalada",
                                html.Div(id="bat-fin-capacity-display",
                                         style={"fontSize": "13px", "fontWeight": "700",
                                                "color": "var(--text)", "paddingTop": "4px"})),
                            fila_param("O&M anual (% CAPEX)",
                                dcc.Slider(id="bat-fin-om-pct", min=0, max=5.0, step=0.25,
                                           value=3.0,
                                           marks={0: "0%", 1: "1%", 2: "2%", 3: "3%", 4: "4%", 5: "5%"},
                                           tooltip={"always_visible": False},
                                           className="app-slider")),
                            fila_param("Inflación precio eléctrico (%/año)",
                                dcc.Slider(id="bat-fin-inflation", min=0, max=6, step=0.5,
                                           value=3.0,
                                           marks={0: "0%", 2: "2%", 3: "3%", 4: "4%", 6: "6%"},
                                           tooltip={"always_visible": False},
                                           className="app-slider")),
                            fila_param("Tasa de descuento (%/año)",
                                dcc.Slider(id="bat-fin-discount", min=1, max=10, step=0.5,
                                           value=2.5,
                                           marks={1: "1%", 5: "5%", 8: "8%", 10: "10%"},
                                           tooltip={"always_visible": False},
                                           className="app-slider")),
                            fila_param("Vida útil estimada (años)",
                                html.Div(id="bat-fin-lifetime-display",
                                         style={"fontSize": "13px", "fontWeight": "700",
                                                "color": "var(--text)", "paddingTop": "4px"})),
                        ]),
                        className="chart-card h-100",
                    ),
                    md=4,
                ),
                dbc.Col(
                    dbc.Card(
                        dbc.CardBody([
                            html.Div("Flujo de caja acumulado (€)", className="chart-title mb-2"),
                            dcc.Graph(id="bat-fig-fin-cashflow",
                                      config={"displayModeBar": False},
                                      style={"height": "340px"}),
                        ]),
                        className="chart-card h-100",
                    ),
                    md=8,
                ),
            ], className="g-2 mt-1"),

            dbc.Row([
                dbc.Col(
                    dbc.Card(
                        dbc.CardBody([
                            html.Div("Desglose financiero",
                                     style={"fontSize": "15px", "fontWeight": "700",
                                            "color": "var(--text)", "marginBottom": "4px"}),
                            dcc.Graph(id="bat-fig-fin-waterfall",
                                      config={"displayModeBar": False},
                                      style={"height": "320px"}),
                        ]),
                        className="chart-card",
                    ),
                    md=12,
                ),
            ], className="g-2 mt-1"),

            dbc.Row([
                dbc.Col(
                    dbc.Card(
                        dbc.CardBody([
                            html.Div(
                                "Ahorro anual del reparto dinámico frente al almacenamiento",
                                className="chart-title mb-2",
                            ),
                            dcc.Graph(
                                id="bat-fig-comparison",
                                config={"displayModeBar": False},
                                style={"height": "360px"},
                            ),
                        ]),
                        className="chart-card",
                    ),
                    md=12,
                ),
            ], className="g-2 mt-1"),

            html.Div(
                [
                    html.I(className="bi bi-calculator",
                           style={"fontSize": "28px", "color": "var(--text-muted)",
                                  "marginBottom": "8px"}),
                    html.Div("Sin análisis de batería",
                             style={"fontWeight": "700", "color": "var(--text-muted)",
                                    "fontSize": "13px"}),
                    html.Div("Ejecuta el modelo con batería habilitada para calcular "
                             "la viabilidad financiera.",
                             style={"fontSize": "11px", "color": "var(--text-muted)",
                                    "marginTop": "4px", "textAlign": "center"}),
                ],
                id="bat-financiero-empty",
                style={"display": "none", "flexDirection": "column",
                       "alignItems": "center", "justifyContent": "center",
                       "padding": "32px 16px"},
            ),

        ],
        id="page-escenarios",
        className="inner-page",
        style={"display": "none"},
    )


def pagina_financiero():
    def fila_param(label, component):
        return html.Div([
            html.Div(label, className="param-label"),
            component,
        ], className="mb-3")

    return html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(kpi_card("kpi-fin-payback",  "Período de retorno",  variant="brand",   show_icon=False), md=6, lg=3),
                    dbc.Col(kpi_card("kpi-fin-npv",      "VAN",                 variant="success", show_icon=False), md=6, lg=3),
                    dbc.Col(kpi_card("kpi-fin-irr",      "TIR",                 variant="accent",  show_icon=False), md=6, lg=3),
                    dbc.Col(kpi_card("kpi-fin-savings",  "Ahorro anual base",   variant="warning", show_icon=False), md=6, lg=3),
                ],
                className="g-3",
            ),

            dbc.Row([
                dbc.Col(
                    dbc.Card(
                        dbc.CardBody([
                            html.Div("Parámetros de inversión", className="chart-title mb-3"),

                            fila_param("CAPEX instalación FV (€/kWp)",
                                dbc.Input(id="fin-cost-kwp", type="number", value=1000,
                                          min=100, max=5000, step=50, className="param-input")),

                            fila_param("Potencia instalada (kWp)",
                                dbc.Input(id="fin-power-kwp", type="number", value=50.0,
                                          min=0.5, max=1000, step=0.5, className="param-input")),

                            fila_param("Coste O&M anual (% del CAPEX)",
                                dcc.Slider(id="fin-om-pct", min=0.5, max=3.0, step=0.25,
                                           value=3.0,
                                           marks={0.5: "0.5%", 1: "1%", 2: "2%", 3: "3%"},
                                           tooltip={"always_visible": False},
                                           className="app-slider")),

                            fila_param("Inflación precio eléctrico (% anual)",
                                dcc.Slider(id="fin-inflation", min=0, max=6, step=0.5,
                                           value=3.0,
                                           marks={0: "0%", 2: "2%", 3: "3%", 4: "4%", 6: "6%"},
                                           tooltip={"always_visible": False},
                                           className="app-slider")),

                            fila_param("Tasa de descuento (% anual)",
                                dcc.Slider(id="fin-discount", min=1, max=10, step=0.5,
                                           value=5.0,
                                           marks={1: "1%", 5: "5%", 8: "8%", 10: "10%"},
                                           tooltip={"always_visible": False},
                                           className="app-slider")),

                            fila_param("Vida útil del proyecto (años)",
                                dcc.Slider(id="fin-lifetime", min=10, max=30, step=1,
                                           value=25,
                                           marks={10: "10a", 15: "15a", 20: "20a",
                                                  25: "25a", 30: "30a"},
                                           tooltip={"always_visible": False},
                                           className="app-slider")),
                        ]),
                        className="chart-card mt-3 h-100",
                    ),
                    md=4,
                ),

                dbc.Col(
                    html.Div([
                        tarjeta_grafico(
                            "Flujo de caja acumulado (€)",
                            "fig-fin-cashflow",
                            height=300,
                            note="La línea cruza el eje en el año de retorno (payback)",
                        ),
                        tarjeta_grafico(
                            "Desglose financiero del proyecto",
                            "fig-fin-waterfall",
                            height=260,
                            note="Inversión · Ahorros brutos · O&M → VAN neto",
                        ),
                    ]),
                    md=8,
                ),
            ], className="g-3 mt-1"),

            html.Div(
                [
                    html.I(className="bi bi-coin empty-state-icon"),
                    html.Div("Sin datos de análisis", className="empty-state-title"),
                    html.Div(
                        "Ejecuta primero el modelo de optimización para disponer de los ahorros anuales.",
                        className="empty-state-body",
                    ),
                ],
                id="financiero-empty",
                className="empty-state",
            ),
        ],
        id="page-financiero",
        className="inner-page",
        style={"display": "none"},
    )


def pagina_export():
    _SECTIONS = [
        ("comparativa", "bi bi-table",          "#014593",
         "Comparativa de modelos",
         "Resumen de KPIs, costes y métricas de todos los modelos optimizados"),
        ("series",      "bi bi-graph-up",        "#18BC9C",
         "Series temporales",
         "Datos hora a hora: autoconsumo, importación, exportación y coste"),
        ("costes",      "bi bi-people-fill",     "#F39C12",
         "Coste por usuario",
         "Desglose individual: coste ex ante, dinámico y ahorro por usuario"),
        ("alpha",       "bi bi-sliders2",        "#9B59B6",
         "Coeficientes alpha de reparto",
         "Media del coeficiente alpha por modelo y usuario (solo períodos con FV)"),
    ]

    _SECTIONS_BAT = [
        ("bateria_fin", "bi bi-calculator",       "#014593",
         "Análisis financiero de la Batería",
         "Parámetros, VAN, TIR, payback y flujo de caja anual"),
        ("bateria_soc", "bi bi-activity",          "#18BC9C",
         "Estado de carga de la Batería",
         "Serie horaria del nivel de carga de la batería comunitaria"),
    ]

    def fila_seccion(value, icon, color, title, desc, last=False):
        return html.Div([
            html.Div([
                html.Div(
                    html.I(className=icon,
                           style={"fontSize": "15px", "color": color}),
                    style={
                        "width": "36px", "height": "36px", "borderRadius": "8px",
                        "background": f"color-mix(in srgb, {color} 12%, white)",
                        "display": "flex", "alignItems": "center",
                        "justifyContent": "center", "flexShrink": "0",
                    },
                ),
                html.Div([
                    html.Div(title, style={
                        "fontSize": "13px", "fontWeight": "600",
                        "color": "var(--text)", "lineHeight": "1.2",
                    }),
                    html.Div(desc, style={
                        "fontSize": "11px", "color": "var(--text-muted)", "marginTop": "2px",
                    }),
                ]),
            ], style={"display": "flex", "gap": "12px", "alignItems": "center",
                      "flex": "1", "minWidth": "0"}),
            dbc.Checklist(
                options=[{"label": "", "value": value}],
                value=[value],
                id=f"export-sw-{value}",
                switch=True,
                className="flex-shrink-0",
                style={"marginLeft": "8px"},
            ),
        ], style={
            "display": "flex", "alignItems": "center",
            "padding": "14px 16px",
            **({} if last else {"borderBottom": "1px solid var(--border, #e2e8f0)"}),
        })

    section_rows = [
        fila_seccion(v, ic, col, title, desc, last=(i == len(_SECTIONS) - 1))
        for i, (v, ic, col, title, desc) in enumerate(_SECTIONS)
    ]

    bat_section_rows = [
        fila_seccion(v, ic, col, title, desc, last=(i == len(_SECTIONS_BAT) - 1))
        for i, (v, ic, col, title, desc) in enumerate(_SECTIONS_BAT)
    ]

    return html.Div([
        dbc.Row([
            dbc.Col(
                dbc.Card(
                    dbc.CardBody([
                        html.Div("Contenido a exportar", style={
                            "fontSize": "11px", "fontWeight": "700",
                            "color": "var(--text-muted)", "textTransform": "uppercase",
                            "letterSpacing": "0.5px", "marginBottom": "4px",
                        }),
                        html.Div("Activa o desactiva cada hoja del archivo",
                                 style={"fontSize": "11px", "color": "#94a3b8",
                                        "marginBottom": "14px"}),
                        *section_rows,
                        dbc.Collapse(
                            html.Div(
                                bat_section_rows,
                                style={"borderTop": "1px solid var(--border, #e2e8f0)"},
                            ),
                            id="export-battery-collapse",
                            is_open=False,
                        ),
                    ]),
                    className="chart-card h-100",
                ),
                md=5,
            ),
            dbc.Col(
                dbc.Card(
                    dbc.CardBody([
                        html.Div([
                            html.Span("Vista previa", style={
                                "fontSize": "11px", "fontWeight": "700",
                                "color": "var(--text-muted)", "textTransform": "uppercase",
                                "letterSpacing": "0.5px",
                            }),
                        ], style={"marginBottom": "4px"}),
                        html.Div("Primeras filas de la hoja Comparativa",
                                 style={"fontSize": "11px", "color": "#94a3b8",
                                        "marginBottom": "14px"}),
                        html.Div(id="export-preview-content",
                                 style={"overflowX": "auto"}),
                        html.Div(
                            dbc.Button(
                                "Descargar Excel",
                                id="export-excel-btn", color="success",
                                className="w-100 mt-3",
                                style={"fontWeight": "600"},
                            ),
                        ),
                        dcc.Download(id="download-excel"),
                        html.Div(id="export-sheets-info", style={"display": "none"}),
                    ]),
                    className="chart-card",
                ),
                md=7,
            ),
        ], className="g-4"),
    ],
    id="page-export",
    className="inner-page",
    style={"display": "none"})


def build_layout():
    return html.Div(
        [
            dcc.Store(id="results-store"),
            dcc.Store(id="run-tag-store"),
            dcc.Store(id="nav-store", data=_DEFAULT_PAGE),
            dcc.Store(id="bat-optimal-store"),
            dcc.Store(id="fin-results-store"),

            html.Div(
                [
                    barra_lateral(),

                    html.Div(
                        [
                            barra_superior(),
                            pagina_config(),
                            pagina_comparativa(),
                            pagina_usuarios(),
                            pagina_energia(),
                            pagina_escenarios(),
                            pagina_export(),
                        ],
                        className="page-content",
                    ),
                ],
                className="app-shell",
            ),
        ]
    )
