import base64
import io
import json
import math
import zipfile
from datetime import datetime
import pandas as pd
import plotly.graph_objects as go
import dash_bootstrap_components as dbc

from dash import Input, Output, State, ctx, html, no_update
from core.run_pipeline import run_pipeline


COLORWAY = ["#2C3E50", "#18BC9C", "#3498DB", "#F39C12", "#E74C3C", "#9B59B6",
            "#1ABC9C", "#E67E22", "#8E44AD", "#2980B9"]

COLOR_EX_ANTE  = "#014593"
COLOR_DYNAMIC  = "#18BC9C"
COLOR_PV       = "#F39C12"
COLOR_DEMAND   = "#E74C3C"
COLOR_SAVING   = "#27AE60"

_MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
          "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

_USER_PALETTE = ["#014593", "#18BC9C", "#F39C12", "#9B59B6",
                 "#E74C3C", "#2980B9", "#16A085", "#D35400"]

PAGE_IDS = ["config", "comparativa", "usuarios", "energia",
            "escenarios", "export"]

PAGE_TITLES = {
    "config":      "Configurar análisis",
    "comparativa": "Comparativa de modelos",
    "usuarios":    "Impacto por usuario",
    "energia":     "Flujos de energía",
    "escenarios":  "Análisis de batería",
    "export":      "Exportar",
}

CO2_FACTOR_KG_KWH = 0.25



def formato_num(x, dec: int = 0) -> str:
    try:
        s = f"{float(x):,.{dec}f}"
        return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    except (TypeError, ValueError):
        return "—"


def formato_eur(x):
    try:    return f"{formato_num(float(x), 2)} €"
    except (ValueError, TypeError): return ""


def formato_pct(x):
    try:    return f"{formato_num(float(x), 2)} %"
    except (ValueError, TypeError): return ""


def a_float(x, default: float = 0.0) -> float:
    try:    return float(x)
    except (ValueError, TypeError): return default


def _sf(v, fallback: float = 0.0) -> float:
    try:
        f = float(v)
        return f if math.isfinite(f) else fallback
    except (TypeError, ValueError):
        return fallback


def col_tiempo(df: pd.DataFrame) -> str | None:
    for c in ["Time", "time", "timestamp", "datetime", "t"]:
        if c in df.columns:
            return c
    return None


def primera_col(cols: list[str], candidates: list[str]) -> str | None:
    for c in candidates:
        if c in cols:
            return c
    return None


def grafico_vacio(msg: str) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        annotations=[dict(
            text=msg, x=0.5, y=0.5,
            xref="paper", yref="paper",
            showarrow=False,
            font=dict(color="#8899AA", size=13),
        )],
    )
    return fig


def estilo_grafico(
    fig: go.Figure,
    y_title: str | None = None,
    y2_title: str | None = None,
    barmode: str = "group",
    hovermode: str = "x",
) -> go.Figure:
    fig.update_layout(
        margin=dict(l=12, r=12, t=8, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        colorway=COLORWAY,
        hovermode=hovermode,
        barmode=barmode,
        separators=",.",
        legend=dict(
            orientation="h",
            x=0, y=-0.18,
            xanchor="left",
            bgcolor="rgba(0,0,0,0)",
            borderwidth=0,
            font=dict(size=11, color="#6B7280"),
        ),
        hoverlabel=dict(
            bgcolor="#1e293b",
            bordercolor="#1e293b",
            font=dict(color="#f8fafc", size=12),
        ),
    )
    fig.update_xaxes(
        showgrid=False,
        zeroline=False,
        linecolor="var(--border, #DDE3ED)",
        tickfont=dict(size=11, color="#9CA3AF"),
    )
    fig.update_yaxes(
        showgrid=True,
        gridcolor="rgba(0,0,0,0.04)",
        zeroline=False,
        title=y_title or "",
        tickfont=dict(size=11, color="#9CA3AF"),
        title_font=dict(size=11, color="#9CA3AF"),
    )

    if y2_title:
        fig.update_layout(
            yaxis2=dict(
                title=y2_title,
                overlaying="y", side="right",
                showgrid=False, zeroline=False,
            )
        )

    for tr in fig.data:
        name = tr.name or ""
        if tr.type in ("scatter", "scattergl"):
            tr.update(line=dict(width=2))
        elif tr.type == "bar":
            tr.update(marker=dict(opacity=0.9))
    return fig



def extraer_resultados(results):
    if isinstance(results, (tuple, list)) and len(results) == 2:
        a, b = results
        summary = a if isinstance(a, dict) else (b if isinstance(b, dict) else {})
        ts = b if hasattr(b, "to_dict") else (a if hasattr(a, "to_dict") else pd.DataFrame())
        if ts is None or not isinstance(ts, pd.DataFrame):
            ts = pd.DataFrame()
        return summary, ts
    if isinstance(results, dict):
        return results, pd.DataFrame()
    return {}, pd.DataFrame()


def get_serie(series: dict, model_key: str) -> pd.DataFrame:
    s = (series or {}).get(model_key) or {}
    rows = s.get("rows") or []
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def calcular_porcentajes(summary: dict, which: str):
    d_tot = a_float(summary.get("demand_total", 0.0))
    g_tot = a_float(summary.get("gen_total",    0.0))

    if which == "ex_ante":
        self_kwh = a_float(summary.get("self_ex_ante", 0.0))
        exp_kwh  = a_float(summary.get("exp_ex_ante",  0.0))
        imp_kwh  = a_float(summary.get("imp_ex_ante",  0.0))
        cost     = a_float(summary.get("cost_ex_ante", 0.0))
    elif which == "fijo":
        self_kwh = a_float(summary.get("self_fixed", 0.0))
        exp_kwh  = a_float(summary.get("exp_fixed",  0.0))
        imp_kwh  = a_float(summary.get("imp_fixed",  0.0))
        cost     = a_float(summary.get("cost_fixed", 0.0))
    else:
        self_kwh = a_float(summary.get("self_prop", 0.0))
        exp_kwh  = a_float(summary.get("exp_prop",  0.0))
        imp_kwh  = a_float(summary.get("imp_prop",  0.0))
        cost     = a_float(summary.get("cost_prop", 0.0))

    self_pct = (self_kwh / d_tot * 100.0) if d_tot > 1e-12 else 0.0
    imp_pct  = (imp_kwh  / d_tot * 100.0) if d_tot > 1e-12 else 0.0
    exp_pct  = (exp_kwh  / g_tot * 100.0) if g_tot > 1e-12 else 0.0
    return cost, self_kwh, self_pct, exp_kwh, exp_pct, imp_kwh, imp_pct


def coste_por_usuario(summary: dict, which: str) -> dict[str, float]:
    if which == "ex_ante":
        key = "cost_per_user_ex_ante"
    elif which == "fijo":
        key = "cost_per_user_fixed"
    elif which == "bat":
        key = "cost_per_user_bat"
    else:
        key = "cost_per_user_prop"
    raw = summary.get(key, {}) or {}
    names = summary.get("user_display_names", {}) or {}
    return {names.get(k, k): v for k, v in raw.items()}



def crear_excel(payload: dict, run_tag: str, sections: list[str], fin_store: dict | None = None) -> bytes:
    from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    HDR_FILL    = PatternFill("solid", fgColor="014593")
    HDR_FONT    = Font(bold=True, color="FFFFFF", size=10)
    ALT_FILL    = PatternFill("solid", fgColor="F0F3F8")
    THIN_BORDER = Border(bottom=Side(style="thin", color="DDE3ED"))
    CENTER      = Alignment(horizontal="center", vertical="center", wrap_text=True)
    LEFT        = Alignment(horizontal="left",   vertical="center")
    RIGHT_AL    = Alignment(horizontal="right",  vertical="center")

    def _write_df(ws, df, title=None):
        r = 1
        if title:
            c = ws.cell(r, 1, title)
            c.font = Font(bold=True, size=12, color="014593")
            r += 1
            c2 = ws.cell(r, 1, f"CEC Optimizer · {run_tag}")
            c2.font = Font(size=9, color="6B7280", italic=True)
            r += 2

        for ci, col in enumerate(df.columns, 1):
            cell = ws.cell(r, ci, str(col))
            cell.fill = HDR_FILL
            cell.font = HDR_FONT
            cell.alignment = CENTER
        r += 1

        for row_i, (_, row) in enumerate(df.iterrows()):
            is_alt = row_i % 2 == 1
            for ci, val in enumerate(row, 1):
                cell = ws.cell(r, ci, val if not (isinstance(val, float) and val != val) else None)
                if is_alt:
                    cell.fill = ALT_FILL
                cell.border = THIN_BORDER
                cell.alignment = RIGHT_AL if isinstance(val, (int, float)) else LEFT
            r += 1

        for ci, col in enumerate(df.columns, 1):
            try:
                max_len = max(len(str(col)),
                              df[col].astype(str).str.len().max() if not df.empty else 0)
            except Exception:
                max_len = len(str(col))
            ws.column_dimensions[get_column_letter(ci)].width = min(int(max_len) + 4, 45)
        ws.freeze_panes = ws.cell(r - len(df), 1)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        wb = writer.book

        _SHEET_INFO = {
            "comparativa": ("Comparison",          "Model comparison: cost, self-consumption, import/export ratios and energy KPIs for each optimised allocation model."),
            "series":      ("Time Series",         "Hourly time series: PV generation, demand, prices, self-consumption, grid import/export and cost for each model and timestamp."),
            "costes":      ("Cost per User",       "Individual user costs: total cost breakdown per user for each optimised model."),
            "alpha":       ("Alpha Coeff.",        "Sharing coefficients: mean allocation coefficient \u03b1 per user and model (solar generation periods only)."),
            "bateria_fin": ("Battery - Financial", "Battery financial analysis: CAPEX, NPV, IRR, payback period and annual cash flow."),
            "bateria_soc": ("Battery - SOC",       "Battery state of charge: hourly SOC profile of the community battery throughout the optimisation horizon."),
        }
        ws_info = wb.create_sheet("Information")
        _ic1 = ws_info.cell(1, 1, "CEC Optimizer \u2014 Exported File Guide")
        _ic1.font = Font(bold=True, size=13, color="014593")
        _ic2 = ws_info.cell(2, 1, f"Run: {run_tag}")
        _ic2.font = Font(size=9, color="6B7280", italic=True)
        _ic3 = ws_info.cell(3, 1, "This file contains the following sheets:")
        _ic3.font = Font(size=10, color="374151")
        _r_info = 5
        _ih1 = ws_info.cell(_r_info, 1, "Sheet")
        _ih1.fill = HDR_FILL; _ih1.font = HDR_FONT; _ih1.alignment = CENTER
        _ih2 = ws_info.cell(_r_info, 2, "Description")
        _ih2.fill = HDR_FILL; _ih2.font = HDR_FONT; _ih2.alignment = CENTER
        _r_info += 1
        for _sec in sections:
            if _sec in _SHEET_INFO:
                _sn, _sd = _SHEET_INFO[_sec]
                _c1 = ws_info.cell(_r_info, 1, _sn)
                _c1.font = Font(bold=True, size=10); _c1.alignment = LEFT; _c1.border = THIN_BORDER
                _c2 = ws_info.cell(_r_info, 2, _sd)
                _c2.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
                _c2.border = THIN_BORDER
                _r_info += 1
        ws_info.column_dimensions["A"].width = 24
        ws_info.column_dimensions["B"].width = 72

        _COL_RENAME = {
            "Modelo":             "Model",
            "Coste (€)":          "Cost (EUR)",
            "% Autoconsumo":      "Self-cons. (%)",
            "% Excedente":        "Surplus (%)",
            "% Importacion":      "Import (%)",
            "% Importación":      "Import (%)",
            "Autoconsumo (kWh)":  "Self-cons. (kWh)",
            "Excedente (kWh)":    "Surplus (kWh)",
            "Importacion (kWh)":  "Import (kWh)",
            "Importación (kWh)":  "Import (kWh)",
        }
        _TS_RENAME = {
            "Modelo":        "Model",
            "Time":          "Timestamp",
            "pv_kWh":        "PV (kWh)",
            "demand_kWh":    "Demand (kWh)",
            "p_buy":         "Buy price (EUR/kWh)",
            "p_sell":        "Sell price (EUR/kWh)",
            "self_ex_ante":  "Self-cons. ExAnte (kWh)",
            "imp_ex_ante":   "Import ExAnte (kWh)",
            "exp_ex_ante":   "Export ExAnte (kWh)",
            "cost_ex_ante":  "Cost ExAnte (EUR)",
            "self_prop":     "Self-cons. Dynamic (kWh)",
            "imp_prop":      "Import Dynamic (kWh)",
            "exp_prop":      "Export Dynamic (kWh)",
            "cost_prop":     "Cost Dynamic (EUR)",
        }

        def _user_to_en(name: str) -> str:
            return name.replace("Usuario ", "User ") if name.startswith("Usuario ") else name

        if "comparativa" in sections:
            df_m = pd.DataFrame(payload.get("models", []))
            drop = [c for c in df_m.columns
                    if c.startswith("cost_per_user") or c in ("users_display", "Tipo")]
            df_m = df_m.drop(columns=drop, errors="ignore")
            num  = df_m.select_dtypes("number").columns
            df_m[num] = df_m[num].round(2)
            df_m = df_m.rename(columns=_COL_RENAME)
            ws = wb.create_sheet("Comparison")
            _write_df(ws, df_m, "Model Comparison")

        if "series" in sections:
            series = payload.get("series", {}) or {}
            frames = []
            for label, s in series.items():
                rows = (s or {}).get("rows") or []
                if rows:
                    df_s = pd.DataFrame(rows)
                    df_s.insert(0, "Modelo", label)
                    frames.append(df_s)
            if frames:
                df_ts = pd.concat(frames, ignore_index=True)
                keep  = ["Modelo", "Time", "pv_kWh", "demand_kWh", "p_buy", "p_sell",
                         "self_ex_ante", "imp_ex_ante", "exp_ex_ante", "cost_ex_ante",
                         "self_prop", "imp_prop", "exp_prop", "cost_prop"]
                df_ts = df_ts[[c for c in keep if c in df_ts.columns]].round(4)
                df_ts = df_ts.rename(columns=_TS_RENAME)
                ws = wb.create_sheet("Time Series")
                _write_df(ws, df_ts, "Time Series")

        if "costes" in sections:
            rows_c = []
            for m in payload.get("models", []):
                per_u = m.get("cost_per_user") or {}
                row_c = {"Model": m["Modelo"]}
                row_c.update({_user_to_en(u): round(float(v), 2) for u, v in per_u.items()})
                rows_c.append(row_c)
            if rows_c:
                ws = wb.create_sheet("Cost per User")
                _write_df(ws, pd.DataFrame(rows_c), "Cost per User (EUR)")

        if "alpha" in sections:
            series = payload.get("series", {}) or {}
            rows_a = []
            for m in payload.get("models", []):
                label  = m["Modelo"]
                tipo   = m.get("Tipo", "ex_ante")
                prefix = ("alpha_ex_" if tipo == "ex_ante"
                          else "alpha_fx_" if tipo == "fijo"
                          else "alpha_prop_")
                s_data = series.get(label, {})
                ts_rows = (s_data or {}).get("rows") or []
                if not ts_rows:
                    continue
                df_ts   = pd.DataFrame(ts_rows)
                a_cols  = sorted([c for c in df_ts.columns if c.startswith(prefix)])
                ud      = m.get("users_display") or [f"U{i+1}" for i in range(len(a_cols))]
                fv_mask = pd.to_numeric(df_ts.get("pv_kWh", pd.Series(dtype=float)),
                                        errors="coerce").fillna(0) > 0.01
                row_a = {"Model": label}
                for i, col in enumerate(a_cols):
                    vals   = pd.to_numeric(df_ts.loc[fv_mask, col], errors="coerce").dropna()
                    u_name = _user_to_en(ud[i]) if i < len(ud) else f"U{i+1}"
                    row_a[f"{u_name} (%)"] = round(vals.mean() * 100, 1) if not vals.empty else None
                rows_a.append(row_a)
            if rows_a:
                ws = wb.create_sheet("Alpha Coeff.")
                _write_df(ws, pd.DataFrame(rows_a), "Mean Sharing Coefficient alpha (%)")

        if "bateria_fin" in sections and fin_store:
            p          = fin_store.get("params", {})
            optimal_cap = float(fin_store.get("optimal_cap") or 0)
            investment  = float(fin_store.get("investment")  or 0)
            om_annual   = float(fin_store.get("om_annual")   or 0)
            annual_sav  = float(fin_store.get("annual_savings") or 0)
            npv         = float(fin_store.get("npv") or 0)
            irr         = fin_store.get("irr")
            payback     = fin_store.get("payback")
            cumulative  = fin_store.get("cumulative") or []
            years       = fin_store.get("years") or list(range(len(cumulative)))
            inflation_v = float(p.get("inflation_pct", 3.0)) / 100.0
            lifetime_v  = int(p.get("lifetime", 15))

            ws_fin = wb.create_sheet("Battery - Financial")
            params_df = pd.DataFrame([
                {"Parameter": "Battery CAPEX (EUR/kWh)",         "Value": p.get("capex_kwh", "-")},
                {"Parameter": "Installed capacity (kWh)",        "Value": round(optimal_cap, 1)},
                {"Parameter": "Total investment (EUR)",          "Value": round(investment, 2)},
                {"Parameter": "O&M annual (% CAPEX)",            "Value": p.get("om_pct", "-")},
                {"Parameter": "O&M annual (EUR)",                "Value": round(om_annual, 2)},
                {"Parameter": "Electricity price inflation (%/yr)", "Value": p.get("inflation_pct", "-")},
                {"Parameter": "Discount rate (%/yr)",            "Value": p.get("discount_pct", "-")},
                {"Parameter": "Useful life (years)",             "Value": p.get("lifetime", "-")},
            ])
            _write_df(ws_fin, params_df, "Battery -- Financial Parameters and Results")
            row_offset = len(params_df) + 6
            results_df = pd.DataFrame([
                {"Metric": "Estimated annual savings (EUR/yr)", "Value": round(annual_sav, 2)},
                {"Metric": "NPV - Net Present Value (EUR)",     "Value": round(npv, 2)},
                {"Metric": "IRR - Internal Rate of Return",     "Value": f"{irr*100:.2f}%" if irr else "-"},
                {"Metric": "Payback period (years)",            "Value": f"{payback:.1f}" if payback else "> 100"},
            ])
            r_start = row_offset + 1
            c_hdr = ws_fin.cell(r_start, 1, "Financial Results")
            c_hdr.font = Font(bold=True, size=11, color="014593")
            r_start += 1
            for ci, col in enumerate(results_df.columns, 1):
                cell = ws_fin.cell(r_start, ci, str(col))
                cell.fill = HDR_FILL; cell.font = HDR_FONT; cell.alignment = CENTER
            r_start += 1
            for ri, (_, row) in enumerate(results_df.iterrows()):
                is_alt = ri % 2 == 1
                for ci, val in enumerate(row, 1):
                    cell = ws_fin.cell(r_start, ci, val)
                    if is_alt: cell.fill = ALT_FILL
                    cell.border = THIN_BORDER
                    cell.alignment = LEFT
                r_start += 1
            r_start += 1
            c_cf = ws_fin.cell(r_start, 1, "Annual Cash Flow")
            c_cf.font = Font(bold=True, size=11, color="014593")
            r_start += 1
            cf_rows = []
            for i, yr in enumerate(years):
                if yr == 0:
                    cf_rows.append({"Year": 0, "Savings (EUR)": 0.0,
                                    "O&M (EUR)": 0.0, "Net flow (EUR)": round(-investment, 2),
                                    "Cumulative (EUR)": round(cumulative[i], 2)})
                else:
                    infl_f = (1 + inflation_v) ** (yr - 1)
                    sav_yr = round(annual_sav * infl_f, 2)
                    om_yr  = round(om_annual  * infl_f, 2)
                    net_yr = round(sav_yr - om_yr, 2)
                    cf_rows.append({"Year": yr, "Savings (EUR)": sav_yr,
                                    "O&M (EUR)": round(-om_yr, 2),
                                    "Net flow (EUR)": net_yr,
                                    "Cumulative (EUR)": round(cumulative[i], 2)})
            cf_df = pd.DataFrame(cf_rows)
            for ci, col in enumerate(cf_df.columns, 1):
                cell = ws_fin.cell(r_start, ci, str(col))
                cell.fill = HDR_FILL; cell.font = HDR_FONT; cell.alignment = CENTER
            r_start += 1
            for ri, (_, row) in enumerate(cf_df.iterrows()):
                is_alt = ri % 2 == 1
                for ci, val in enumerate(row, 1):
                    cell = ws_fin.cell(r_start, ci, val)
                    if is_alt: cell.fill = ALT_FILL
                    cell.border = THIN_BORDER
                    cell.alignment = RIGHT_AL if isinstance(val, (int, float)) else LEFT
                r_start += 1
            for ci in range(1, len(cf_df.columns) + 1):
                ws_fin.column_dimensions[get_column_letter(ci)].width = 22

        if "bateria_soc" in sections:
            bat_model = next(
                (m for m in (payload.get("models") or [])
                 if m.get("Tipo") == "bateria" and m.get("Coste (€)") is not None),
                None,
            )
            if bat_model:
                bat_label   = bat_model["Modelo"]
                bat_cap_kwh = float(bat_model.get("battery_capacity_kwh") or 50.0)
                series_data = payload.get("series", {}) or {}
                s_data      = series_data.get(bat_label, {})
                soc_rows    = (s_data or {}).get("rows") or []
                if soc_rows:
                    df_soc = pd.DataFrame(soc_rows)
                    if "soc_bat" in df_soc.columns:
                        df_soc["soc_bat"] = pd.to_numeric(df_soc["soc_bat"], errors="coerce")
                        df_soc["SOC (%)"] = (df_soc["soc_bat"] / bat_cap_kwh * 100).clip(0, 100).round(2)
                        time_col = next((c for c in df_soc.columns
                                        if c.lower() in ("time", "timestamp", "datetime")), None)
                        keep = ([time_col] if time_col else []) + ["soc_bat", "SOC (%)"]
                        df_soc_exp = df_soc[[c for c in keep if c in df_soc.columns]].copy()
                        if time_col:
                            df_soc_exp = df_soc_exp.rename(columns={time_col: "Timestamp"})
                        df_soc_exp = df_soc_exp.rename(columns={"soc_bat": "SOC (kWh)"})
                        ws_soc = wb.create_sheet("Battery - SOC")
                        _write_df(ws_soc, df_soc_exp,
                                  f"State of Charge -- {bat_label} ({bat_cap_kwh:.0f} kWh)")

        if "Sheet" in wb.sheetnames:
            del wb["Sheet"]

    return buf.getvalue()


def crear_zip(payload: dict, run_tag: str) -> bytes:
    df_models = pd.DataFrame(payload.get("models", []))
    meta      = payload.get("meta", {})
    series    = payload.get("series", {}) or {}

    _ZIP_COL_RENAME = {
        "Modelo": "Model", "Coste (€)": "Cost (EUR)",
        "% Autoconsumo": "Self-cons. (%)", "% Excedente": "Surplus (%)",
        "% Importación": "Import (%)", "% Importacion": "Import (%)",
        "Autoconsumo (kWh)": "Self-cons. (kWh)", "Excedente (kWh)": "Surplus (kWh)",
        "Importación (kWh)": "Import (kWh)", "Importacion (kWh)": "Import (kWh)",
    }
    ts_frames = []
    for label, s in series.items():
        rows = (s or {}).get("rows") or []
        if rows:
            df_s = pd.DataFrame(rows)
            df_s.insert(0, "Model", label)
            ts_frames.append(df_s)
    df_ts_all = pd.concat(ts_frames, ignore_index=True) if ts_frames else pd.DataFrame()

    df_models_clean = df_models.drop(
        columns=[c for c in df_models.columns if c.startswith("cost_per_user") or c == "users_display"],
        errors="ignore",
    ).rename(columns=_ZIP_COL_RENAME)

    report_html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>CEC Export -- {run_tag}</title>
<style>
body{{font-family:"Segoe UI",Arial,sans-serif;max-width:1100px;margin:auto;padding:32px;
     background:#F0F3F8;color:#111827}}
h1{{color:#014593;font-size:1.5rem}}
h2{{color:#53565A;font-size:1.1rem;margin-top:2rem}}
table{{border-collapse:collapse;width:100%;background:#fff;border-radius:10px;
       overflow:hidden;box-shadow:0 1px 8px rgba(0,0,0,0.07)}}
th,td{{border:1px solid #DDE3ED;padding:9px 12px;text-align:right}}
th{{background:#014593;color:#fff;text-align:left;font-size:.8rem;
    text-transform:uppercase;letter-spacing:.4px}}
tr:nth-child(even) td{{background:#F6F8FB}}
pre{{background:#fff;border:1px solid #DDE3ED;border-radius:8px;
     padding:14px;font-size:.8rem;color:#53565A}}
</style></head>
<body>
<h1>CEC Optimizer -- Results</h1>
<p style="color:#6B7280;font-size:.9rem">Run: <strong>{run_tag}</strong></p>
<h2>Metadata</h2>
<pre>{json.dumps(meta, indent=2)}</pre>
<h2>Model Comparison</h2>
{df_models_clean.to_html(index=False, border=0)}
</body></html>""".encode("utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("models.csv",     df_models_clean.to_csv(index=False))
        z.writestr("timeseries.csv", df_ts_all.to_csv(index=False) if not df_ts_all.empty else "")
        z.writestr("report.html",    report_html)
        z.writestr("meta.json",      json.dumps(meta, indent=2).encode())
    return buf.getvalue()



def grafico_coste_usuarios(models: list[dict]) -> go.Figure:
    if not models:
        return grafico_vacio("Sin datos de usuarios.")

    all_users: list[str] = []
    for m in models:
        for u in (m.get("users_display") or []):
            if u not in all_users:
                all_users.append(u)

    if not all_users:
        return grafico_vacio("Sin datos de usuarios disponibles.")

    fig = go.Figure()
    colors = COLORWAY

    for i, m in enumerate(models):
        per_user = m.get("cost_per_user") or {}
        y_vals   = [a_float(per_user.get(u, 0.0)) for u in all_users]
        fig.add_trace(go.Bar(
            name=m["Modelo"],
            x=all_users,
            y=y_vals,
            marker_color=colors[i % len(colors)],
        ))

    estilo_grafico(fig, y_title="Coste (€)", barmode="group")
    return fig




def register_callbacks(app, cfg):

    @app.callback(
        Output("nav-store", "data"),
        [Input(f"nav-{pid}", "n_clicks") for pid in PAGE_IDS] +
        [Input("results-store", "data")],
        State("nav-store", "data"),
        prevent_initial_call=True,
    )
    def navigate(*args):
        state   = args[-1]
        trig    = ctx.triggered_id

        if trig == "results-store":
            results_data = args[len(PAGE_IDS)]
            if results_data and results_data.get("models"):
                return "comparativa"
            return state or "config"

        for pid in PAGE_IDS:
            if trig == f"nav-{pid}":
                return pid

        return state or "config"

    page_style_outputs = [Output(f"page-{pid}", "style") for pid in PAGE_IDS]
    nav_class_outputs  = [Output(f"nav-{pid}", "className") for pid in PAGE_IDS]

    PAGE_SUBTITLES = {
        "config":      "Optimización MILP de asignación de energía FV",
        "comparativa": "Optimización MILP de asignación de energía FV",
        "usuarios":    "Optimización MILP de asignación de energía FV",
        "energia":     "Optimización MILP de asignación de energía FV",
        "escenarios":  "Análisis de la viabilidad energética de la batería",
        "export":      "Optimización MILP de asignación de energía FV",
    }

    @app.callback(
        page_style_outputs + nav_class_outputs +
        [
            Output("topbar-title",    "children"),
            Output("topbar-subtitle", "children"),
            Output("status-dot",      "className"),
            Output("status-label",    "children"),
        ],
        Input("nav-store", "data"),
        Input("results-store", "data"),
    )
    def show_page(current_page, results_data):
        current_page = current_page or "config"

        has_results = bool(results_data and results_data.get("models"))

        page_styles = []
        for pid in PAGE_IDS:
            page_styles.append(
                {"display": "block"} if pid == current_page else {"display": "none"}
            )

        nav_classes = []
        for pid in PAGE_IDS:
            base = "nav-item-btn"
            nav_classes.append(f"{base} active" if pid == current_page else base)

        title    = PAGE_TITLES.get(current_page, "CEC Optimizer")
        subtitle = PAGE_SUBTITLES.get(current_page, "Optimización MILP de asignación de energía FV")

        if has_results:
            dot_cls = "status-dot ready"
            status  = "Resultados disponibles"
        else:
            dot_cls = "status-dot"
            status  = "Sin resultados"

        return page_styles + nav_classes + [title, subtitle, dot_cls, status]

    @app.callback(
        Output("adv-collapse", "is_open"),
        Input("adv-toggle", "n_clicks"),
        State("adv-collapse", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_adv(n, is_open):
        return (not is_open) if n else is_open

    @app.callback(
        Output("tariff-mixed-manual-wrap", "is_open"),
        Output("tariff-fixed-manual-wrap", "is_open"),
        Input("tariff-type", "value"),
    )
    def toggle_tariff_panels(tariff_type):
        return tariff_type == "mixed", tariff_type == "fixed"

    @app.callback(
        Output("mixed-buy-wrap",  "is_open"),
        Output("mixed-sell-wrap", "is_open"),
        Input("tariff-type",          "value"),
        Input("indexed-manual-which", "value"),
    )
    def toggle_mixed_manual_inputs(tariff_type, which):
        if tariff_type != "mixed":
            return True, False
        return which != "sell", which == "sell"

    @app.callback(
        Output("buy-upload-wrap",  "is_open"),
        Output("sell-upload-wrap", "is_open"),
        Input("tariff-type",          "value"),
        Input("indexed-manual-which", "value"),
    )
    def toggle_price_uploads(tariff_type, which):
        if tariff_type == "indexed":
            return True, True
        if tariff_type == "mixed":
            return which != "buy", which != "sell"
        return False, False

    @app.callback(
        Output("upload-cons-name", "children"),
        Output("upload-pv-name",   "children"),
        Output("upload-buy-name",  "children"),
        Output("upload-sell-name", "children"),
        Input("upload-cons", "filename"),
        Input("upload-pv",   "filename"),
        Input("upload-buy",  "filename"),
        Input("upload-sell", "filename"),
    )
    def show_filenames(f1, f2, f3, f4):
        def s(x):
            if not x:
                return ""
            return html.Div(
                [html.I(className="bi bi-check-circle-fill me-1",
                        style={"color": "var(--success)"}), x],
                style={"display": "flex", "alignItems": "center",
                       "gap": "4px", "fontSize": "12px", "color": "var(--success)"},
            )
        return s(f1), s(f2), s(f3), s(f4)

    @app.callback(
        Output("results-store",  "data"),
        Output("run-tag-store",  "data"),
        Output("run-status",     "children"),
        Input("run-btn",         "n_clicks"),
        Input("sample-data-btn", "n_clicks"),
        State("tariff-type",          "value"),
        State("indexed-manual-which", "value"),
        State("indexed-buy-manual",   "value"),
        State("indexed-sell-manual",  "value"),
        State("fixed-buy",            "value"),
        State("fixed-sell",           "value"),
        State("upload-cons",    "contents"),
        State("upload-pv",      "contents"),
        State("upload-buy",     "contents"),
        State("upload-sell",    "contents"),
        State("solver-name",         "value"),
        State("exante-mode",         "value"),
        State("dynamic-modes-list",  "value"),
        State("battery-enabled",     "value"),
        State("bat-capacity",        "value"),
        State("bat-power",           "value"),
        State("bat-eta-c",           "value"),
        State("bat-eta-d",           "value"),
        State("bat-fin-cost-kwp",    "value"),
        State("bat-lifecycle-cycles","value"),
        prevent_initial_call=True,
    )
    def run(
        _run, _sample,
        tariff_type, mixed_manual_which,
        indexed_buy_manual, indexed_sell_manual,
        fixed_buy, fixed_sell,
        cons, pv, buy, sell,
        solver_name, exante_mode_list, dynamic_modes_list,
        battery_enabled, bat_capacity, bat_power, bat_eta_c, bat_eta_d,
        bat_capex_kwh, bat_lifecycle_cycles,
    ):
        triggered = ctx.triggered_id
        use_sample = (triggered == "sample-data-btn")

        def _err(msg):
            return {}, "", dbc.Alert(
                [html.I(className="bi bi-exclamation-triangle-fill me-2"), msg],
                color="danger", className="alert-enterprise", dismissable=True,
            )

        if not use_sample:
            if not (cons and pv):
                return _err("Faltan los archivos de Consumos y/o Fotovoltaica.")

            if tariff_type == "indexed":
                manual_buy_enabled  = False
                manual_sell_enabled = False
                p_buy_manual        = indexed_buy_manual
                p_sell_manual       = indexed_sell_manual
                tariff_mode         = "indexed"
                if not buy:  return _err("Falta CSV de precio de compra (tarifa indexada).")
                if not sell: return _err("Falta CSV de precio de venta (tarifa indexada).")

            elif tariff_type == "mixed":
                which = mixed_manual_which or "buy"
                manual_buy_enabled  = which == "buy"
                manual_sell_enabled = which == "sell"
                p_buy_manual        = indexed_buy_manual
                p_sell_manual       = indexed_sell_manual
                tariff_mode         = "indexed"
                if not manual_buy_enabled and not buy:   return _err("Falta CSV de precio de compra.")
                if not manual_sell_enabled and not sell: return _err("Falta CSV de precio de venta.")

            else:
                manual_buy_enabled  = True
                manual_sell_enabled = True
                p_buy_manual        = fixed_buy
                p_sell_manual       = fixed_sell
                tariff_mode         = "fixed"
        else:
            manual_buy_enabled  = False
            manual_sell_enabled = False
            p_buy_manual        = 0.20
            p_sell_manual       = 0.08
            tariff_mode         = "indexed"

        exante_mode_list   = list(dict.fromkeys(["rd"] + list(exante_mode_list or [])))
        dynamic_modes_list = list(dict.fromkeys(dynamic_modes_list or []))

        upload_contents = {"cons": cons, "pv": pv, "buy": buy, "sell": sell}
        mode            = "default" if use_sample else "csv"

        overrides_base = {
            "solver_name":          solver_name,
            "tariff_mode":          tariff_mode,
            "manual_buy_enabled":   manual_buy_enabled,
            "manual_sell_enabled":  manual_sell_enabled,
            "p_buy_manual":         p_buy_manual,
            "p_sell_manual":        p_sell_manual,
        }

        exante_defs = []
        if "rd"    in exante_mode_list: exante_defs.append((4, "Ex ante RD 244/2019"))
        if "rigid" in exante_mode_list: exante_defs.append((0, "Ex ante Rígido"))

        dyn_label = {
            "hour":  "Dinámico Horario",
            "day":   "Dinámico Diario",
            "week":  "Dinámico Semanal",
            "month": "Dinámico Mensual",
        }

        models        = []
        series        = {}
        last_run_tag  = ""
        last_summary  = {}
        last_ts       = pd.DataFrame()
        first_dm      = dynamic_modes_list[0] if dynamic_modes_list else "hour"
        session_id    = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")[:23]
        run_cache     = {}
        base_cache_store = {}

        def _cached_run(u, dm, label_for_err, bat_ov=None):
            key = (u, dm, bool(bat_ov))
            if key in run_cache:
                return run_cache[key], None
            ov = dict(overrides_base, exante_updates_per_year=u, dynamic_block_mode=dm)
            if bat_ov:
                ov.update(bat_ov)
            bc = base_cache_store.get((u, dm)) if bat_ov else None
            try:
                results, run_tag, _, out_base_cache = run_pipeline(
                    cfg, mode=mode, upload_contents=upload_contents, manual={}, overrides=ov,
                    run_id=session_id, base_cache=bc,
                )
            except Exception as e:
                return None, _err(f"Error en {label_for_err}: {e}")
            s, t = extraer_resultados(results)
            run_cache[key] = (s, t, run_tag)
            if not bat_ov:
                base_cache_store[(u, dm)] = out_base_cache
            return run_cache[key], None

        for u, ex_label in exante_defs:
            result, err = _cached_run(u, first_dm, ex_label, bat_ov=None)
            if err:
                return err
            summary, ts, run_tag = result

            last_run_tag = run_tag
            last_summary, last_ts = summary, ts

            cost, self_kwh, self_pct, exp_kwh, exp_pct, imp_kwh, imp_pct = calcular_porcentajes(summary, "ex_ante")
            per_user_cost = coste_por_usuario(summary, "ex_ante")
            users_display = list(per_user_cost.keys())

            models.append({
                "Modelo":             ex_label,
                "Tipo":               "ex_ante",
                "Coste (€)":          cost,
                "% Autoconsumo":      self_pct,
                "% Excedente":        exp_pct,
                "% Importación":      imp_pct,
                "Autoconsumo (kWh)":  self_kwh,
                "Excedente (kWh)":    exp_kwh,
                "Importación (kWh)":  imp_kwh,
                "cost_per_user":      per_user_cost,
                "users_display":      users_display,
            })

            if isinstance(ts, pd.DataFrame) and not ts.empty:
                series[ex_label] = {"columns": list(ts.columns), "rows": ts.to_dict("records")}

        u_for_dyn = 4 if "rd" in exante_mode_list else 0

        for dm in dynamic_modes_list:
            result, err = _cached_run(u_for_dyn, dm, dyn_label.get(dm, dm))
            if err:
                return err
            summary, ts, run_tag = result

            last_run_tag = run_tag
            last_summary, last_ts = summary, ts

            cost, self_kwh, self_pct, exp_kwh, exp_pct, imp_kwh, imp_pct = calcular_porcentajes(summary, "prop")
            per_user_cost = coste_por_usuario(summary, "prop")
            users_display = list(per_user_cost.keys())
            label         = dyn_label.get(dm, f"Dinámico {dm}")

            models.append({
                "Modelo":             label,
                "Tipo":               "dinamico",
                "Coste (€)":          cost,
                "% Autoconsumo":      self_pct,
                "% Excedente":        exp_pct,
                "% Importación":      imp_pct,
                "Autoconsumo (kWh)":  self_kwh,
                "Excedente (kWh)":    exp_kwh,
                "Importación (kWh)":  imp_kwh,
                "cost_per_user":      per_user_cost,
                "users_display":      users_display,
            })

            if isinstance(ts, pd.DataFrame) and not ts.empty:
                series[label] = {"columns": list(ts.columns), "rows": ts.to_dict("records")}

        use_battery = bool(battery_enabled and "enabled" in (battery_enabled or []))
        if use_battery:
            bat_dm    = "hour"
            u_bat     = 4 if "rd" in exante_mode_list else 0
            bat_label = "Dinámico con batería"
            bat_ov    = {
                "battery_enabled":            True,
                "battery_capacity_kwh":       float(bat_capacity or 10.0),
                "battery_power_kw":           float(bat_power or 5.0),
                "battery_eta_c":              float((bat_eta_c or 95)) / 100.0,
                "battery_eta_d":              float((bat_eta_d or 95)) / 100.0,
                "battery_soc_init":           cfg.battery.initial_soc_fraction,
                "battery_replacement_cost":   float(bat_capex_kwh or 250) * float(bat_capacity or 10),
                "battery_lifecycle_cycles":   int(bat_lifecycle_cycles or 7000),
            }
            result_bat, err_bat = _cached_run(u_bat, bat_dm, bat_label, bat_ov=bat_ov)
            if err_bat:
                models.append({
                    "Modelo":  bat_label, "Tipo": "bateria",
                    "Coste (€)": None, "% Autoconsumo": None, "% Excedente": None,
                    "% Importación": None, "Autoconsumo (kWh)": None,
                    "Excedente (kWh)": None, "Importación (kWh)": None,
                    "cost_per_user": {}, "users_display": [], "_error": str(err_bat),
                })
            else:
                summary_bat, ts_bat, run_tag_bat = result_bat
                last_run_tag = run_tag_bat
                if summary_bat.get("battery_enabled") and summary_bat.get("cost_bat") is not None:
                    cost_bat   = _sf(summary_bat["cost_bat"])
                    self_bat   = _sf(summary_bat.get("self_bat"))
                    imp_bat    = _sf(summary_bat.get("imp_bat"))
                    exp_bat    = _sf(summary_bat.get("exp_bat"))
                    disch_bat  = _sf(summary_bat.get("discharge_bat_total"))
                    d_tot      = _sf(summary_bat.get("demand_total"), 1.0) or 1.0
                    g_tot      = _sf(summary_bat.get("gen_total"),    1.0) or 1.0
                    self_pct_b = (self_bat + disch_bat) / d_tot * 100 if d_tot > 0 else 0.0
                    imp_pct_b  = imp_bat / d_tot * 100 if d_tot > 0 else 0.0
                    exp_pct_b  = exp_bat / g_tot * 100 if g_tot > 0 else 0.0
                    pu_bat     = coste_por_usuario(summary_bat, "bat") or coste_por_usuario(summary_bat, "prop")
                    bat_efc_val      = summary_bat.get("bat_efc")
                    bat_soh_loss_val = summary_bat.get("bat_soh_loss_pct")
                    models.append({
                        "Modelo":               bat_label,
                        "Tipo":                 "bateria",
                        "Coste (€)":            cost_bat,
                        "% Autoconsumo":        self_pct_b,
                        "% Excedente":          exp_pct_b,
                        "% Importación":        imp_pct_b,
                        "Autoconsumo (kWh)":    self_bat,
                        "Excedente (kWh)":      exp_bat,
                        "Importación (kWh)":    imp_bat,
                        "cost_per_user":        pu_bat,
                        "users_display":        list(pu_bat.keys()),
                        "battery_capacity_kwh": float(bat_capacity or 10.0),
                        "bat_efc":              bat_efc_val,
                        "bat_soh_loss_pct":     bat_soh_loss_val,
                        "bat_lifecycle_cycles": int(bat_lifecycle_cycles or 7000),
                        "bat_capex_kwh":        float(bat_capex_kwh or 250),
                    })
                    if isinstance(ts_bat, pd.DataFrame) and not ts_bat.empty:
                        series[bat_label] = {"columns": list(ts_bat.columns), "rows": ts_bat.to_dict("records")}

        if last_summary:
            label_fx = "Reparto proporcional"
            cost_fx, self_fx, self_pct_fx, exp_fx, exp_pct_fx, imp_fx, imp_pct_fx = calcular_porcentajes(last_summary, "fijo")
            per_user_cost_fx = coste_por_usuario(last_summary, "fijo")
            users_display_fx = list(per_user_cost_fx.keys())
            models.insert(0, {
                "Modelo":             label_fx,
                "Tipo":               "fijo",
                "Coste (€)":          cost_fx,
                "% Autoconsumo":      self_pct_fx,
                "% Excedente":        exp_pct_fx,
                "% Importación":      imp_pct_fx,
                "Autoconsumo (kWh)":  self_fx,
                "Excedente (kWh)":    exp_fx,
                "Importación (kWh)":  imp_fx,
                "cost_per_user":      per_user_cost_fx,
                "users_display":      users_display_fx,
            })
            if isinstance(last_ts, pd.DataFrame) and not last_ts.empty:
                series[label_fx] = {"columns": list(last_ts.columns), "rows": last_ts.to_dict("records")}

        payload = {
            "models": models,
            "series": series,
            "meta":   {
                "tariff_mode":   tariff_mode,
                "exante_mode":   exante_mode_list,
                "dynamic_modes": dynamic_modes_list,
                "solver":        solver_name,
                "use_sample":    use_sample,
            },
        }

        return payload, last_run_tag, ""

    @app.callback(
        Output("kpi-best-model",         "children"),
        Output("kpi-best-cost",          "children"),
        Output("kpi-saving-pct",         "children"),
        Output("kpi-co2-avoided",        "children"),
        Output("ranking-display",        "children"),
        Output("user-cost-cards",        "children"),
        Output("alpha-model-selector",   "options"),
        Output("alpha-model-selector",   "value"),
        Output("comparativa-empty",      "style"),
        Output("energy-balance-display", "children"),
        Output("chart-cumulative-pct",   "data"),
        Output("chart-cumulative-eur",   "data"),
        Output("user-equidad-display",   "children"),
        Input("results-store", "data"),
    )
    def render(data):
        if not data or "models" not in data or not data["models"]:
            return (
                "", "", "", "",
                None, None,
                [], None,
                {"display": "flex"},
                None, [], [],
                None,
            )

        df = pd.DataFrame(data["models"]).copy()
        for c in ["Coste (€)", "% Autoconsumo", "% Excedente", "% Importación"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        best       = df.loc[df["Coste (€)"].idxmin()]
        best_model = str(best["Modelo"])

        ref_label = None
        modelos   = df["Modelo"].astype(str).tolist()
        if "Ex ante RD 244/2019" in modelos:
            ref_label = "Ex ante RD 244/2019"
        elif "Ex ante Rígido" in modelos:
            ref_label = "Ex ante Rígido"

        ref_cost = ref_imp_pct = None
        if ref_label:
            ref_row     = df.loc[df["Modelo"].astype(str) == ref_label].iloc[0]
            ref_cost    = float(ref_row["Coste (€)"]) if pd.notna(ref_row["Coste (€)"]) else None
            ref_imp_pct = float(ref_row["% Importación"]) if pd.notna(ref_row["% Importación"]) else None

        best_cost_val = float(best["Coste (€)"]) if pd.notna(best["Coste (€)"]) else None
        saving_pct_val = None
        if ref_cost and best_cost_val and abs(ref_cost) > 1e-12:
            saving_pct_val = (ref_cost - best_cost_val) / ref_cost * 100.0
        saving_eur_val = (ref_cost - best_cost_val) if ref_cost and best_cost_val else None

        kpi_best_cost  = formato_eur(best_cost_val)
        kpi_saving_pct = formato_pct(saving_pct_val) if saving_pct_val is not None else "—"

        best_imp_pct_val = a_float(best.get("% Importación", 0))
        if ref_imp_pct is not None:
            imp_avoided_pp = ref_imp_pct - best_imp_pct_val
            if abs(imp_avoided_pp) < 0.05:
                kpi_co2 = "—"
            else:
                kpi_co2 = f"{formato_num(imp_avoided_pp, 2)}%"
        else:
            kpi_co2 = f"{formato_num(best_imp_pct_val, 2)}%"

        model_font = "18px" if len(best_model) > 14 else "22px" if len(best_model) > 10 else "26px"
        kpi_model_el = html.Span(best_model, style={"fontSize": model_font})

        series  = data.get("series", {}) or {}
        ts_best = get_serie(series, best_model)
        ts_ref  = get_serie(series, ref_label) if ref_label else pd.DataFrame()

        def _step_cost_ts(ts: pd.DataFrame, kind: str):
            if ts.empty: return None, None
            tcol = col_tiempo(ts)
            if not tcol: return None, None
            x = ts.copy()
            x[tcol] = pd.to_datetime(x[tcol], errors="coerce")
            x = x.dropna(subset=[tcol]).sort_values(tcol)
            if kind == "ex_ante":
                c_step = primera_col(x.columns, ["cost_ex_ante", "cost_step_ex_ante"])
                c_cum  = primera_col(x.columns, ["cost_ex_ante_cum"])
            elif kind == "fijo":
                c_step = primera_col(x.columns, ["cost_fixed"])
                c_cum  = primera_col(x.columns, ["cost_fixed_cum"])
            else:
                c_step = primera_col(x.columns, ["cost_prop", "cost_step_prop"])
                c_cum  = primera_col(x.columns, ["cost_prop_cum"])
            out = x[[tcol]].copy()
            if c_step:
                out["cost_step"] = pd.to_numeric(x[c_step], errors="coerce")
            elif c_cum:
                cum = pd.to_numeric(x[c_cum], errors="coerce")
                out["cost_step"] = cum.diff()
                if len(out) > 0:
                    out.loc[out.index[0], "cost_step"] = cum.iloc[0]
            else:
                return None, None
            return out.dropna(subset=["cost_step"]), tcol

        best_kind = ("ex_ante" if "ex ante" in best_model.lower()
                     else "fijo" if str(best.get("Tipo", "")) == "fijo"
                     else "prop")
        ref_cost_ts,  ref_tcol  = _step_cost_ts(ts_ref,  "ex_ante") if ref_label else (None, None)
        best_cost_ts, best_tcol = _step_cost_ts(ts_best, best_kind)

        best_row = df.loc[df["Modelo"].astype(str) == best_model].iloc[0]

        data_cumulative_pct = []
        data_cumulative_eur = []
        if ref_cost_ts is not None and best_cost_ts is not None:
            rct = ref_cost_ts.rename(columns={ref_tcol: "Time", "cost_step": "cost_ref"})
            bct = best_cost_ts.rename(columns={best_tcol: "Time", "cost_step": "cost_best"})
            m_merged = pd.merge(rct, bct, on="Time", how="inner").sort_values("Time")
            m_merged["cum_ref"]  = m_merged["cost_ref"].cumsum()
            m_merged["cum_best"] = m_merged["cost_best"].cumsum()
            m_merged["sav_eur"]  = m_merged["cum_ref"] - m_merged["cum_best"]
            m_merged["sav_pct"]  = 0.0
            ok = m_merged["cum_ref"].abs() > 1e-12
            m_merged.loc[ok, "sav_pct"] = (
                (m_merged.loc[ok, "cum_ref"] - m_merged.loc[ok, "cum_best"])
                / m_merged.loc[ok, "cum_ref"] * 100.0
            )
            m_wk = (m_merged.set_index("Time")[["sav_pct", "sav_eur"]]
                             .resample("7D").last()
                             .reset_index()
                             .dropna())
            data_cumulative_pct = [
                {"date": r.Time.strftime("%d %b"), "Ahorro (%)": round(float(r.sav_pct), 2)}
                for r in m_wk.itertuples()
            ]
            data_cumulative_eur = [
                {"date": r.Time.strftime("%d %b"), "Ahorro (€)": round(float(r.sav_eur), 2)}
                for r in m_wk.itertuples()
            ]

        self_pct = a_float(best_row.get("% Autoconsumo", 0))
        imp_pct  = max(0.0, 100.0 - self_pct)
        exp_pct  = a_float(best_row.get("% Excedente",    0))

        eb_rows = []
        for eb_label, eb_pct, eb_color, eb_icon in [
            ("Autoconsumo FV",   self_pct, "#18BC9C", "bi-sun-fill"),
            ("Importación red",  imp_pct,  "#E74C3C", "bi-plug-fill"),
            ("Excedente FV",     exp_pct,  "#F39C12", "bi-arrow-up-right-circle-fill"),
        ]:
            eb_rows.append(html.Div([
                html.Div([
                    html.I(className=f"bi {eb_icon}",
                           style={"color": eb_color, "fontSize": "13px", "marginRight": "6px"}),
                    html.Span(eb_label, style={"fontSize": "12px", "fontWeight": "600",
                                               "color": "var(--text)", "flexGrow": "1"}),
                    html.Span(f"{formato_num(eb_pct, 1)}%", style={"fontSize": "12.5px", "fontWeight": "800",
                                                        "color": eb_color}),
                ], style={"display": "flex", "alignItems": "center", "marginBottom": "4px"}),
                html.Div(
                    html.Div(style={"width": f"{min(eb_pct, 100):.1f}%", "height": "7px",
                                    "background": eb_color, "borderRadius": "4px"}),
                    style={"background": "var(--bg)", "borderRadius": "4px",
                           "overflow": "hidden", "marginBottom": "10px"},
                ),
            ]))

        energy_balance_display = html.Div([
            html.Div([
                html.Span(f"{round(self_pct)}",
                          style={"fontSize": "54px", "fontWeight": "900", "lineHeight": "1",
                                 "color": "#18BC9C", "letterSpacing": "-2px"}),
                html.Span("%", style={"fontSize": "22px", "color": "#18BC9C", "fontWeight": "700",
                                      "verticalAlign": "top", "marginTop": "10px",
                                      "display": "inline-block"}),
            ]),
            html.Div("Tasa de autoconsumo FV",
                     style={"fontSize": "10.5px", "fontWeight": "700",
                            "color": "var(--text-muted)", "textTransform": "uppercase",
                            "letterSpacing": "0.5px", "marginBottom": "16px"}),
            html.Div(eb_rows),
        ])

        df_rank    = df.sort_values("Coste (€)", ascending=True).reset_index(drop=True)
        max_cost_r = float(df_rank["Coste (€)"].max()) if not df_rank.empty else 1.0

        def _mini_bar(label, pct, color):
            pct_safe = pct if math.isfinite(pct) else 0.0
            pct_txt  = f"{formato_num(pct_safe, 1)}%" if math.isfinite(pct) else "—"
            return html.Div([
                html.Div([
                    html.Span(label, style={
                        "fontSize": "10px", "color": "var(--text-muted)",
                        "fontWeight": "600", "flex": "1",
                    }),
                    html.Span(pct_txt, style={
                        "fontSize": "10px", "fontWeight": "700", "color": color,
                    }),
                ], style={"display": "flex", "alignItems": "center", "marginBottom": "2px"}),
                html.Div(
                    html.Div(style={"width": f"{min(pct_safe, 100):.1f}%", "height": "4px",
                                    "background": color, "borderRadius": "2px"}),
                    style={"background": "var(--bg)", "borderRadius": "2px",
                           "overflow": "hidden", "marginBottom": "5px"},
                ),
            ])

        _RANK_BAR_COLORS = ["#18BC9C", "#2E6DB4", "#5B8DB8", "#8AAFC8", "#A8C3D4"]

        rank_items = []
        n_rank = len(df_rank)
        for idx, row in df_rank.iterrows():
            mn          = str(row["Modelo"])
            cost_v      = float(row["Coste (€)"]) if pd.notna(row.get("Coste (€)")) else 0.0
            tipo        = row.get("Tipo", "ex_ante")
            bar_pct     = (cost_v / max_cost_r * 100) if max_cost_r > 0 else 0.0
            bar_col     = _RANK_BAR_COLORS[min(idx, len(_RANK_BAR_COLORS) - 1)]
            self_pct_r  = _sf(row.get("% Autoconsumo", 0))
            imp_pct_r   = _sf(row.get("% Importación", 0))

            if ref_cost and cost_v and mn != ref_label:
                sav     = ref_cost - cost_v
                sav_txt = f"{sav:+,.0f} €"
                sav_col = "#27AE60" if sav > 0 else "#E74C3C"
            elif mn == ref_label:
                sav_txt, sav_col = "Referencia", "#6B7280"
            else:
                sav_txt, sav_col = "", "#6B7280"

            rank_items.append(html.Div([
                html.Div([
                    html.Span(f"#{idx + 1}",
                              style={"fontSize": "12px", "fontWeight": "800",
                                     "color": "var(--text-muted)", "minWidth": "28px",
                                     "flexShrink": "0"}),
                    html.Span(mn, style={"marginLeft": "8px", "fontWeight": "700",
                                          "fontSize": "13px", "flexGrow": "1",
                                          "color": "var(--text)"}),
                    html.Span(f"{formato_num(cost_v, 0)} €",
                              style={"fontWeight": "900", "fontSize": "14px",
                                     "marginLeft": "auto", "color": "var(--text)"}),
                    html.Span(sav_txt,
                              style={"fontSize": "12px", "color": sav_col, "fontWeight": "700",
                                     "minWidth": "78px", "textAlign": "right",
                                     "marginLeft": "10px"}),
                ], style={"display": "flex", "alignItems": "center", "marginBottom": "6px"}),
                html.Div(
                    html.Div(style={"width": f"{bar_pct:.1f}%", "height": "6px",
                                    "background": bar_col, "borderRadius": "3px"}),
                    style={"background": "var(--bg)", "borderRadius": "3px",
                           "overflow": "hidden", "marginBottom": "8px"},
                ),
                _mini_bar("Autoconsumo FV", self_pct_r, "#FFB81C"),
                _mini_bar("Importación red", imp_pct_r, "#E74C3C"),
            ], style={
                "padding": "10px 0",
                "borderBottom": ("1px solid var(--border)" if idx < n_rank - 1 else "none"),
                "background": "rgba(24,188,156,0.04)" if mn == best_model else "transparent",
                "paddingLeft": "6px" if mn == best_model else "0",
                "borderLeft": ("3px solid #18BC9C" if mn == best_model else "3px solid transparent"),
            }))

        ranking_display = html.Div([
            *rank_items,
            html.Hr(style={"margin": "14px 0 10px", "borderColor": "var(--border)"}),
            html.Div([
                html.I(className="bi bi-info-circle me-2",
                       style={"color": "var(--text-muted)", "fontSize": "12px"}),
                html.Span(
                    "Los modelos comparados requieren distintos niveles de inversión inicial, "
                    "por lo que los resultados en coste no son estrictamente comparables en igualdad de condiciones.",
                    style={"fontStyle": "italic"},
                ),
            ], style={"fontSize": "11px", "color": "var(--text-muted)", "lineHeight": "1.5"}),
        ])

        alpha_options = [{"label": m["Modelo"], "value": m["Modelo"]} for m in data["models"]]
        alpha_default = alpha_options[0]["value"] if alpha_options else None

        all_users: list[str] = []
        for m in data["models"]:
            for u in (m.get("users_display") or []):
                if u not in all_users:
                    all_users.append(u)

        ref_mrow  = next((m for m in data["models"] if m["Modelo"] == ref_label), None) if ref_label else None
        best_mrow = next((m for m in data["models"] if m["Modelo"] == best_model), None)

        if all_users and best_mrow:
            ucols = []
            for ui, u in enumerate(all_users):
                user_color = _USER_PALETTE[ui % len(_USER_PALETTE)]
                ref_u     = a_float((ref_mrow.get("cost_per_user") or {}).get(u, 0)) if ref_mrow else 0
                best_u    = a_float((best_mrow.get("cost_per_user") or {}).get(u, 0))
                sav_u     = ref_u - best_u if ref_mrow else 0
                sav_pct_u = (sav_u / ref_u * 100) if ref_u > 1e-9 else 0
                sav_col_u = "#27AE60" if sav_u >= 0 else "#E74C3C"
                initial   = u[0].upper() if u else "U"

                cost_lines = []
                if ref_mrow:
                    cost_lines.append(
                        html.Div([
                            html.Span(ref_label,
                                      style={"fontSize": "11px", "color": "var(--text-muted)",
                                             "fontWeight": "600", "flex": "1"}),
                            html.Span(f"{formato_num(ref_u, 0)} €",
                                      style={"fontSize": "11px", "fontWeight": "700",
                                             "color": "var(--text)"}),
                        ], style={"display": "flex", "justifyContent": "space-between",
                                  "marginBottom": "4px"}),
                    )
                cost_lines.append(
                    html.Div([
                        html.Span(best_model,
                                  style={"fontSize": "11px", "color": "#0e7a62",
                                         "fontWeight": "600", "flex": "1"}),
                        html.Span(f"{formato_num(best_u, 0)} €",
                                  style={"fontSize": "11px", "fontWeight": "700",
                                         "color": "#0e7a62"}),
                    ], style={"display": "flex", "justifyContent": "space-between"}),
                )

                card_body = [
                    html.Div([
                        html.Div(initial, style={
                            "width": "36px", "height": "36px", "borderRadius": "50%",
                            "background": user_color, "color": "#fff",
                            "display": "flex", "alignItems": "center",
                            "justifyContent": "center", "fontWeight": "800",
                            "fontSize": "15px", "flexShrink": "0",
                        }),
                        html.Div(u, style={"fontWeight": "700", "fontSize": "13px",
                                           "marginLeft": "10px", "color": "var(--text)"}),
                    ], style={"display": "flex", "alignItems": "center",
                              "marginBottom": "12px"}),
                    html.Div([
                        html.Span(f"{formato_num(sav_pct_u, 1)}%",
                                  style={"fontSize": "26px", "fontWeight": "900",
                                         "color": sav_col_u, "lineHeight": "1"}),
                        html.Span(f" ({'+'if sav_u >= 0 else ''}{formato_num(sav_u, 0)} €)",
                                  style={"fontSize": "12px", "color": sav_col_u,
                                         "fontWeight": "600"}),
                        html.Div("ahorro vs referencia",
                                 style={"fontSize": "10px", "color": "var(--text-muted)",
                                        "fontWeight": "700", "textTransform": "uppercase",
                                        "letterSpacing": "0.4px", "marginTop": "2px"}),
                    ], style={"marginBottom": "14px"}) if ref_mrow else None,
                    html.Div(cost_lines,
                             style={"borderTop": "1px solid var(--border)",
                                    "paddingTop": "10px"}),
                ]

                ucols.append(dbc.Col(
                    dbc.Card(
                        dbc.CardBody([c for c in card_body if c is not None]),
                        className="e-card h-100",
                        style={"borderTop": f"3px solid {user_color}"},
                    ),
                    xs=12, sm=6, md=3,
                ))
            user_cost_cards = dbc.Row(ucols, className="g-3")
        else:
            user_cost_cards = html.Div("Sin datos de usuarios.", className="text-muted small mt-2")

        equidad_display = html.Div()

        if all_users and ref_mrow and best_mrow:
            raw_rates = []
            for u in all_users:
                ref_u  = a_float((ref_mrow.get("cost_per_user") or {}).get(u, 0))
                best_u = a_float((best_mrow.get("cost_per_user") or {}).get(u, 0))
                raw_rates.append((ref_u - best_u) / ref_u if abs(ref_u) > 1e-9 else 0.0)

            total_ref  = sum(a_float((ref_mrow.get("cost_per_user") or {}).get(u, 0)) for u in all_users)
            total_best = sum(a_float((best_mrow.get("cost_per_user") or {}).get(u, 0)) for u in all_users)
            total_saving_pct = (total_ref - total_best) / total_ref * 100 if abs(total_ref) > 1e-9 else 0.0

            _MIN_SAVING_PCT = 0.5

            if total_saving_pct < _MIN_SAVING_PCT:
                eq_color = "#6B7280"
                equidad_display = dbc.Card(
                    dbc.CardBody([
                        html.Div([
                            html.Div(
                                html.I(className="bi bi-bar-chart-steps",
                                       style={"fontSize": "16px", "color": eq_color}),
                                style={"width": "36px", "height": "36px", "borderRadius": "8px",
                                       "background": "color-mix(in srgb, #6B7280 12%, white)",
                                       "display": "flex", "alignItems": "center",
                                       "justifyContent": "center", "flexShrink": "0"},
                            ),
                            html.Div([
                                html.Div("Índice de equidad de reparto", style={
                                    "fontSize": "10px", "fontWeight": "700",
                                    "color": "var(--text-muted)", "textTransform": "uppercase",
                                    "letterSpacing": "0.5px", "marginBottom": "2px",
                                }),
                                html.Div("Ahorro insuficiente para evaluar equidad", style={
                                    "fontSize": "13px", "color": eq_color, "fontWeight": "700",
                                }),
                            ], style={"marginLeft": "12px"}),
                        ], style={"display": "flex", "alignItems": "center",
                                  "marginBottom": "8px"}),
                        html.Div(
                            f"El ahorro total del mejor modelo es inferior al {_MIN_SAVING_PCT:.0f} % "
                            "respecto al ex ante. Con ahorros tan pequeños el índice de Jain no es representativo.",
                            style={"fontSize": "11.5px", "color": "var(--text-muted)",
                                   "lineHeight": "1.6"},
                        ),
                    ]),
                    className="chart-card",
                    style={"borderLeft": f"4px solid {eq_color}"},
                )
            else:
                rates = [max(0.0, r) for r in raw_rates]

                n = len(rates)
                sum_r  = sum(rates)
                sum_r2 = sum(r * r for r in rates)
                if sum_r2 > 1e-12:
                    jain = (sum_r ** 2) / (n * sum_r2)
                    equidad_pct = max(0.0, min(100.0, jain * 100.0))
                else:
                    equidad_pct = 100.0

                eq_color = "#27AE60" if equidad_pct >= 70 else ("#F39C12" if equidad_pct >= 40 else "#E74C3C")
                eq_label = ("Distribución equitativa" if equidad_pct >= 70
                            else ("Distribución moderada" if equidad_pct >= 40
                                  else "Distribución desigual"))

                equidad_display = dbc.Card(
                    dbc.CardBody([
                        html.Div([
                            html.Div(
                                html.I(className="bi bi-bar-chart-steps",
                                       style={"fontSize": "16px", "color": eq_color}),
                                style={"width": "36px", "height": "36px", "borderRadius": "8px",
                                       "background": f"color-mix(in srgb, {eq_color} 12%, white)",
                                       "display": "flex", "alignItems": "center",
                                       "justifyContent": "center", "flexShrink": "0"},
                            ),
                            html.Div([
                                html.Div("Índice de equidad de reparto", style={
                                    "fontSize": "10px", "fontWeight": "700",
                                    "color": "var(--text-muted)", "textTransform": "uppercase",
                                    "letterSpacing": "0.5px", "marginBottom": "2px",
                                }),
                                html.Div([
                                    html.Span(f"{formato_num(equidad_pct, 0)}%", style={
                                        "fontSize": "26px", "fontWeight": "900",
                                        "color": eq_color, "lineHeight": "1", "marginRight": "8px",
                                    }),
                                    html.Span(eq_label, style={
                                        "fontSize": "13px", "color": eq_color, "fontWeight": "700",
                                    }),
                                ], style={"display": "flex", "alignItems": "baseline"}),
                            ], style={"marginLeft": "12px"}),
                        ], style={"display": "flex", "alignItems": "center",
                                  "marginBottom": "8px"}),
                        html.Div(
                            "Un valor próximo al 100 % indica que el beneficio de la optimización "
                            "se distribuye de forma proporcional a la demanda de cada miembro de la comunidad.",
                            style={"fontSize": "11.5px", "color": "var(--text-muted)",
                                   "lineHeight": "1.6"},
                        ),
                    ]),
                    className="chart-card",
                    style={"borderLeft": f"4px solid {eq_color}"},
                )

        return (
            kpi_model_el, kpi_best_cost, kpi_saving_pct, kpi_co2,
            ranking_display, user_cost_cards,
            alpha_options, alpha_default,
            {"display": "none"},
            energy_balance_display,
            data_cumulative_pct, data_cumulative_eur,
            equidad_display,
        )

    @app.callback(
        Output("fig-alpha-evolution", "figure"),
        Input("alpha-model-selector", "value"),
        Input("results-store", "data"),
    )
    def update_alpha_chart(model_label, data):
        if not model_label or not data or "series" not in data:
            return grafico_vacio("Selecciona un modelo para ver los coeficientes alpha.")

        series = data.get("series", {}) or {}
        ts = get_serie(series, model_label)
        if ts.empty:
            return grafico_vacio("No hay series disponibles para este modelo.")

        tcol = col_tiempo(ts)
        if not tcol:
            return grafico_vacio("No se encontró columna temporal.")

        ts[tcol] = pd.to_datetime(ts[tcol], errors="coerce")
        ts = ts.dropna(subset=[tcol]).sort_values(tcol).reset_index(drop=True)

        model_row = next((m for m in data["models"] if m["Modelo"] == model_label), None)
        tipo      = (model_row or {}).get("Tipo", "ex_ante")
        prefix    = ("alpha_ex_" if tipo == "ex_ante"
                     else "alpha_fx_" if tipo == "fijo"
                     else "alpha_prop_")

        alpha_cols = [c for c in ts.columns if c.startswith(prefix)]
        if not alpha_cols:
            return grafico_vacio("No se encontraron columnas de coeficientes alpha en este modelo.")

        models_list = data.get("models", [])
        users_display = []
        for m in models_list:
            if m.get("Modelo") == model_label:
                users_display = m.get("users_display", [])
                break
        if not users_display:
            users_display = [f"Usuario {i+1}" for i in range(len(alpha_cols))]


        n_u = len(alpha_cols)
        y_labels = [
            users_display[i] if i < len(users_display) else f"U{i+1}"
            for i in range(n_u)
        ]

        ts["_period"] = ts[tcol].dt.to_period("M")
        periods_sorted = sorted(ts["_period"].unique())
        period_labels  = [
            f"{_MESES[p.month-1]} {str(p.year)[2:]}" for p in periods_sorted
        ]
        z_matrix = []
        for col in alpha_cols:
            row_vals = []
            for p in periods_sorted:
                mask = ts["_period"] == p
                val = float(pd.to_numeric(ts.loc[mask, col], errors="coerce")
                            .dropna().iloc[0]) if mask.any() else 0.0
                row_vals.append(val)
            z_matrix.append(row_vals)

        fv_mask_chart = (
            pd.to_numeric(ts.get("pv_kWh", pd.Series(dtype=float)), errors="coerce")
            .fillna(0.0) > 0.01
        )
        user_stds = []
        for col in alpha_cols:
            all_vals = pd.to_numeric(ts.loc[fv_mask_chart, col], errors="coerce").dropna()
            user_stds.append(float(all_vals.std(ddof=1)) if len(all_vals) > 1 else 0.0)
        max_std = max(user_stds) if user_stds else 0.0
        HIGH_VAR_THRESHOLD = 0.04

        fig = go.Figure()

        if max_std < HIGH_VAR_THRESHOLD:
            for i, (col, label) in enumerate(zip(alpha_cols, y_labels)):
                color = _USER_PALETTE[i % len(_USER_PALETTE)]
                fig.add_trace(go.Scatter(
                    x=period_labels,
                    y=z_matrix[i],
                    mode="lines",
                    name=label,
                    line=dict(shape="hv", width=2.5, color=color),
                    hovertemplate=f"<b>{label}</b><br>%{{x}}<br>alpha = %{{y:.4f}}<extra></extra>",
                ))
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=8, r=8, t=8, b=8),
                font=dict(size=11),
                hovermode="x unified",
                yaxis=dict(rangemode="tozero", tickformat=".2f",
                           gridcolor="rgba(0,0,0,0.05)", zeroline=False,
                           title=dict(text="alpha", font=dict(size=11))),
                xaxis=dict(tickangle=-40 if len(period_labels) > 8 else 0,
                           tickfont=dict(size=9), gridcolor="rgba(0,0,0,0)"),
                legend=dict(orientation="h", x=0, y=-0.22, font=dict(size=11),
                            bgcolor="rgba(0,0,0,0)"),
                hoverlabel=dict(bgcolor="#1e293b", bordercolor="#1e293b",
                                font=dict(color="#f8fafc", size=12)),
            )
        else:
            equal_share = round(1.0 / n_u, 4) if n_u else 0.25

            user_stats = []
            for i, (col, label) in enumerate(zip(alpha_cols, y_labels)):
                vals  = pd.to_numeric(ts.loc[fv_mask_chart, col], errors="coerce").dropna()
                color = _USER_PALETTE[i % len(_USER_PALETTE)]
                mean_v   = float(vals.mean())   if len(vals) else 0.0
                std_v    = float(vals.std(ddof=1)) if len(vals) > 1 else 0.0
                median_v = float(vals.median()) if len(vals) else 0.0
                user_stats.append({
                    "label":  label, "color": color,
                    "mean":   mean_v,
                    "median": median_v,
                    "lo":     max(0.0, mean_v - std_v),
                    "hi":     min(1.0, mean_v + std_v),
                })

            exante_means = {}
            for k in data.get("series", {}):
                if "ex" in k.lower() and "ante" in k.lower():
                    ts_ea = get_serie(data["series"], k)
                    ea_cols = [c for c in ts_ea.columns if c.startswith("alpha_u")]
                    fv_mask_ea = (
                        pd.to_numeric(ts_ea.get("pv_kWh", pd.Series(dtype=float)), errors="coerce")
                        .fillna(0.0) > 0.01
                    )
                    for j, ea_col in enumerate(ea_cols):
                        if j < len(y_labels):
                            ea_v = pd.to_numeric(ts_ea.loc[fv_mask_ea, ea_col], errors="coerce").dropna()
                            if len(ea_v):
                                exante_means[y_labels[j]] = float(ea_v.mean())
                    break

            for i, stat in enumerate(user_stats):
                r_c = int(stat["color"][1:3], 16)
                g_c = int(stat["color"][3:5], 16)
                b_c = int(stat["color"][5:7], 16)
                first = (i == 0)
                lbl   = stat["label"]

                fig.add_trace(go.Scatter(
                    x=[stat["lo"], stat["hi"]], y=[lbl, lbl],
                    mode="lines", name="Dispersión (±std)",
                    legendgroup="disp", showlegend=first,
                    line=dict(color=f"rgba({r_c},{g_c},{b_c},0.45)", width=4),
                    hoverinfo="skip",
                ))
                fig.add_trace(go.Scatter(
                    x=[stat["mean"]], y=[lbl],
                    mode="markers", name="Media",
                    legendgroup="mean_dyn", showlegend=first,
                    marker=dict(symbol="circle", size=14, color=stat["color"],
                                line=dict(width=2, color="white")),
                    hovertemplate=(
                        f"<b>{lbl}</b><br>"
                        f"Media: {formato_num(stat['mean'], 3)}<br>"
                        f"Dispersión: [{formato_num(stat['lo'], 3)} – {formato_num(stat['hi'], 3)}]"
                        "<extra></extra>"
                    ),
                ))
                fig.add_trace(go.Scatter(
                    x=[stat["median"]], y=[lbl],
                    mode="markers", name="Mediana",
                    legendgroup="median", showlegend=first,
                    marker=dict(symbol="diamond", size=11, color="white",
                                line=dict(width=2.5, color=stat["color"])),
                    hovertemplate=f"<b>{lbl}</b><br>Mediana: {formato_num(stat['median'], 3)}<extra></extra>",
                ))
                if lbl in exante_means:
                    ea_val = exante_means[lbl]
                    fig.add_trace(go.Scatter(
                        x=[ea_val], y=[lbl],
                        mode="markers", name="Media ex ante",
                        legendgroup="mean_ea", showlegend=first,
                        marker=dict(symbol="diamond", size=11, color="white",
                                    line=dict(width=2.5, color="#6B7280")),
                        hovertemplate=f"<b>{lbl}</b><br>Media ex ante: {formato_num(ea_val, 3)}<extra></extra>",
                    ))

            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=8, r=8, t=28, b=8),
                font=dict(size=11),
                xaxis=dict(rangemode="tozero", tickformat=".2f",
                           gridcolor="rgba(0,0,0,0.06)", zeroline=False,
                           title=dict(text="alpha", font=dict(size=11))),
                yaxis=dict(tickfont=dict(size=11), gridcolor="rgba(0,0,0,0)",
                           autorange="reversed"),
                legend=dict(orientation="h", x=0, y=-0.18, font=dict(size=11),
                            bgcolor="rgba(0,0,0,0)"),
                hoverlabel=dict(bgcolor="#1e293b", bordercolor="#1e293b",
                                font=dict(color="#f8fafc", size=12)),
            )

        return fig

    @app.callback(
        Output("alpha-mean-table", "children"),
        Input("results-store", "data"),
    )
    def render_alpha_mean_table(data):
        if not data or "models" not in data or "series" not in data:
            return html.Div()

        series = data["series"]
        models = data["models"]

        all_users_disp = []
        for m in models:
            ud = m.get("users_display") or []
            if ud:
                all_users_disp = ud
                break
        if not all_users_disp:
            return html.Div()

        table_rows = []
        for m in models:
            label  = m["Modelo"]
            tipo   = m.get("Tipo", "ex_ante")
            prefix = ("alpha_ex_"  if tipo == "ex_ante"
                      else "alpha_fx_"  if tipo == "fijo"
                      else "alpha_bat_" if tipo == "bateria"
                      else "alpha_prop_")
            ts     = get_serie(series, label)
            if ts.empty:
                continue
            alpha_cols = sorted([c for c in ts.columns if c.startswith(prefix)])
            ud = m.get("users_display") or [f"U{i+1}" for i in range(len(alpha_cols))]

            if "pv_kWh" in ts.columns:
                fv_mask = pd.to_numeric(ts["pv_kWh"], errors="coerce").fillna(0) > 0.01
            else:
                fv_mask = pd.Series(True, index=ts.index)
            means = {}
            for i, col in enumerate(alpha_cols):
                vals = pd.to_numeric(ts.loc[fv_mask, col], errors="coerce").dropna()
                means[ud[i] if i < len(ud) else f"U{i+1}"] = vals.mean() if not vals.empty else float("nan")
            table_rows.append({"modelo": label, "tipo": tipo, "means": means})

        if not table_rows:
            return html.Div()

        th_base = {
            "padding": "8px 12px", "fontSize": "11px", "fontWeight": "700",
            "textTransform": "uppercase", "letterSpacing": "0.5px",
            "borderBottom": "2px solid var(--border, #e2e8f0)",
            "textAlign": "center", "whiteSpace": "nowrap",
        }
        td_base = {
            "padding": "8px 12px", "fontSize": "12px",
            "borderBottom": "1px solid var(--border, #e2e8f0)",
            "textAlign": "center",
        }
        td_label = dict(td_base, textAlign="left", fontWeight="600",
                        color="var(--text, #1e293b)", maxWidth="180px",
                        overflow="hidden", textOverflow="ellipsis", whiteSpace="nowrap")

        header_cells = [html.Th("Modelo", style=dict(th_base, textAlign="left"))]
        for i, u in enumerate(all_users_disp):
            color = _USER_PALETTE[i % len(_USER_PALETTE)]
            header_cells.append(html.Th(
                u,
                style=dict(th_base, color=color, borderBottom=f"2px solid {color}"),
            ))

        body_rows = []
        for ri, row in enumerate(table_rows):
            bg = "rgba(0,0,0,0.015)" if ri % 2 == 1 else "transparent"
            cells = [html.Td(row["modelo"],
                             style=dict(td_label, background=bg))]
            for i, u in enumerate(all_users_disp):
                val = row["means"].get(u, float("nan"))
                color = _USER_PALETTE[i % len(_USER_PALETTE)]
                if val != val:  # nan
                    txt = "—"
                    cell_style = dict(td_base, background=bg, color="#94a3b8")
                else:
                    txt = f"{val:.1%}"
                    cell_style = dict(td_base, background=bg,
                                      color=color, fontWeight="600",
                                      fontSize="13px")
                cells.append(html.Td(txt, style=cell_style))
            body_rows.append(html.Tr(cells))

        table = html.Table(
            [html.Thead(html.Tr(header_cells)), html.Tbody(body_rows)],
            style={
                "width": "100%", "borderCollapse": "collapse",
                "borderRadius": "8px", "overflow": "hidden",
            },
        )

        return html.Div([
            html.Div("Media del coeficiente por modelo y usuario",
                     style={"fontSize": "11px", "fontWeight": "700", "color": "var(--text-muted, #64748b)",
                            "textTransform": "uppercase", "letterSpacing": "0.5px",
                            "marginBottom": "8px"}),
            html.Div("Solo se consideran períodos con generación FV > 0.",
                     style={"fontSize": "10px", "color": "#94a3b8", "marginBottom": "10px"}),
            html.Div(table, style={"overflowX": "auto"}),
        ])

    @app.callback(
        Output("alpha-daterange-model", "options"),
        Output("alpha-daterange-model", "value"),
        Output("alpha-daterange-start", "value"),
        Output("alpha-daterange-end",   "value"),
        Input("results-store", "data"),
    )
    def update_alpha_daterange_options(data):
        if not data or "models" not in data:
            return [], None, None, None
        opts = [{"label": m["Modelo"], "value": m["Modelo"]} for m in data["models"]]
        default = opts[0]["value"] if opts else None
        t_min = t_max = None
        for s in (data.get("series") or {}).values():
            rows = (s or {}).get("rows") or []
            if rows:
                first = rows[0]
                tcol = next(
                    (c for c in ["Time", "time", "timestamp", "datetime", "t"]
                     if c in first),
                    None,
                )
                if tcol:
                    time_vals = [r[tcol] for r in rows if r.get(tcol) is not None]
                    times = pd.to_datetime(time_vals, errors="coerce").dropna()
                    if not times.empty:
                        t_min, t_max = times.min(), times.max()
            break
        start_str = t_min.strftime("%Y-%m-%d") if t_min else None
        end_str   = t_max.strftime("%Y-%m-%d") if t_max else None
        return opts, default, start_str, end_str

    @app.callback(
        Output("fig-alpha-daterange", "figure"),
        Input("alpha-daterange-model", "value"),
        Input("alpha-daterange-start", "value"),
        Input("alpha-daterange-end",   "value"),
        Input("results-store", "data"),
    )
    def update_alpha_daterange(model_label, start_str, end_str, data):
        if not model_label or not data or "series" not in data:
            return grafico_vacio("Selecciona modelo y rango de fechas.")

        series = data.get("series", {}) or {}
        ts = get_serie(series, model_label)
        if ts.empty:
            return grafico_vacio("No hay series disponibles para este modelo.")

        tcol = col_tiempo(ts)
        if not tcol:
            return grafico_vacio("No se encontró columna temporal.")

        ts = ts.copy()
        ts[tcol] = pd.to_datetime(ts[tcol], errors="coerce")
        ts = ts.dropna(subset=[tcol]).sort_values(tcol).reset_index(drop=True)

        if start_str:
            ts = ts[ts[tcol] >= pd.Timestamp(start_str)]
        if end_str:
            ts = ts[ts[tcol] <= pd.Timestamp(end_str) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)]
        if ts.empty:
            return grafico_vacio("No hay datos en el rango de fechas seleccionado.")

        model_row = next((m for m in data["models"] if m["Modelo"] == model_label), None)
        tipo      = (model_row or {}).get("Tipo", "ex_ante")
        prefix    = ("alpha_ex_" if tipo == "ex_ante"
                     else "alpha_fx_" if tipo == "fijo"
                     else "alpha_prop_")
        alpha_cols = sorted([c for c in ts.columns if c.startswith(prefix)])
        if not alpha_cols:
            return grafico_vacio("No se encontraron columnas de coeficiente alpha para este modelo.")

        users_display = []
        for m in (data.get("models") or []):
            if m.get("Modelo") == model_label:
                users_display = m.get("users_display") or []
                break
        if not users_display:
            users_display = [f"Usuario {i+1}" for i in range(len(alpha_cols))]

        ts = ts.set_index(tcol)
        fig = go.Figure()
        for i, col in enumerate(alpha_cols):
            label = users_display[i] if i < len(users_display) else f"U{i+1}"
            color = _USER_PALETTE[i % len(_USER_PALETTE)]
            serie = pd.to_numeric(ts[col], errors="coerce").dropna()
            serie_daily = serie.resample("D").mean().dropna()
            if serie_daily.empty:
                continue
            fig.add_trace(go.Scatter(
                x=serie_daily.index,
                y=serie_daily.values,
                mode="lines",
                name=label,
                line=dict(width=2, color=color),
                hovertemplate=f"<b>{label}</b><br>%{{x|%Y-%m-%d}}<br>\u03b1 = %{{y:.4f}}<extra></extra>",
            ))

        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=8, r=8, t=8, b=8),
            font=dict(size=11),
            hovermode="x unified",
            yaxis=dict(rangemode="tozero", tickformat=".3f",
                       gridcolor="rgba(0,0,0,0.05)", zeroline=False,
                       title=dict(text="\u03b1", font=dict(size=11))),
            xaxis=dict(tickfont=dict(size=9), gridcolor="rgba(0,0,0,0)"),
            legend=dict(orientation="h", x=0, y=-0.22, font=dict(size=11),
                        bgcolor="rgba(0,0,0,0)"),
            hoverlabel=dict(bgcolor="#1e293b", bordercolor="#1e293b",
                            font=dict(color="#f8fafc", size=12)),
        )
        return fig

    @app.callback(
        Output("explorer-stats-row",      "children"),
        Output("fig-explorer-price",      "figure"),
        Output("monthly-balance-cards",   "children"),
        Output("explorer-placeholder",    "children"),
        Input("results-store", "data"),
    )
    def render_explorer(data):
        _no     = grafico_vacio("Ejecuta el modelo para explorar los datos.")
        _no_cards = html.Div("Sin datos.", className="text-muted small text-center py-3")
        if not data or "series" not in data or not data["series"]:
            return [], _no, _no_cards, "Ejecuta el modelo en Configurar para ver los datos."

        series  = data["series"]
        models  = data.get("models", [])
        valid_models = [m for m in models if m.get("Coste (€)") is not None and m["Modelo"] in series]
        if valid_models:
            best_key = min(valid_models, key=lambda m: m["Coste (€)"])["Modelo"]
        else:
            best_key = next(iter(series))
        ts_raw  = get_serie(series, best_key)
        if ts_raw.empty:
            return [], _no, _no_cards, "No se encontraron series de datos."

        tcol = col_tiempo(ts_raw)
        if not tcol:
            return [], _no, _no_cards, "No se encontró columna temporal."

        ts = ts_raw.copy()
        ts[tcol] = pd.to_datetime(ts[tcol], errors="coerce")
        ts = ts.dropna(subset=[tcol]).sort_values(tcol).reset_index(drop=True)
        ts["hour"] = ts[tcol].dt.hour

        n_rows   = len(ts)
        if n_rows:
            t_dt_min = ts[tcol].min()
            t_dt_max = ts[tcol].max()
            if t_dt_min.year == t_dt_max.year:
                if t_dt_min.month == 1 and t_dt_max.month == 12:
                    t_start = str(t_dt_max.year)
                else:
                    t_start = f"{_MESES[t_dt_min.month-1]}–{_MESES[t_dt_max.month-1]} {t_dt_max.year}"
            else:
                t_start = f"{t_dt_min.year}–{str(t_dt_max.year)[2:]}"
        else:
            t_start = "—"
        dem_col  = primera_col(ts.columns, ["demand_kWh", "D_total"])
        pv_col_e = primera_col(ts.columns, ["pv_kWh", "G"])

        total_dem = float(ts[dem_col].sum()) if dem_col else 0.0
        total_pv  = float(ts[pv_col_e].sum()) if pv_col_e else 0.0
        user_cols = [c for c in ts.columns if c.startswith("self_ex_u")]
        n_users   = len(user_cols)
        pv_coverage_pct = (total_pv / total_dem * 100.0) if total_dem > 1e-12 else 0.0

        def stat_tile(label, value, variant):
            return dbc.Card(
                dbc.CardBody([
                    html.Div(label, className="kpi-label"),
                    html.Div(value, className="kpi-value"),
                    html.Div("", className="kpi-delta"),
                ]),
                className=f"kpi-card {variant}",
            )

        bat_model = next(
            (m for m in models if m.get("Tipo") == "bateria" and m.get("Coste (€)") is not None),
            None,
        )
        if bat_model and bat_model.get("bat_efc") and bat_model["bat_efc"] > 0:
            efc_period       = float(bat_model["bat_efc"])
            lifecycle_cycles = int(bat_model.get("bat_lifecycle_cycles") or 7000)
            vida_restante_pct = max(0.0, (1 - efc_period / lifecycle_cycles) * 100)
            fourth_tile = stat_tile("Vida restante bat.", f"{vida_restante_pct:.2f} %", "warning")
        else:
            fourth_tile = stat_tile("Usuarios", str(n_users), "warning")

        stats_row = [
            stat_tile("Periodo",       t_start,                                                             "brand"),
            stat_tile("Generación FV", f"{formato_num(total_pv, 0)} kWh" if total_pv > 0 else "—",         "success"),
            fourth_tile,
            stat_tile("Demanda total", f"{formato_num(total_dem, 0)} kWh",                                  "accent"),
        ]

        fig_price = go.Figure()
        buy_col_e  = primera_col(ts.columns, ["p_buy"])
        sell_col_e = primera_col(ts.columns, ["p_sell"])
        p_buy_24 = p_sell_24 = None
        if buy_col_e:
            p_buy_24 = (ts.groupby("hour")[buy_col_e].mean()
                          .reindex(range(24)).ffill().reset_index())
        if sell_col_e:
            p_sell_24 = (ts.groupby("hour")[sell_col_e].mean()
                           .reindex(range(24)).ffill().reset_index())
        if p_buy_24 is not None and p_sell_24 is not None:
            fig_price.add_trace(go.Scatter(
                x=list(p_buy_24["hour"]) + list(reversed(p_sell_24["hour"].tolist())),
                y=list(p_buy_24[buy_col_e]) + list(reversed(p_sell_24[sell_col_e].tolist())),
                fill="toself",
                fillcolor="rgba(1,69,147,0.07)",
                line=dict(color="rgba(0,0,0,0)"),
                name="Spread compra/venta",
                hoverinfo="skip",
            ))
        if p_buy_24 is not None:
            fig_price.add_trace(go.Scatter(
                x=p_buy_24["hour"], y=p_buy_24[buy_col_e],
                mode="lines", name="Precio compra",
                line=dict(color=COLOR_EX_ANTE, width=2.5)))
        if p_sell_24 is not None:
            fig_price.add_trace(go.Scatter(
                x=p_sell_24["hour"], y=p_sell_24[sell_col_e],
                mode="lines", name="Precio venta",
                line=dict(color=COLOR_DYNAMIC, width=2, dash="dash")))
        estilo_grafico(fig_price, y_title="€/kWh")
        fig_price.update_xaxes(dtick=2, tick0=0, title="Hora del día")
        fig_price.update_layout(
            margin=dict(b=12, t=8),
            legend=dict(orientation="h", x=0, y=1.08, yanchor="bottom",
                        xanchor="left", bgcolor="rgba(0,0,0,0)"),
        )

        fig_monthly_balance = go.Figure()

        self_col = primera_col(ts.columns, ["self_bat", "self_prop", "self_ex_ante"])
        imp_col  = primera_col(ts.columns, ["imp_bat",  "imp_prop",  "imp_ex_ante"])
        exp_col  = primera_col(ts.columns, ["exp_bat",  "exp_prop",  "exp_ex_ante"])

        if not (self_col and imp_col and exp_col) and user_cols and dem_col and pv_col_e:
            ts["_self_total"] = ts[user_cols].sum(axis=1)
            ts["_imp_total"]  = (ts[dem_col] - ts["_self_total"]).clip(lower=0)
            ts["_exp_total"]  = (ts[pv_col_e] - ts["_self_total"]).clip(lower=0)
            self_col, imp_col, exp_col = "_self_total", "_imp_total", "_exp_total"

        if self_col and imp_col and exp_col:
            ts["_month"] = ts[tcol].dt.month
            mon_self = (ts.groupby("_month")[self_col].sum()
                          .reindex(range(1, 13), fill_value=0.0))
            mon_imp  = (ts.groupby("_month")[imp_col].sum()
                          .reindex(range(1, 13), fill_value=0.0))
            mon_exp  = (ts.groupby("_month")[exp_col].sum()
                          .reindex(range(1, 13), fill_value=0.0))
            coverage_line = [
                float(s / (s + i) * 100) if (s + i) > 1e-9 else 0.0
                for s, i in zip(mon_self.tolist(), mon_imp.tolist())
            ]

            BAR_MAX_H = 280
            max_total = max((float(mon_self.iloc[mi]) + float(mon_imp.iloc[mi]) +
                             float(mon_exp.iloc[mi])) for mi in range(12)) or 1.0

            def _seg(bg, h, val, r_top=False, r_bot=False, min_label_h=10):
                if h <= 0:
                    return None
                br = []
                if r_top: br += ["borderTopLeftRadius:4px", "borderTopRightRadius:4px"]
                if r_bot: br += ["borderBottomLeftRadius:4px", "borderBottomRightRadius:4px"]
                br_str = "; ".join(br)
                return html.Div(
                    html.Span(f"{formato_num(val, 0)}", style={
                        "color": "white", "fontSize": "10px", "fontWeight": "800",
                    }) if h >= min_label_h else None,
                    style={
                        "height": f"{h}px", "background": bg,
                        "display": "flex", "alignItems": "center",
                        "justifyContent": "center",
                        **({"borderTopLeftRadius": "4px", "borderTopRightRadius": "4px"} if r_top else {}),
                        **({"borderBottomLeftRadius": "4px", "borderBottomRightRadius": "4px"} if r_bot else {}),
                    },
                    title=f"{formato_num(val, 0)} kWh",
                )

            month_cards = []
            for mi in range(12):
                sv = float(mon_self.iloc[mi])
                iv = float(mon_imp.iloc[mi])
                ev = float(mon_exp.iloc[mi])
                cv = float(coverage_line[mi])
                total = sv + iv + ev
                has_data = total > 1.0
                EXP_MIN_H = 14  # altura mínima visible para excedente
                bar_h   = int(total / max_total * BAR_MAX_H) if has_data else 4
                e_h_raw = int(ev / total * bar_h) if has_data and ev > 0 else 0
                e_h = max(EXP_MIN_H, e_h_raw) if e_h_raw > 0 else 0
                s_h = max(1, int(sv / total * bar_h)) if has_data and sv > 0 else 0
                i_h = max(0, bar_h - s_h - e_h)

                top_seg  = "exp" if e_h > 0 else ("imp" if i_h > 0 else "self")
                bot_seg  = "self" if s_h > 0 else ("imp" if i_h > 0 else "exp")

                month_cards.append(html.Div([
                    html.Div(_MESES[mi], className="mc-month"),
                    html.Div([
                        _seg("#F39C12", e_h, ev, r_top=True,  r_bot=(top_seg=="exp" and bot_seg=="exp"), min_label_h=EXP_MIN_H),
                        _seg("#E74C3C", i_h, iv, r_top=(top_seg=="imp"), r_bot=(bot_seg=="imp")),
                        _seg("#18BC9C", s_h, sv, r_top=(top_seg=="self"), r_bot=True),
                    ], style={
                        "width": "100%", "display": "flex", "flexDirection": "column",
                        "height": f"{BAR_MAX_H}px", "justifyContent": "flex-end", "gap": "2px",
                    }),
                    html.Div(f"{formato_num(cv, 0)}%" if has_data else "—", className="mc-pct"),
                ], className="mc-mini-col"))

            monthly_balance_out = month_cards
        else:
            monthly_balance_out = html.Div(
                "Sin datos de flujos de energía.",
                className="text-muted small text-center py-4",
            )

        return stats_row, fig_price, monthly_balance_out, ""

    @app.callback(
        Output("export-preview-content", "children"),
        Output("export-sheets-info",     "children"),
        Input("results-store",         "data"),
        Input("export-sw-comparativa", "value"),
        Input("export-sw-series",      "value"),
        Input("export-sw-costes",      "value"),
        Input("export-sw-alpha",       "value"),
        Input("export-sw-bateria_fin", "value"),
        Input("export-sw-bateria_soc", "value"),
    )
    def render_export_preview(data, sw_comp, sw_ser, sw_cos, sw_alp, sw_bat_fin, sw_bat_soc):
        active = (
            ("comparativa"  in (sw_comp    or [])) +
            ("series"       in (sw_ser     or [])) +
            ("costes"       in (sw_cos     or [])) +
            ("alpha"        in (sw_alp     or [])) +
            ("bateria_fin"  in (sw_bat_fin or [])) +
            ("bateria_soc"  in (sw_bat_soc or []))
        )
        _SHEET_LABELS = {
            "comparativa": "Comparativa",
            "series":      "Series temporales",
            "costes":      "Costes por usuario",
            "alpha":       "Coef. Alpha",
            "bateria_fin": "Batería - Financiero",
            "bateria_soc": "Batería - SOC",
        }
        sw_map = {"comparativa": sw_comp, "series": sw_ser,
                  "costes": sw_cos, "alpha": sw_alp,
                  "bateria_fin": sw_bat_fin, "bateria_soc": sw_bat_soc}
        active_names = [_SHEET_LABELS[k] for k, v in sw_map.items() if k in (v or [])]

        if active == 0:
            sheets_el = html.Span("Selecciona al menos una hoja para exportar",
                                  style={"fontSize": "12px", "color": "#E74C3C"})
        else:
            badges = [
                html.Span(name, style={
                    "fontSize": "11px", "fontWeight": "600", "padding": "3px 8px",
                    "borderRadius": "12px", "background": "rgba(1,69,147,0.08)",
                    "color": "#014593", "marginRight": "4px",
                }) for name in active_names
            ]
            sheets_el = html.Div([
                html.Span(f"{active} {'hoja' if active == 1 else 'hojas'}  ·  Excel (.xlsx)  ·  ",
                          style={"fontSize": "12px", "fontWeight": "600",
                                 "color": "var(--text)", "marginRight": "6px"}),
                *badges,
            ], style={"display": "flex", "alignItems": "center", "flexWrap": "wrap", "gap": "2px"})

        if not data or "models" not in data or not data["models"]:
            preview = html.Div("Ejecuta el modelo para ver la vista previa.",
                               style={"color": "#94a3b8", "fontSize": "12px",
                                      "padding": "20px 0"})
            return preview, sheets_el

        df_m = pd.DataFrame(data["models"])
        drop = [c for c in df_m.columns
                if c.startswith("cost_per_user") or c in ("users_display", "Tipo")]
        df_m = df_m.drop(columns=drop, errors="ignore")
        num  = df_m.select_dtypes("number").columns
        df_m[num] = df_m[num].round(2)
        df_prev = df_m.head(5)

        th_s = {"padding": "7px 10px", "fontSize": "10px", "fontWeight": "700",
                "textTransform": "uppercase", "letterSpacing": "0.4px",
                "background": "#014593", "color": "#fff",
                "textAlign": "left", "whiteSpace": "nowrap"}
        td_s = {"padding": "6px 10px", "fontSize": "11px",
                "borderBottom": "1px solid var(--border, #e2e8f0)",
                "whiteSpace": "nowrap"}
        header = html.Thead(html.Tr([html.Th(c, style=th_s) for c in df_prev.columns]))
        body_rows = []
        for ri, (_, row) in enumerate(df_prev.iterrows()):
            bg = "rgba(0,0,0,0.015)" if ri % 2 == 1 else "transparent"
            body_rows.append(html.Tr([
                html.Td(str(v) if v == v else "—", style=dict(td_s, background=bg))
                for v in row
            ]))
        preview = html.Table(
            [header, html.Tbody(body_rows)],
            style={"width": "100%", "borderCollapse": "collapse",
                   "fontSize": "11px", "borderRadius": "6px", "overflow": "hidden"},
        )
        note = html.Div(
            f"Mostrando {len(df_prev)} de {len(df_m)} modelos · {len(df_prev.columns)} columnas",
            style={"fontSize": "10px", "color": "#94a3b8", "marginTop": "8px"},
        )
        return html.Div([preview, note]), sheets_el

    @app.callback(
        Output("battery-params-collapse", "is_open"),
        Input("battery-enabled", "value"),
    )
    def toggle_battery_params(value):
        return bool(value and "enabled" in value)

    @app.callback(
        Output("nav-bateria-wrap", "style"),
        Input("battery-enabled", "value"),
    )
    def toggle_bateria_tab(value):
        if value and "enabled" in value:
            return {"display": "block"}
        return {"display": "none"}

    @app.callback(
        Output("export-battery-collapse", "is_open"),
        Input("results-store", "data"),
        Input("battery-enabled", "value"),
    )
    def toggle_export_battery(results, battery_enabled):
        try:
            if not (battery_enabled and "enabled" in battery_enabled):
                return False
            models = (results or {}).get("models") or []
            return any(
                m.get("Tipo") == "bateria" and m.get("Coste (€)") is not None
                for m in models
            )
        except Exception:
            return False

    @app.callback(
        Output("seasonal-cards-row",       "children"),
        Output("fig-seasonal-comparison",  "figure"),
        Input("results-store", "data"),
    )
    def render_seasonal(data):
        _no_fig = grafico_vacio("Ejecuta el modelo para ver el análisis estacional.")
        if not data or "series" not in data or not data["series"]:
            return html.Div(), _no_fig

        series = data.get("series", {})
        models = data.get("models", [])
        if not series:
            return html.Div(), _no_fig

        df_m = pd.DataFrame(models)
        if df_m.empty or "Coste (€)" not in df_m.columns:
            return html.Div(), _no_fig
        df_m["Coste (€)"] = pd.to_numeric(df_m["Coste (€)"], errors="coerce")
        df_m = df_m.dropna(subset=["Coste (€)"])
        if df_m.empty:
            return html.Div(), _no_fig

        best_label = str(df_m.loc[df_m["Coste (€)"].idxmin(), "Modelo"])
        ref_label  = next(
            (str(m["Modelo"]) for m in models
             if "rd 244" in str(m.get("Modelo", "")).lower() or
                "ex ante rd" in str(m.get("Modelo", "")).lower()),
            None,
        )

        ts_best = get_serie(series, best_label)
        if ts_best.empty:
            ts_best = get_serie(series, next(iter(series)))
        tcol = col_tiempo(ts_best)
        if not tcol:
            return html.Div(), _no_fig

        ts = ts_best.copy()
        ts[tcol] = pd.to_datetime(ts[tcol], errors="coerce")
        ts = ts.dropna(subset=[tcol]).sort_values(tcol).reset_index(drop=True)

        def _season(month):
            if month in (12, 1, 2):  return "Invierno"
            if month in (3, 4, 5):   return "Primavera"
            if month in (6, 7, 8):   return "Verano"
            return "Otoño"

        _SEASON_ORDER  = ["Invierno", "Primavera", "Verano", "Otoño"]
        _SEASON_ICON   = {"Invierno": "❄️", "Primavera": "🌸", "Verano": "☀️", "Otoño": "🍂"}
        _SEASON_COLOR  = {"Invierno": "#2980B9", "Primavera": "#27AE60",
                          "Verano": "#F39C12", "Otoño": "#E67E22"}

        ts["_season"] = ts[tcol].dt.month.map(_season)

        best_kind = ("ex_ante" if "ex ante" in best_label.lower() else
                     "fijo"    if any(m.get("Tipo") == "fijo" and m.get("Modelo") == best_label
                                      for m in models) else "prop")
        self_col = primera_col(ts.columns,
            ["self_prop", "self_ex_ante", "self_fixed", "self_bat"])
        imp_col  = primera_col(ts.columns,
            ["imp_prop",  "imp_ex_ante",  "imp_fixed",  "imp_bat"])
        exp_col  = primera_col(ts.columns,
            ["exp_prop",  "exp_ex_ante",  "exp_fixed",  "exp_bat"])
        dem_col  = primera_col(ts.columns, ["demand_kWh", "D_total"])

        if not (self_col and dem_col):
            return html.Div(), _no_fig

        season_stats = {}
        for s in _SEASON_ORDER:
            mask = ts["_season"] == s
            dem  = float(ts.loc[mask, dem_col].sum()) if dem_col else 0
            self_kwh = float(ts.loc[mask, self_col].sum()) if self_col else 0
            imp_kwh  = float(ts.loc[mask, imp_col].sum())  if imp_col  else 0
            exp_kwh  = float(ts.loc[mask, exp_col].sum())  if exp_col  else 0
            season_stats[s] = {
                "demand": dem, "self": self_kwh, "imp": imp_kwh, "exp": exp_kwh,
                "self_pct": self_kwh / dem * 100 if dem > 0 else 0,
                "imp_pct":  imp_kwh  / dem * 100 if dem > 0 else 0,
            }

        ref_stats = {}
        if ref_label and ref_label != best_label:
            ts_ref = get_serie(series, ref_label)
            if not ts_ref.empty:
                tc_r = col_tiempo(ts_ref)
                if tc_r:
                    ts_r = ts_ref.copy()
                    ts_r[tc_r] = pd.to_datetime(ts_r[tc_r], errors="coerce")
                    ts_r = ts_r.dropna(subset=[tc_r]).sort_values(tc_r).reset_index(drop=True)
                    ts_r["_season"] = ts_r[tc_r].dt.month.map(_season)
                    sc_r = primera_col(ts_r.columns, ["self_ex_ante", "self_prop"])
                    dm_r = primera_col(ts_r.columns, ["demand_kWh", "D_total"])
                    for s in _SEASON_ORDER:
                        mask = ts_r["_season"] == s
                        dem  = float(ts_r.loc[mask, dm_r].sum()) if dm_r else 0
                        sfc  = float(ts_r.loc[mask, sc_r].sum()) if sc_r else 0
                        ref_stats[s] = {"self_pct": sfc / dem * 100 if dem > 0 else 0}

        season_cards = []
        for s in _SEASON_ORDER:
            st   = season_stats[s]
            col  = _SEASON_COLOR[s]
            icon = _SEASON_ICON[s]
            ref_pct = (ref_stats[s]["self_pct"] if s in ref_stats else None)
            _d = st['self_pct'] - ref_pct if ref_pct else 0
            delta = (f"{'+'if _d >= 0 else ''}{formato_num(_d, 1)}%") if ref_pct else ""
            delta_col = "#27AE60" if (ref_pct and st['self_pct'] > ref_pct) else "#E74C3C"

            season_cards.append(dbc.Col(
                dbc.Card(dbc.CardBody([
                    html.Div([
                        html.Span(icon, style={"fontSize": "20px", "marginRight": "8px"}),
                        html.Span(s, style={"fontWeight": "700", "fontSize": "14px",
                                            "color": "var(--text)"}),
                    ], style={"display": "flex", "alignItems": "center",
                              "marginBottom": "10px"}),
                    html.Div([
                        html.Span(f"{formato_num(st['self_pct'], 1)}%",
                                  style={"fontSize": "28px", "fontWeight": "900",
                                         "color": col, "lineHeight": "1"}),
                        html.Span(" autoconsumo",
                                  style={"fontSize": "11px", "color": "var(--text-muted)",
                                         "marginLeft": "4px"}),
                    ]),
                    html.Div(delta,
                             style={"fontSize": "12px", "color": delta_col,
                                    "fontWeight": "700", "marginTop": "4px"})
                    if delta else html.Div(),
                    html.Div(
                        html.Div(style={
                            "width": f"{min(st['self_pct'], 100):.1f}%",
                            "height": "5px", "background": col, "borderRadius": "3px",
                        }),
                        style={"background": "var(--bg)", "borderRadius": "3px",
                               "overflow": "hidden", "marginTop": "10px"},
                    ),
                ]), style={"borderTop": f"3px solid {col}"}),
                className="chart-card",
                xs=6, sm=6, md=3,
            ))

        fig_season = go.Figure()
        x_cats     = _SEASON_ORDER
        self_vals  = [season_stats[s]["self_pct"] for s in x_cats]
        imp_vals   = [season_stats[s]["imp_pct"]  for s in x_cats]

        fig_season.add_trace(go.Bar(
            name=f"Autoconsumo {best_label[:20]}…" if len(best_label) > 20 else f"Autoconsumo {best_label}",
            x=x_cats, y=self_vals,
            marker_color=COLOR_DYNAMIC, opacity=0.85,
        ))
        if ref_stats:
            ref_self = [ref_stats[s]["self_pct"] for s in x_cats]
            fig_season.add_trace(go.Bar(
                name="Autoconsumo Ref. (Ex ante)",
                x=x_cats, y=ref_self,
                marker_color=COLOR_EX_ANTE, opacity=0.7,
            ))
        fig_season.add_trace(go.Bar(
            name="Importación red",
            x=x_cats, y=imp_vals,
            marker_color=COLOR_DEMAND, opacity=0.6,
            yaxis="y2",
        ))
        estilo_grafico(fig_season, y_title="Autoconsumo (%)", y2_title="Importación (%)", barmode="group")
        fig_season.update_layout(margin=dict(l=8, r=8, t=10, b=10))

        return dbc.Row(season_cards, className="g-3"), fig_season

    @app.callback(
        Output("battery-soc-collapse", "is_open"),
        Output("fig-battery-soc",      "figure"),
        Input("results-store", "data"),
    )
    def render_battery_soc(data):
        if not data or "series" not in data:
            return False, grafico_vacio("Sin datos de batería.")

        bat_model = next(
            (m for m in (data.get("models") or [])
             if m.get("Tipo") == "bateria" and m.get("Coste (€)") is not None),
            None,
        )
        if not bat_model:
            return False, grafico_vacio("Sin datos de batería.")

        bat_label   = bat_model["Modelo"]
        bat_cap_kwh = float(bat_model.get("battery_capacity_kwh") or 50.0)

        ts = get_serie(data["series"], bat_label)
        if ts.empty or "soc_bat" not in ts.columns:
            return False, grafico_vacio("Sin columna SOC en series de batería.")

        tcol = col_tiempo(ts)
        if not tcol:
            return False, grafico_vacio("Sin columna temporal.")

        ts[tcol] = pd.to_datetime(ts[tcol], errors="coerce")
        ts = ts.dropna(subset=[tcol]).sort_values(tcol).reset_index(drop=True)
        ts["soc_bat"] = pd.to_numeric(ts["soc_bat"], errors="coerce")

        ts["soc_pct"] = (ts["soc_bat"] / bat_cap_kwh * 100.0).clip(0, 100)

        t0 = ts[tcol].iloc[0]
        init_row = pd.DataFrame({tcol: [t0 - pd.Timedelta(hours=1)], "soc_pct": [0.0]})
        ts_plot = pd.concat([init_row, ts[[tcol, "soc_pct"]]], ignore_index=True)

        soc_daily = (ts_plot.set_index(tcol)["soc_pct"]
                       .resample("D").mean()
                       .dropna()
                       .reset_index())

        soc_mean_pct = float(soc_daily["soc_pct"].mean())

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=soc_daily[tcol],
            y=soc_daily["soc_pct"],
            mode="lines",
            name="SOC diario medio (%)",
            fill="tozeroy",
            fillcolor="rgba(24,188,156,0.12)",
            line=dict(color="#18BC9C", width=2),
            hovertemplate="%{x|%d %b}<br>SOC: %{y:.1f}%<extra></extra>",
        ))
        fig.add_hline(
            y=soc_mean_pct,
            line_dash="dash",
            line_color="#E67E22",
            line_width=3,
            annotation_text=f" Media: {formato_num(soc_mean_pct, 1)}% ",
            annotation_position="right",
            annotation_font=dict(size=12, color="#fff", family="Inter, sans-serif"),
            annotation_bgcolor="#E67E22",
            annotation_borderpad=5,
        )
        estilo_grafico(fig, y_title="SOC (%)")
        fig.update_yaxes(range=[0, 105])
        fig.update_layout(margin=dict(l=8, r=90, t=8, b=8))
        return True, fig

    @app.callback(
        Output("bat-kpi-fin-payback",       "children"),
        Output("bat-kpi-fin-npv",           "children"),
        Output("bat-kpi-fin-irr",           "children"),
        Output("bat-kpi-fin-savings",       "children"),
        Output("bat-fig-fin-cashflow",      "figure"),
        Output("bat-fig-fin-waterfall",     "figure"),
        Output("bat-financiero-empty",      "style"),
        Output("bat-fin-capacity-display",  "children"),
        Output("fin-results-store",         "data"),
        Output("bat-fig-comparison",        "figure"),
        Output("bat-fin-capex-display",     "children"),
        Output("bat-fin-lifetime-display",  "children"),
        Input("results-store",         "data"),
        Input("bat-fin-om-pct",        "value"),
        Input("bat-fin-inflation",     "value"),
        Input("bat-fin-discount",      "value"),
        Input("bat-lifecycle-cycles",  "value"),
        State("bat-capacity",          "value"),
    )
    def render_financiero(data, om_pct, inflation, discount, lifecycle_cycles_ui, bat_capacity_val):
        _no = grafico_vacio("Sin datos de análisis.")
        empty_style = {"display": "flex"}
        hidden_style = {"display": "none"}

        optimal_cap = float(bat_capacity_val or 10.0)
        cap_display = f"{optimal_cap:.0f} kWh"

        if not data or "models" not in data or not data["models"]:
            return "—", "—", "—", "—", _no, _no, empty_style, cap_display, None, _no, "—", "—"

        df_m = pd.DataFrame(data["models"])
        df_m["Coste (€)"] = pd.to_numeric(df_m["Coste (€)"], errors="coerce")
        df_m = df_m.dropna(subset=["Coste (€)"])
        if df_m.empty:
            return "—", "—", "—", "—", _no, _no, empty_style, cap_display, None, _no, "—", "—"

        horario_row = df_m[df_m["Modelo"] == "Dinámico Horario"]
        bat_row     = df_m[df_m["Tipo"]   == "bateria"]
        if horario_row.empty or bat_row.empty:
            return "—", "—", "—", "—", _no, _no, empty_style, cap_display, None, _no, "—", "—"
        cost_horario = float(horario_row.iloc[0]["Coste (€)"])
        cost_bat_val = float(bat_row.iloc[0]["Coste (€)"])
        annual_savings = cost_horario - cost_bat_val

        bat_efc_sim      = float(bat_row.iloc[0].get("bat_efc", 0) or 0)
        lifecycle_cycles = int(lifecycle_cycles_ui or bat_row.iloc[0].get("bat_lifecycle_cycles", 7000) or 7000)
        cost_kwp_v       = float(bat_row.iloc[0].get("bat_capex_kwh", 250) or 250)
        lifetime_v       = max(1, int(round(lifecycle_cycles / bat_efc_sim))) if bat_efc_sim > 0 else 15
        capex_display    = f"{cost_kwp_v:.0f} €/kWh"
        lifetime_display = f"{lifetime_v} años"

        om_pct_v    = (float(om_pct)   if om_pct    is not None else 3.0)  / 100.0
        inflation_v = (float(inflation) if inflation is not None else 3.0) / 100.0
        discount_v  = (float(discount)  if discount  is not None else 5.0) / 100.0

        investment   = cost_kwp_v * max(optimal_cap, 1.0)
        om_annual    = investment * om_pct_v

        cumulative = [-investment]
        years      = list(range(lifetime_v + 1))
        npv        = -investment
        pv_savings = 0.0   # para el gráfico waterfall
        pv_om      = 0.0
        payback_yr = None

        for yr in range(1, lifetime_v + 1):
            infl_factor = (1 + inflation_v) ** (yr - 1)
            savings_yr  = annual_savings * infl_factor
            om_yr       = om_annual * infl_factor
            net_yr      = savings_yr - om_yr
            disc_factor = (1 + discount_v) ** yr
            pv_net_yr   = net_yr / disc_factor
            npv        += pv_net_yr
            pv_savings += savings_yr / disc_factor
            pv_om      += om_yr / disc_factor
            cumulative.append(cumulative[-1] + pv_net_yr)
            if payback_yr is None and cumulative[-1] >= 0:
                prev = cumulative[-2]
                curr = cumulative[-1]
                payback_yr = (yr - 1) + (-prev) / (curr - prev) if curr != prev else float(yr)

        def _npv_at_rate(r):
            v = -investment
            for yr in range(1, lifetime_v + 1):
                infl_factor = (1 + inflation_v) ** (yr - 1)
                savings_yr  = annual_savings * infl_factor
                om_yr       = om_annual * infl_factor
                net_yr      = savings_yr - om_yr
                v          += net_yr / ((1 + r) ** yr)
            return v

        irr = None
        try:
            lo, hi = 0.001, 2.0
            for _ in range(60):
                mid = (lo + hi) / 2
                if _npv_at_rate(mid) > 0:
                    lo = mid
                else:
                    hi = mid
                if hi - lo < 1e-5:
                    break
            irr = (lo + hi) / 2
        except Exception:
            pass

        if payback_yr is None:
            c = cumulative[-1]
            for yr in range(lifetime_v + 1, 101):
                infl_factor  = (1 + inflation_v) ** (yr - 1)
                disc_factor  = (1 + discount_v) ** yr
                net_yr       = annual_savings * infl_factor - om_annual * infl_factor
                prev = c
                c   += net_yr / disc_factor
                if c >= 0:
                    payback_yr = (yr - 1) + (-prev) / (c - prev) if c != prev else float(yr)
                    break

        if discount_v > 0 and lifetime_v > 0:
            annuity_factor = (1 - (1 + discount_v) ** (-lifetime_v)) / discount_v
            eaa = npv / annuity_factor if annuity_factor > 0 else npv / lifetime_v
        else:
            eaa = npv / lifetime_v if lifetime_v > 0 else 0.0

        kpi_pb  = f"{formato_num(payback_yr, 1)} años" if payback_yr is not None else "> 100 años"
        kpi_npv = f"{formato_num(npv, 0)} €"
        kpi_irr = f"{formato_num(irr * 100, 1)} %" if irr else "—"
        kpi_sav = f"{formato_num(eaa, 0)} €/año"

        fig_cf = go.Figure()

        bar_colors = [
            "rgba(24,188,156,0.85)" if v >= 0 else "rgba(231,76,60,0.85)"
            for v in cumulative
        ]
        fig_cf.add_trace(go.Bar(
            x=years, y=cumulative,
            name="Flujo acumulado",
            marker=dict(color=bar_colors, line=dict(width=0), cornerradius=4),
            hovertemplate="<b>Año %{x}</b><br>%{y:+,.0f} €<extra></extra>",
        ))
        fig_cf.add_hline(
            y=0,
            line_dash="dot",
            line_color="rgba(156,163,175,0.5)",
            line_width=1.5,
        )
        if payback_yr is not None and payback_yr <= lifetime_v:
            fig_cf.add_vline(
                x=payback_yr,
                line_dash="dash",
                line_color="#F59E0B",
                line_width=2,
                annotation_text=f"Payback: año {formato_num(payback_yr, 1)}",
                annotation_position="top right",
                annotation_font=dict(size=11, color="#92400e", family="Inter, sans-serif"),
                annotation_bgcolor="rgba(251,191,36,0.15)",
                annotation_bordercolor="rgba(251,191,36,0.4)",
                annotation_borderpad=4,
            )
        estilo_grafico(fig_cf, y_title="€ acumulados (valor actual)")
        fig_cf.update_xaxes(title_text="Año", dtick=5)
        fig_cf.update_yaxes(tickformat="+,.0f")
        fig_cf.update_layout(
            margin=dict(l=10, r=10, t=10, b=30),
            bargap=0.18,
            showlegend=False,
            plot_bgcolor="rgba(0,0,0,0)",
        )

        color_npv = "#18BC9C" if npv >= 0 else "#E74C3C"
        wf_labels = [
            f"−{formato_num(investment, 0)} €",
            f"+{formato_num(pv_savings, 0)} €",
            f"−{formato_num(pv_om, 0)} €",
            f"{'+'if npv>=0 else '−'}{formato_num(abs(npv), 0)} €",
        ]
        wf_bases   = [0, -investment, -investment + pv_savings, 0]
        wf_heights = [-investment, pv_savings, -pv_om, npv]
        wf_colors  = ["#E74C3C", "#18BC9C", "#F39C12", color_npv]
        wf_x       = ["Inversión<br>(CAPEX)", "VA Ahorros<br>(energía)",
                      "VA O&M<br>(mantenimiento)", "VAN neto"]

        fig_wf = go.Figure()
        fig_wf.add_trace(go.Bar(
            x=wf_x,
            y=wf_heights,
            base=wf_bases,
            marker=dict(color=wf_colors, line=dict(width=0), cornerradius=8),
            text=wf_labels,
            textposition="inside",
            insidetextanchor="middle",
            textfont=dict(size=14, family="Inter, sans-serif", color="white", weight=700),
            customdata=wf_heights,
            hovertemplate="<b>%{x}</b><br>%{customdata:+,.0f} €<extra></extra>",
        ))
        fig_wf.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            separators=",.",
            margin=dict(l=10, r=10, t=10, b=8),
            showlegend=False,
            bargap=0.25,
            xaxis=dict(
                tickfont=dict(size=13, color="#374151", family="Inter, sans-serif"),
                gridcolor="rgba(0,0,0,0)",
                zeroline=False,
                fixedrange=True,
            ),
            yaxis=dict(
                tickformat="+,.0f",
                ticksuffix=" €",
                tickfont=dict(size=11, color="#9CA3AF", family="Inter, sans-serif"),
                gridcolor="rgba(226,232,240,0.7)",
                zeroline=True,
                zerolinecolor="rgba(1,69,147,0.2)",
                zerolinewidth=1.5,
                automargin=True,
            ),
            hoverlabel=dict(
                bgcolor="#1e293b",
                bordercolor="#1e293b",
                font=dict(color="#f8fafc", size=13, family="Inter, sans-serif"),
            ),
        )

        fin_store = {
            "payback":        payback_yr,
            "npv":            npv,
            "irr":            irr,
            "annual_savings": annual_savings,
            "investment":     investment,
            "om_annual":      om_annual,
            "optimal_cap":    optimal_cap,
            "cumulative":     cumulative,
            "years":          years,
            "params": {
                "capex_kwh":    cost_kwp_v,
                "om_pct":       om_pct_v * 100,
                "inflation_pct": inflation_v * 100,
                "discount_pct": discount_v * 100,
                "lifetime":     lifetime_v,
            },
        }

        ref_rows_fin = df_m[df_m["Modelo"].isin(["Ex ante RD 244/2019", "Ex ante Rígido"])]
        cost_ref_fin = float(ref_rows_fin.iloc[0]["Coste (€)"]) if not ref_rows_fin.empty else None

        denom_pct    = cost_ref_fin if (cost_ref_fin and cost_ref_fin > 0) else (cost_horario if cost_horario > 0 else 1.0)

        sav_pct_horario = (cost_ref_fin - cost_horario) / denom_pct * 100 if cost_ref_fin else 0.0
        ann_pct_solo    = [sav_pct_horario] * lifetime_v

        sav_bat_annual = cost_horario - cost_bat_val

        years_c     = list(range(1, lifetime_v + 1))
        ann_pct_bat = []
        cum_bat_v   = -investment
        for yr in range(1, lifetime_v + 1):
            infl_factor = (1 + inflation_v) ** (yr - 1)
            disc_factor = (1 + discount_v) ** yr
            net_yr      = (sav_bat_annual - om_annual) * infl_factor
            cum_bat_v  += net_yr / disc_factor
            ann_pct_bat.append(cum_bat_v / yr / denom_pct * 100)

        graph_zero_yr = None
        for i in range(1, len(ann_pct_bat)):
            if ann_pct_bat[i - 1] < 0 <= ann_pct_bat[i]:
                t = -ann_pct_bat[i - 1] / (ann_pct_bat[i] - ann_pct_bat[i - 1])
                graph_zero_yr = years_c[i - 1] + t
                break

        y_ceil  = round(max(ann_pct_bat[-1], sav_pct_horario) + 3, 0)
        y_floor = max(ann_pct_bat[0] / 3.0, -60.0)

        fig_comp = go.Figure()

        fig_comp.add_hline(y=0, line_dash="dot",
                           line_color="rgba(100,116,139,0.45)", line_width=1.5)
        fig_comp.add_hline(y=sav_pct_horario, line_dash="dot",
                           line_color="rgba(99,102,241,0.4)", line_width=1.2)

        fig_comp.add_trace(go.Scatter(
            x=years_c, y=ann_pct_solo,
            name="Dinámico Horario",
            mode="lines",
            line=dict(color="#6366F1", width=2, dash="dash"),
            hovertemplate="<b>Año %{x}</b><br>Ahorro: <b>%{y:.2f} %</b><extra></extra>",
        ))
        fig_comp.add_trace(go.Scatter(
            x=years_c, y=ann_pct_bat,
            name="Dinámico con batería",
            mode="lines",
            line=dict(color="#18BC9C", width=2.5),
            hovertemplate="<b>Año %{x}</b><br>Ahorro anualizado: <b>%{y:.2f} %</b><extra></extra>",
        ))

        if graph_zero_yr is not None:
            fig_comp.add_vline(
                x=graph_zero_yr,
                line_dash="dash",
                line_color="#F59E0B",
                line_width=2,
                annotation_text=f"Payback: año {formato_num(graph_zero_yr, 1)}",
                annotation_position="top right",
                annotation_font=dict(size=11, color="#92400e", family="Inter, sans-serif"),
                annotation_bgcolor="rgba(251,191,36,0.15)",
                annotation_bordercolor="rgba(251,191,36,0.4)",
                annotation_borderpad=4,
            )

        fig_comp.add_annotation(
            x=years_c[-1], y=ann_pct_solo[-1],
            text=f"<b>{formato_num(ann_pct_solo[-1], 2)} %</b>",
            showarrow=False, xanchor="left", yanchor="middle", xshift=8,
            font=dict(size=12, color="#6366F1", family="Inter, sans-serif"),
        )
        fig_comp.add_annotation(
            x=years_c[-1], y=ann_pct_bat[-1],
            text=f"<b>{formato_num(ann_pct_bat[-1], 2)} %</b>",
            showarrow=False, xanchor="left", yanchor="middle", xshift=8,
            font=dict(size=12, color="#18BC9C", family="Inter, sans-serif"),
        )
        estilo_grafico(fig_comp, y_title="Ahorro anualizado descontado (%)")
        fig_comp.update_xaxes(title_text="Año", dtick=5)
        fig_comp.update_yaxes(ticksuffix=" %", range=[y_floor, y_ceil])
        fig_comp.update_layout(
            margin=dict(l=10, r=70, t=10, b=30),
            showlegend=True,
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02,
                xanchor="right", x=1,
                font=dict(size=11, family="Inter, sans-serif"),
                bgcolor="rgba(0,0,0,0)",
            ),
            plot_bgcolor="rgba(0,0,0,0)",
        )

        return (kpi_pb, kpi_npv, kpi_irr, kpi_sav,
                fig_cf, fig_wf, hidden_style, cap_display, fin_store,
                fig_comp, capex_display, lifetime_display)

    def render_bat_optimal(data):
        _no = grafico_vacio("Ejecuta el modelo para ver la capacidad óptima.")
        _empty_kpi = html.Div("—", style={"fontSize": "28px", "fontWeight": "900",
                                           "color": "var(--text-muted)"})
        if not data or "series" not in data or not data["series"]:
            return _no, _empty_kpi, {}

        series = data.get("series", {})
        first_key = next(iter(series))
        ts_base = get_serie(series, first_key)
        if ts_base.empty:
            return _no, _empty_kpi, {}

        pv_col  = primera_col(ts_base.columns, ["pv_kWh", "G"])
        dem_col = primera_col(ts_base.columns, ["demand_kWh", "D_total"])
        buy_col = primera_col(ts_base.columns, ["p_buy"])
        sel_col = primera_col(ts_base.columns, ["p_sell"])
        if not (pv_col and dem_col):
            return _no, _empty_kpi, {}

        pv  = ts_base[pv_col].fillna(0).values
        dem = ts_base[dem_col].fillna(0).values
        p_buy_v = ts_base[buy_col].fillna(0.15).values if buy_col else [0.15] * len(pv)
        p_sel_v = ts_base[sel_col].fillna(0.06).values if sel_col else [0.06] * len(pv)

        def _greedy_cost(cap_kwh):
            if cap_kwh <= 0:
                return sum(
                    max(dem[t] - pv[t], 0) * p_buy_v[t]
                    - max(pv[t] - dem[t], 0) * p_sel_v[t]
                    for t in range(len(pv))
                )
            pow_kw = cap_kwh / 2.0  # C/2 rate
            soc = cap_kwh * 0.5
            cost = 0.0
            for t in range(len(pv)):
                surplus = max(pv[t] - dem[t], 0.0)
                deficit = max(dem[t] - pv[t], 0.0)
                charge = min(surplus, cap_kwh - soc, pow_kw)
                soc = min(soc + charge, cap_kwh)
                surplus -= charge
                discharge = min(deficit, soc, pow_kw)
                soc = max(soc - discharge, 0.0)
                deficit -= discharge
                cost += deficit * p_buy_v[t] - surplus * p_sel_v[t]
            return cost

        base_cost = _greedy_cost(0)

        daily_surplus = sum(max(pv[t] - dem[t], 0) for t in range(len(pv))) / max(len(pv) / 24, 1)
        max_cap = max(daily_surplus * 4, 10.0)
        n_steps = 40
        caps = [max_cap * i / n_steps for i in range(1, n_steps + 1)]
        savings = [base_cost - _greedy_cost(c) for c in caps]

        marginals = [savings[i] - savings[i - 1] for i in range(1, len(savings))]
        max_marg = max(marginals) if marginals else 1.0
        optimal_idx = next(
            (i + 1 for i, m in enumerate(marginals) if max_marg > 0 and m < 0.10 * max_marg),
            len(caps) - 1,
        )
        optimal_cap = caps[optimal_idx]
        optimal_sav = savings[optimal_idx]

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=caps, y=savings,
            mode="lines",
            fill="tozeroy",
            fillcolor="rgba(255,184,28,0.07)",
            line=dict(color="rgba(0,0,0,0)", width=0),
            showlegend=False, hoverinfo="skip",
        ))
        caps_left  = [c for c in caps if c <= optimal_cap]
        saves_left = savings[:len(caps_left)]
        fig.add_trace(go.Scatter(
            x=caps_left, y=saves_left,
            mode="lines",
            fill="tozeroy",
            fillcolor="rgba(255,184,28,0.14)",
            line=dict(color="rgba(0,0,0,0)", width=0),
            showlegend=False, hoverinfo="skip",
        ))
        fig.add_trace(go.Scatter(
            x=caps, y=savings,
            mode="lines",
            name="Ahorro adicional (€/año)",
            line=dict(color="#FFB81C", width=2.5),
            hovertemplate="<b>%{x:.1f} kWh</b><br>Ahorro: <b>%{y:,.0f} €</b><extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=[optimal_cap], y=[optimal_sav],
            mode="markers",
            name=f"Óptimo: {optimal_cap:.0f} kWh",
            marker=dict(size=13, color="#FFB81C", symbol="circle",
                        line=dict(color="#fff", width=2.5)),
            hovertemplate=(
                f"<b>Capacidad óptima: {optimal_cap:.0f} kWh</b><br>"
                f"Ahorro: <b>{formato_num(optimal_sav, 0)} €/año</b><extra></extra>"
            ),
        ))
        fig.add_vline(
            x=optimal_cap,
            line_dash="dot", line_color="rgba(255,184,28,0.5)", line_width=1.5,
            annotation_text=f"  Óptimo: {optimal_cap:.0f} kWh",
            annotation_position="top right",
            annotation_font=dict(size=11, color="#7a5800"),
        )
        estilo_grafico(fig, y_title="Ahorro adicional (€/año)")
        fig.update_xaxes(title="Capacidad batería (kWh)")
        fig.update_layout(
            margin=dict(l=10, r=10, t=16, b=36),
            legend=dict(orientation="h", x=0, y=1.06, yanchor="bottom",
                        bgcolor="rgba(0,0,0,0)", font=dict(size=11)),
        )

        kpi_el = html.Div([
            html.Div([
                html.Span(f"{optimal_cap:.0f}", style={
                    "fontSize": "36px", "fontWeight": "900",
                    "color": "#18BC9C", "lineHeight": "1.1",
                    "letterSpacing": "-1px",
                }),
                html.Span(" kWh", style={
                    "fontSize": "16px", "color": "#18BC9C",
                    "fontWeight": "700", "marginLeft": "2px",
                }),
            ]),
            html.Div("Capacidad óptima estimada", style={
                "fontSize": "10px", "fontWeight": "700",
                "color": "var(--text-muted)", "textTransform": "uppercase",
                "letterSpacing": "0.5px", "marginTop": "1px",
            }),

            html.Div([
                html.Span(f"{formato_num(optimal_sav, 0)} €/año", style={
                    "fontWeight": "800", "fontSize": "14px", "color": "var(--text)",
                }),
                html.Span(" ahorro estimado", style={
                    "fontSize": "11px", "color": "var(--text-muted)", "marginLeft": "4px",
                }),
            ], style={"display": "flex", "alignItems": "center", "marginTop": "10px"}),
        ], style={"padding": "2px 0"})
        return fig, kpi_el, {"optimal_cap": optimal_cap, "optimal_sav": optimal_sav}

    def render_scenarios(n, data, pv_range):
        _no = grafico_vacio("Ejecuta el análisis de escenarios.")
        empty_style  = {"display": "flex"}
        hidden_style = {"display": "none"}

        if not data or "series" not in data or not data["series"]:
            return _no, _no, _no, "Sin datos base. Ejecuta primero el modelo.", empty_style

        series = data.get("series", {})
        models = data.get("models", [])

        first_key = next(iter(series))
        ts_base   = get_serie(series, first_key)
        if ts_base.empty:
            return _no, _no, _no, "No se encontraron series temporales.", empty_style

        pv_col  = primera_col(ts_base.columns, ["pv_kWh", "G"])
        dem_col = primera_col(ts_base.columns, ["demand_kWh", "D_total"])
        buy_col = primera_col(ts_base.columns, ["p_buy"])
        sel_col = primera_col(ts_base.columns, ["p_sell"])
        self_col= primera_col(ts_base.columns, ["self_prop", "self_ex_ante"])
        imp_col = primera_col(ts_base.columns, ["imp_prop",  "imp_ex_ante"])
        exp_col = primera_col(ts_base.columns, ["exp_prop",  "exp_ex_ante"])

        if not (pv_col and dem_col):
            return _no, _no, _no, "Sin columnas FV o demanda.", empty_style

        pv_base    = ts_base[pv_col].fillna(0).values
        dem_base   = ts_base[dem_col].fillna(0).values
        pbuy_base  = ts_base[buy_col].fillna(0.15).values  if buy_col  else None
        psel_base  = ts_base[sel_col].fillna(0.06).values  if sel_col  else None
        self_base  = ts_base[self_col].fillna(0).values    if self_col else None
        imp_base   = ts_base[imp_col].fillna(0).values     if imp_col  else None

        pv_range  = pv_range or [0.5, 3.0]
        n_points  = 12
        mults     = [pv_range[0] + i * (pv_range[1] - pv_range[0]) / max(n_points - 1, 1)
                     for i in range(n_points)]

        pv_peak_kw = float(pv_base.max()) if pv_base.max() > 0 else 1.0
        base_kwp   = pv_peak_kw

        df_m = pd.DataFrame(models)
        df_m["Coste (€)"] = pd.to_numeric(df_m["Coste (€)"], errors="coerce")
        df_m = df_m.dropna(subset=["Coste (€)"])
        if df_m.empty:
            return _no, _no, _no, "Sin datos de coste.", empty_style

        best_cost_base = float(df_m["Coste (€)"].min())
        ref_rows = df_m[df_m["Modelo"].str.contains("RD 244|ex ante|Rígido", case=False, na=False)]
        ref_cost_base  = float(ref_rows.iloc[0]["Coste (€)"]) if not ref_rows.empty else best_cost_base

        T         = len(pv_base)
        dem_total = float(dem_base.sum())
        g_total   = float(pv_base.sum())
        self_tot  = float(self_base.sum()) if self_base is not None else g_total * 0.5


        if g_total > 0 and dem_total > 0 and self_tot > 0:
            ratio_base = self_tot / dem_total  # fracción de demanda cubierta a k=1
            c_factor = -math.log(max(1 - ratio_base, 0.001)) * dem_total / g_total
        else:
            c_factor = 1.0

        results_scen = []
        for k in mults:
            self_pct_dyn  = (1 - math.exp(-k * g_total / dem_total * c_factor)) if dem_total > 0 else 0
            self_pct_dyn  = min(self_pct_dyn, 1.0)
            self_pct_ex   = self_pct_dyn * 0.92  # ~8% menos por ineficiencia ex ante (empírico)

            self_kwh_dyn  = self_pct_dyn * dem_total
            self_kwh_ex   = self_pct_ex  * dem_total
            imp_kwh_dyn   = dem_total - self_kwh_dyn
            exp_kwh_dyn   = max(k * g_total - self_kwh_dyn, 0)
            exp_kwh_ex    = max(k * g_total - self_kwh_ex,  0)

            pbuy_m  = float(pbuy_base.mean()) if pbuy_base is not None else 0.15
            psel_m  = float(psel_base.mean()) if psel_base is not None else 0.06
            cost_dyn = pbuy_m * imp_kwh_dyn - psel_m * exp_kwh_dyn
            cost_ex  = pbuy_m * (dem_total - self_kwh_ex) - psel_m * exp_kwh_ex
            saving   = cost_ex - cost_dyn

            results_scen.append({
                "mult": k, "kwp": base_kwp * k,
                "self_pct_dyn": self_pct_dyn * 100,
                "self_pct_ex":  self_pct_ex  * 100,
                "saving": saving,
                "exp_kwh_dyn": exp_kwh_dyn,
                "exp_kwh_ex":  exp_kwh_ex,
            })

        x_kwp    = [r["kwp"]          for r in results_scen]
        save_eur = [r["saving"]        for r in results_scen]
        self_dyn = [r["self_pct_dyn"]  for r in results_scen]
        self_ex  = [r["self_pct_ex"]   for r in results_scen]
        exp_dyn  = [r["exp_kwh_dyn"]   for r in results_scen]
        exp_ex   = [r["exp_kwh_ex"]    for r in results_scen]

        base_idx = min(range(len(mults)), key=lambda i: abs(mults[i] - 1.0))
        x_base   = x_kwp[base_idx]

        _COMMON_LAYOUT = dict(
            margin=dict(l=10, r=10, t=12, b=36),
            legend=dict(orientation="h", x=0, y=1.08, yanchor="bottom",
                        xanchor="left", bgcolor="rgba(0,0,0,0)", font=dict(size=11)),
        )

        fig_sav = go.Figure()
        fig_sav.add_trace(go.Scatter(
            x=x_kwp, y=save_eur,
            mode="lines",
            fill="tozeroy",
            fillcolor="rgba(24,188,156,0.12)",
            line=dict(color=COLOR_DYNAMIC, width=0),
            showlegend=False, hoverinfo="skip",
        ))
        fig_sav.add_trace(go.Scatter(
            x=x_kwp, y=save_eur,
            mode="lines+markers",
            name="Ahorro Dinámico vs Ex ante",
            line=dict(color=COLOR_DYNAMIC, width=2.5),
            marker=dict(size=6, color=COLOR_DYNAMIC, line=dict(color="#fff", width=1.5)),
            hovertemplate="<b>%{x:.1f} kWp</b><br>Ahorro: %{y:,.0f} €<extra></extra>",
        ))
        fig_sav.add_vline(
            x=x_base, line_dash="dot", line_color="#F39C12", line_width=1.8,
            annotation_text="Instalación actual",
            annotation_position="top right",
            annotation_font=dict(size=10, color="#F39C12"),
        )
        estilo_grafico(fig_sav, y_title="Ahorro (€/año)")
        fig_sav.update_xaxes(title="Potencia FV instalada (kWp)")
        fig_sav.update_layout(**_COMMON_LAYOUT)

        fig_self = go.Figure()
        fig_self.add_trace(go.Scatter(
            x=x_kwp + x_kwp[::-1],
            y=self_dyn + self_ex[::-1],
            fill="toself",
            fillcolor="rgba(24,188,156,0.10)",
            line=dict(color="rgba(0,0,0,0)"),
            name="Ventaja dinámica",
            hoverinfo="skip",
            showlegend=True,
        ))
        fig_self.add_trace(go.Scatter(
            x=x_kwp, y=self_dyn,
            mode="lines+markers",
            name="Dinámico",
            line=dict(color=COLOR_DYNAMIC, width=2.5),
            marker=dict(size=6, color=COLOR_DYNAMIC, line=dict(color="#fff", width=1.5)),
            hovertemplate="<b>%{x:.1f} kWp</b><br>Autoconsumo: %{y:.1f}%<extra></extra>",
        ))
        fig_self.add_trace(go.Scatter(
            x=x_kwp, y=self_ex,
            mode="lines+markers",
            name="Ex ante RD 244",
            line=dict(color=COLOR_EX_ANTE, width=2, dash="dash"),
            marker=dict(size=5, color=COLOR_EX_ANTE),
            hovertemplate="<b>%{x:.1f} kWp</b><br>Autoconsumo: %{y:.1f}%<extra></extra>",
        ))
        fig_self.add_vline(
            x=x_base, line_dash="dot", line_color="#F39C12", line_width=1.8,
            annotation_text="Actual",
            annotation_position="top right",
            annotation_font=dict(size=10, color="#F39C12"),
        )
        estilo_grafico(fig_self, y_title="Tasa de autoconsumo (%)")
        fig_self.update_xaxes(title="Potencia FV instalada (kWp)")
        fig_self.update_yaxes(range=[0, 105])
        fig_self.update_layout(**_COMMON_LAYOUT)

        fig_exp = go.Figure()
        fig_exp.add_trace(go.Scatter(
            x=x_kwp + x_kwp[::-1],
            y=exp_dyn + exp_ex[::-1],
            fill="toself",
            fillcolor="rgba(24,188,156,0.10)",
            line=dict(color="rgba(0,0,0,0)"),
            name="Ventaja dinámica",
            hoverinfo="skip",
            showlegend=True,
        ))
        fig_exp.add_trace(go.Scatter(
            x=x_kwp, y=exp_dyn,
            mode="lines+markers",
            name="Dinámico",
            line=dict(color=COLOR_DYNAMIC, width=2.5),
            marker=dict(size=6, color=COLOR_DYNAMIC, line=dict(color="#fff", width=1.5)),
            hovertemplate="<b>%{x:.1f} kWp</b><br>Excedente: %{y:,.0f} kWh<extra></extra>",
        ))
        fig_exp.add_trace(go.Scatter(
            x=x_kwp, y=exp_ex,
            mode="lines+markers",
            name="Ex ante",
            line=dict(color=COLOR_EX_ANTE, width=2, dash="dash"),
            marker=dict(size=5, color=COLOR_EX_ANTE),
            hovertemplate="<b>%{x:.1f} kWp</b><br>Excedente: %{y:,.0f} kWh<extra></extra>",
        ))
        fig_exp.add_vline(
            x=x_base, line_dash="dot", line_color="#F39C12", line_width=1.8,
            annotation_text="Actual",
            annotation_position="top right",
            annotation_font=dict(size=10, color="#F39C12"),
        )
        estilo_grafico(fig_exp, y_title="Excedente FV (kWh/año)")
        fig_exp.update_xaxes(title="Potencia FV instalada (kWp)")
        fig_exp.update_layout(**_COMMON_LAYOUT)

        status = ""
        return fig_sav, fig_self, fig_exp, status, hidden_style

    @app.callback(
        Output("download-excel", "data"),
        Input("export-excel-btn", "n_clicks"),
        State("results-store",         "data"),
        State("run-tag-store",         "data"),
        State("export-sw-comparativa", "value"),
        State("export-sw-series",      "value"),
        State("export-sw-costes",      "value"),
        State("export-sw-alpha",       "value"),
        State("export-sw-bateria_fin", "value"),
        State("export-sw-bateria_soc", "value"),
        State("fin-results-store",     "data"),
        State("battery-enabled",       "value"),
        prevent_initial_call=True,
    )
    def export_excel(_, data, run_tag, sw_comp, sw_ser, sw_cos, sw_alp,
                     sw_bat_fin, sw_bat_soc, fin_store, battery_enabled):
        if not data or "models" not in data:
            return no_update
        bat_active = bool(battery_enabled and "enabled" in (battery_enabled or []))
        has_bat_model = any(
            m.get("Tipo") == "bateria" and m.get("Coste (€)") is not None
            for m in (data.get("models") or [])
        )
        sections = []
        if "comparativa" in (sw_comp    or []): sections.append("comparativa")
        if "series"      in (sw_ser     or []): sections.append("series")
        if "costes"      in (sw_cos     or []): sections.append("costes")
        if "alpha"       in (sw_alp     or []): sections.append("alpha")
        if bat_active and has_bat_model and "bateria_fin" in (sw_bat_fin or []) and fin_store:
            sections.append("bateria_fin")
        if bat_active and has_bat_model and "bateria_soc" in (sw_bat_soc or []):
            sections.append("bateria_soc")
        if not sections:
            return no_update
        tag    = run_tag or "run"
        xbytes = crear_excel(data, tag, sections, fin_store=fin_store)
        return dict(
            content=base64.b64encode(xbytes).decode(),
            filename=f"{tag}_resultados.xlsx",
            type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            base64=True,
        )

