import dash_bootstrap_components as dbc
from dash import dcc, html



def etiqueta_info(text: str, tooltip: str, tooltip_id: str):
    icon_id = f"{tooltip_id}-icon"
    children: list = [html.Span(text, className="field-label")]
    if tooltip:
        children += [
            html.Span("i", id=icon_id, className="info-icon"),
            dbc.Tooltip(tooltip, target=icon_id, placement="top", className="h-tooltip"),
        ]
    return html.Div(children, className="label-row")



def kpi_card(
    value_id: str,
    title: str,
    icon: str = "bi-graph-up",
    variant: str = "brand",      
    show_icon: bool = True,
):
    body = []
    if show_icon:
        body.append(html.I(className=f"bi {icon} kpi-icon"))
    body += [
        html.Div(title, className="kpi-label"),
        html.Div(id=value_id, className="kpi-value", children="—"),
        html.Div(id=f"{value_id}-delta", className="kpi-delta"),
    ]
    return dbc.Card(
        dbc.CardBody(body),
        className=f"kpi-card {variant}",
    )



def upload_box(id_upload: str, label: str, tooltip: str):
    tip_id = f"{id_upload}-tip"
    return dbc.Card(
        dbc.CardBody(
            [
                etiqueta_info(label, tooltip, tip_id),
                dcc.Upload(
                    id=id_upload,
                    children=html.Div(
                        [
                            html.I(className="bi bi-cloud-upload upload-icon"),
                            html.Div("Arrastra o selecciona", className="upload-label"),
                            html.Div("CSV · columnas Time + datos", className="upload-hint"),
                        ]
                    ),
                    className="upload-zone",
                    multiple=False,
                ),
                html.Div(id=f"{id_upload}-name", className="upload-filename"),
            ]
        ),
        className="e-card",
    )



def tarifas_card():
    left = dbc.Card(
        dbc.CardBody(
            [
                etiqueta_info(
                    "Tipo de Tarifa",
                    "Indexada: precios variables por hora (CSV). "
                    "Mixta: uno manual y el otro por CSV. "
                    "Fija: precios constantes introducidos manualmente.",
                    "t-type",
                ),
                dbc.RadioItems(
                    id="tariff-type",
                    options=[
                        {"label": "Indexada", "value": "indexed"},
                        {"label": "Mixta",    "value": "mixed"},
                        {"label": "Fija",     "value": "fixed"},
                    ],
                    value="indexed",
                    className="yellow-choice",
                    inline=False,
                ),
            ]
        ),
        className="e-card flex-fill",
    )

    mixed_right = dbc.Collapse(
        dbc.Card(
            dbc.CardBody(
                [
                    html.Div("Tarifa mixta", className="card-title-main mb-2"),
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    etiqueta_info(
                                        "Dato manual",
                                        "El dato seleccionado se introduce manualmente. "
                                        "El otro se pide por CSV.",
                                        "t-mixed-which",
                                    ),
                                    dbc.RadioItems(
                                        id="indexed-manual-which",
                                        options=[
                                            {"label": "Compra", "value": "buy"},
                                            {"label": "Venta",  "value": "sell"},
                                        ],
                                        value="buy",
                                        className="yellow-choice",
                                    ),
                                ],
                                md=6,
                            ),
                            dbc.Col(
                                [
                                    dbc.Collapse(
                                        html.Div(
                                            [
                                                etiqueta_info("Precio compra (€/kWh)", "", "t-mixed-buy"),
                                                dbc.Input(
                                                    id="indexed-buy-manual",
                                                    type="number", min=0, step=0.001, value=0.1161,
                                                ),
                                            ]
                                        ),
                                        id="mixed-buy-wrap",
                                        is_open=True,
                                    ),
                                    dbc.Collapse(
                                        html.Div(
                                            [
                                                etiqueta_info("Precio venta (€/kWh)", "", "t-mixed-sell"),
                                                dbc.Input(
                                                    id="indexed-sell-manual",
                                                    type="number", min=0, step=0.001, value=0.0532,
                                                ),
                                            ]
                                        ),
                                        id="mixed-sell-wrap",
                                        is_open=False,
                                    ),
                                ],
                                md=6,
                            ),
                        ],
                        className="g-2 align-items-stretch",
                    ),
                ]
            ),
            className="e-card flex-fill",
        ),
        id="tariff-mixed-manual-wrap",
        is_open=False,
    )

    fixed_right = dbc.Collapse(
        dbc.Card(
            dbc.CardBody(
                [
                    html.Div("Tarifa fija", className="card-title-main mb-2"),
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    etiqueta_info("Precio compra (€/kWh)", "", "t-fixed-buy"),
                                    dbc.Input(id="fixed-buy", type="number", min=0, step=0.001, value=0.1161),
                                ],
                                md=6,
                            ),
                            dbc.Col(
                                [
                                    etiqueta_info("Precio venta (€/kWh)", "", "t-fixed-sell"),
                                    dbc.Input(id="fixed-sell", type="number", min=0, step=0.001, value=0.0532),
                                ],
                                md=6,
                            ),
                        ],
                        className="g-2 align-items-stretch",
                    ),
                ]
            ),
            className="e-card flex-fill",
        ),
        id="tariff-fixed-manual-wrap",
        is_open=False,
    )

    right = html.Div([mixed_right, fixed_right], className="flex-fill")

    return dbc.Row(
        [
            dbc.Col(left, md=6, lg=4, className="d-flex"),
            dbc.Col(right, md=6, lg=8, className="d-flex"),
        ],
        className="g-3 align-items-stretch",
    )



def run_controls():
    return html.Div(
        [
            html.Button(
                    [
                        html.Span("Opciones avanzadas", style={"fontSize": "13px", "fontWeight": "700"}),
                        html.I(className="bi bi-chevron-right", id="adv-caret",
                               style={"fontSize": "14px", "transition": "transform .15s"}),
                    ],
                    id="adv-toggle",
                    className="adv-toggle-btn",
                    n_clicks=0,
                ),

                dbc.Collapse(
                    dbc.Card(
                        dbc.CardBody(
                            dbc.Accordion(
                                [
                                    dbc.AccordionItem(
                                        [
                                            dbc.Checklist(
                                                id="exante-mode",
                                                options=[
                                                    {"label": "RD 244/2019 (4 actualizaciones/año)", "value": "rd"},
                                                    {"label": "Rígido (1 actualización/año)",        "value": "rigid"},
                                                ],
                                                value=["rd"],
                                                className="yellow-choice",
                                            ),
                                        ],
                                        title="Ex ante",
                                    ),
                                    dbc.AccordionItem(
                                        [
                                            html.Div("Frecuencias dinámicas", className="card-title-main mb-2"),
                                            dbc.Checklist(
                                                id="dynamic-modes-list",
                                                options=[
                                                    {"label": "Horaria",  "value": "hour"},
                                                    {"label": "Diaria",   "value": "day"},
                                                    {"label": "Semanal",  "value": "week"},
                                                    {"label": "Mensual",  "value": "month"},
                                                ],
                                                value=["hour"],
                                                className="yellow-choice",
                                                inline=True,
                                            ),
                                            html.Div("Solver", className="card-title-main mt-3 mb-1"),
                                            dcc.Dropdown(
                                                id="solver-name",
                                                options=[
                                                    {"label": "CBC", "value": "cbc"},
                                                    {"label": "Gurobi",            "value": "gurobi"},
                                                    {"label": "GLPK",              "value": "glpk"},
                                                ],
                                                value="gurobi",
                                                clearable=False,
                                            ),
                                        ],
                                        title="Dinámico",
                                    ),
                                    dbc.AccordionItem(
                                        [
                                            html.Div(
                                                [
                                                    html.Div([
                                                        html.Div("Almacenamiento comunitario",
                                                                 style={"fontSize": "13px", "fontWeight": "700",
                                                                        "color": "var(--text)"}),
                                                        html.Div("Batería compartida para almacenar excedente FV",
                                                                 style={"fontSize": "11px", "color": "var(--text-muted)",
                                                                        "marginTop": "1px"}),
                                                    ]),
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
                                                        dbc.Input(id="bat-capacity", type="number", value=50.0,
                                                                  min=1, max=500, step=1,
                                                                  className="param-input"),
                                                    ], md=6),
                                                    dbc.Col([
                                                        html.Div("Potencia máx. (kW)", className="param-label"),
                                                        dbc.Input(id="bat-power", type="number", value=30.0,
                                                                  min=0.5, max=250, step=0.5,
                                                                  className="param-input"),
                                                    ], md=6),
                                                    dbc.Col([
                                                        html.Div("Eficiencia carga (%)", className="param-label"),
                                                        dcc.Slider(id="bat-eta-c", min=70, max=99, step=1, value=95,
                                                                   marks={70: "70%", 85: "85%", 95: "95%", 99: "99%"},
                                                                   className="app-slider",
                                                                   tooltip={"placement": "bottom", "always_visible": False}),
                                                    ], md=6, className="mt-2"),
                                                    dbc.Col([
                                                        html.Div("Eficiencia descarga (%)", className="param-label"),
                                                        dcc.Slider(id="bat-eta-d", min=70, max=99, step=1, value=95,
                                                                   marks={70: "70%", 85: "85%", 95: "95%", 99: "99%"},
                                                                   className="app-slider",
                                                                   tooltip={"placement": "bottom", "always_visible": False}),
                                                    ], md=6, className="mt-2"),
                                                    dbc.Col([
                                                        html.Div("CAPEX (€/kWh)", className="param-label"),
                                                        dbc.Input(id="bat-fin-cost-kwp", type="number", value=250,
                                                                  min=100, max=800, step=10,
                                                                  className="param-input"),
                                                    ], md=6, className="mt-2"),
                                                    dbc.Col([
                                                        html.Div("Ciclos de vida", className="param-label"),
                                                        dbc.Input(id="bat-lifecycle-cycles", type="number", value=7000,
                                                                  min=100, max=20000, step=100,
                                                                  className="param-input"),
                                                    ], md=6, className="mt-2"),
                                                ], className="g-2 mt-1"),
                                                id="battery-params-collapse",
                                                is_open=False,
                                            ),
                                        ],
                                        title="Almacenamiento",
                                    ),
                                ],
                                start_collapsed=True,
                                flush=True,
                            )
                        ),
                        className="e-card mt-3",
                    ),
                    id="adv-collapse",
                    is_open=False,
                ),

                html.Div(
                    [
                        dcc.Loading(
                            dbc.Button(
                                "Ejecutar análisis",
                                id="run-btn",
                                color="primary",
                                className="run-btn",
                            ),
                            id="run-loading",
                            type="circle",
                            color="var(--brand)",
                        ),
                        html.Div(id="run-status", className="mt-2"),
                    ],
                    className="run-btn-wrap",
                ),
        ]
    )



def results_table():
    return dbc.Card(
        dbc.CardBody(html.Div(id="results-table")),
        className="e-card",
    )






def sample_data_section():
    return html.Div(
        [
            html.Div(
                [
                    html.Strong("Datos de ejemplo incluidos"),
                    html.P(
                        "12 usuarios · 1 año horario · PVPC indexado. "
                        "Úsalos para explorar la herramienta sin cargar archivos propios."
                    ),
                ],
                className="sample-banner-text",
            ),
            html.Button(
                [html.I(className="bi bi-database me-1"), "Usar datos de ejemplo"],
                id="sample-data-btn",
                className="sample-btn",
                n_clicks=0,
            ),
        ],
        className="sample-banner",
    )
