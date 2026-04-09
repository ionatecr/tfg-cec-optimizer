import base64
import io
import logging
import pandas as pd
from dataclasses import dataclass

from model.parameters import load_config


@dataclass(frozen=True)
class PreparedInputs:
    df: pd.DataFrame
    users: list[str]
    time_col: str = "Time"
    pv_col: str = "pv_kWh"
    buy_col: str = "p_buy"
    sell_col: str = "p_sell"
    cons_prefix: str = "cons_"

_log = logging.getLogger("TFG")


def parse_upload(contents: str) -> pd.DataFrame:
    cfg = load_config()
    _, content_string = contents.split(",")
    decoded = base64.b64decode(content_string)

    text = None
    for enc in [cfg.io.csv.encoding, cfg.io.csv.fallback_encoding, "utf-8"]:
        try:
            text = decoded.decode(enc, errors="strict")
            break
        except (UnicodeDecodeError, LookupError):
            pass
    if text is None:
        text = decoded.decode("utf-8", errors="replace")

    data = io.StringIO(text)
    df = pd.read_csv(data, sep=cfg.io.csv.sep_primary)
    if df.shape[1] == 1:
        data.seek(0)
        df = pd.read_csv(data, sep=cfg.io.csv.sep_fallback)

    columnas_limpias = []
    for c in df.columns:
        columnas_limpias.append(c.strip().lstrip("\ufeff"))
    df.columns = columnas_limpias
    return df


def buscar_col_tiempo(df: pd.DataFrame, candidates: list[str]) -> str:
    for c in candidates:
        if c in df.columns:
            return c
    raise ValueError(
        f"No se encontró columna de tiempo. Se esperaba una de: {candidates}. "
        f"Columnas disponibles: {list(df.columns)}"
    )


def normalizar_tiempo(df: pd.DataFrame, time_col: str, cfg) -> pd.DataFrame:
    df = df.copy()
    s = pd.to_datetime(df[time_col], dayfirst=cfg.io.time.dayfirst, errors="coerce", utc=cfg.io.time.utc)
    if cfg.io.time.utc:
        s = s.dt.tz_convert(None)
    df["Time"] = s

    n_nat = int(df["Time"].isna().sum())
    if n_nat > 0:
        _log.warning(f"normalizar_tiempo: {n_nat} filas con timestamp inválido serán eliminadas")

    if cfg.io.time.floor:
        df["Time"] = df["Time"].dt.floor(cfg.io.time.floor)

    df = df.dropna(subset=["Time"])
    df = df.sort_values("Time").reset_index(drop=True)
    return df.drop(columns=[time_col], errors="ignore") if time_col != "Time" else df


def quitar_duplicados(df, value_cols, how="sum"):
    if not df["Time"].duplicated().any():
        return df
    agg = {}
    for c in value_cols:
        if c in df.columns:
            agg[c] = how
    df = df.groupby("Time", as_index=False).agg(agg)
    df = df.sort_values("Time").reset_index(drop=True)
    return df


def prepare_inputs(df_c, df_pv, df_buy, df_sell):
    cfg = load_config()
    cols = cfg.io.columns
    time_candidates = cols.time

    # perfiles de consumo
    tc = buscar_col_tiempo(df_c, time_candidates)
    df_c = normalizar_tiempo(df_c, tc, cfg)
    prefix = cols.consumption_prefix

    users = []
    for c in df_c.columns:
        if c.startswith(prefix):
            users.append(c)

    if not users:
        raise ValueError(
            f"No se encontraron columnas de consumo con prefijo '{prefix}'. "
            f"Columnas disponibles: {list(df_c.columns)}"
        )
    
    _log.info(f"  [2.1] consumos: {len(df_c)} filas | {len(users)} usuarios → {users}")

    # pv
    tpv = buscar_col_tiempo(df_pv, time_candidates)
    df_pv = normalizar_tiempo(df_pv, tpv, cfg)
    if cols.pv not in df_pv.columns:
        raise ValueError(
            f"No se encontró columna PV '{cols.pv}'. "
            f"Columnas disponibles: {list(df_pv.columns)}"
        )
    df_pv = df_pv[["Time", cols.pv]].rename(columns={cols.pv: "pv_kWh"})
    _log.info(f"  [2.2] pv: {len(df_pv)} filas")

    # precio compra
    tbuy = buscar_col_tiempo(df_buy, time_candidates)
    df_buy = normalizar_tiempo(df_buy, tbuy, cfg)
    if cols.buy not in df_buy.columns:
        raise ValueError(
            f"No se encontró columna de compra '{cols.buy}'. "
            f"Columnas disponibles: {list(df_buy.columns)}"
        )
    df_buy = df_buy[["Time", cols.buy]].rename(columns={cols.buy: "p_buy"})
    _log.info(f"  [2.3] buy: {len(df_buy)} filas")

    # precio venta
    tsell = buscar_col_tiempo(df_sell, time_candidates)
    df_sell = normalizar_tiempo(df_sell, tsell, cfg)
    if cols.sell not in df_sell.columns:
        raise ValueError(
            f"No se encontró columna de venta '{cols.sell}'. "
            f"Columnas disponibles: {list(df_sell.columns)}"
        )
    df_sell = df_sell[["Time", cols.sell]].rename(columns={cols.sell: "p_sell"})
    _log.info(f"  [2.4] sell: {len(df_sell)} filas")

    df_c    = quitar_duplicados(df_c,    users,       how="sum")
    df_pv   = quitar_duplicados(df_pv,   ["pv_kWh"],  how="sum")
    df_buy  = quitar_duplicados(df_buy,  ["p_buy"],   how="mean")
    df_sell = quitar_duplicados(df_sell, ["p_sell"],  how="mean")

    n_cons = len(df_c)
    df = df_c.merge(df_pv, on="Time", how="inner")
    if len(df) < n_cons * 0.9:
        _log.warning(f"  merge perdió >{int((1 - len(df)/n_cons)*100)}% de filas (revisar solapamiento)")

    df = df.merge(df_buy,  on="Time", how="left")
    df = df.merge(df_sell, on="Time", how="left")
    df = df.sort_values("Time").reset_index(drop=True)

    if len(df) < cfg.validation.min_rows_after_merge:
        raise ValueError(
            f"Tras el merge hay pocas filas ({len(df)}). "
            f"Umbral mínimo: {cfg.validation.min_rows_after_merge}. "
            "Probable problema de timestamps no coincidentes entre Consumo y FV."
        )

    df["pv_kWh"] = pd.to_numeric(df["pv_kWh"], errors="coerce").fillna(0.0)
    df["p_buy"]  = pd.to_numeric(df["p_buy"],  errors="coerce").ffill().bfill()
    df["p_sell"] = pd.to_numeric(df["p_sell"], errors="coerce").ffill().bfill()
    for u in users:
        df[u] = pd.to_numeric(df[u], errors="coerce").fillna(0.0)

    df = df.dropna(subset=["Time"]).sort_values("Time").reset_index(drop=True)

    # Comprobar huecos temporales
    if len(df) >= 2:
        diffs = df["Time"].diff().dropna()
        dt_mode = diffs.mode().iloc[0]
        gaps = diffs[diffs > 2 * dt_mode]
        if not gaps.empty:
            t_min, t_max = df["Time"].min(), df["Time"].max()
            full_idx = pd.date_range(start=t_min, end=t_max, freq=dt_mode)
            n_before = len(df)
            df = (df.set_index("Time")
                    .reindex(full_idx)
                    .ffill()
                    .bfill()
                    .reset_index()
                    .rename(columns={"index": "Time"}))
            _log.info(f"  [2.5] huecos temporales: {len(gaps)} rellenados ({n_before}→{len(df)} filas)")

    _log.info(f"  [2.6] merge final: {len(df)} filas | rango={df['Time'].min().date()} – {df['Time'].max().date()}")

    return PreparedInputs(df=df, users=users)
