import sys
sys.dont_write_bytecode = True

import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash import Dash

from model.parameters import load_config
from ui.layouts import build_layout
from ui.callbacks import register_callbacks

CFG = load_config("parameters.yaml")

app = Dash(
    __name__,
    external_stylesheets=[
        dbc.themes.FLATLY,
        dbc.icons.BOOTSTRAP,
    ],
    suppress_callback_exceptions=True,
)
server = app.server
app.title = "CEC Optimizer"

app.layout = dmc.MantineProvider(build_layout())
register_callbacks(app, CFG)

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
