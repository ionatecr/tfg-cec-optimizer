import base64
import io
import logging
import pandas as pd
import re
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
    _log.debug(f"parse_upload: {len(decoded)} bytes recibidos")

    text = None
    enc_used = None
    for enc in [cfg.io.csv.encoding, cfg.io.csv.fallback_encoding, "utf-8"]:
        try:
            text = decoded.decode(enc, errors="strict")
            enc_used = enc
            break
        except (UnicodeDecodeError, LookupError):
            _log.debug(f"parse_upload: encoding '{enc}' falló, probando siguiente")
    if text is None:
        text = decoded.decode("utf-8", errors="replace")
        enc_used = "utf-8 (replace)"
    _log.debug(f"parse_upload: decodificado con '{enc_used}'")

    data = io.StringIO(text)
    df = pd.read_csv(data, sep=cfg.io.csv.sep_primary)
    if df.shape[1] == 1:
        data.seek(0)
        df = pd.read_csv(data, sep=cfg.io.csv.sep_fallback)
        _log.debug(f"parse_upload: separador primario dio 1 columna → fallback, shape={df.shape}")
    else:
        _log.debug(f"parse_upload: separador primario OK, shape={df.shape}")

    df.columns = [c.strip().lstrip("\ufeff") for c in df.columns]
    _log.debug(f"parse_upload: columnas={list(df.columns)}")
    return df


def find_time_col(df: pd.DataFrame, cfg=None) -> str:
    cfg = cfg or load_config()
    cols = list(df.columns)
    low = {c: str(c).strip().lower() for c in cols}

    patterns = cfg.io.detect.time_patterns
    for pat in patterns:
        rgx = re.compile(pat, re.IGNORECASE)
        for c in cols:
            if rgx.search(low[c]):
                _log.debug(f"find_time_col: '{c}' identificada por patrón '{pat}'")
                return c

    _log.debug("find_time_col: ningún patrón coincidió, usando heurística de parseo")
    best_col = None
    best_score = -1.0
    scores = {}
    for c in cols:
        s = df[c]
        if s.dtype.kind in ("i", "u", "f"):
            continue
        parsed = pd.to_datetime(s, errors="coerce", utc=cfg.io.time.utc)
        score = parsed.notna().mean()
        scores[c] = round(float(score), 3)
        if score > best_score:
            best_score = score
            best_col = c

    _log.debug(f"find_time_col: scores heurística = {scores}")

    if best_col is None or best_score < 0.5:
        _log.error(f"find_time_col: ninguna columna supera threshold 0.5. Columnas: {cols}")
        raise ValueError("No se pudo detectar la columna de tiempo (time).")

    _log.debug(f"find_time_col: seleccionada '{best_col}' con score={best_score:.2f}")
    return best_col


def norm_time(df: pd.DataFrame, time_col: str, cfg=None) -> pd.DataFrame:
    cfg = cfg or load_config()
    df = df.copy()
    _log.debug(f"norm_time: parseando '{time_col}', dayfirst={cfg.io.time.dayfirst}, utc={cfg.io.time.utc}")

    s = pd.to_datetime(
        df[time_col],
        dayfirst=cfg.io.time.dayfirst,
        errors="coerce",
        utc=cfg.io.time.utc
    )
    if cfg.io.time.utc:
        s = s.dt.tz_convert(None)
    df["Time"] = s

    n_nat = int(df["Time"].isna().sum())
    if n_nat > 0:
        _log.warning(f"norm_time: {n_nat} filas con timestamp inválido serán eliminadas")

    if cfg.io.time.floor:
        df["Time"] = df["Time"].dt.floor(cfg.io.time.floor)
        _log.debug(f"norm_time: timestamps truncados a '{cfg.io.time.floor}'")

    df = df.dropna(subset=["Time"])
    df = df.sort_values("Time").reset_index(drop=True)

    if not df.empty:
        _log.debug(f"norm_time: {len(df)} filas, rango={df['Time'].min()} – {df['Time'].max()}")

    return df.drop(columns=[time_col], errors="ignore") if time_col != "Time" else df


def pick_value_col(df: pd.DataFrame, preferred: list[str]) -> str | None:
    for c in preferred:
        if c in df.columns:
            _log.debug(f"pick_value_col: columna preferida '{c}' encontrada")
            return c
    non_time = [c for c in df.columns if c != "Time"]
    if not non_time:
        return None
    _log.debug(f"pick_value_col: ninguna preferida hallada, usando primera disponible '{non_time[0]}'")
    return non_time[0]


def _collapse_to_unique_time(df: pd.DataFrame, value_cols: list[str], how: str = "sum") -> pd.DataFrame:
    if "Time" not in df.columns:
        return df
    df = df.copy()
    for c in value_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if df["Time"].duplicated().any():
        n_dup = int(df["Time"].duplicated().sum())
        _log.debug(f"_collapse_to_unique_time: {n_dup} timestamps duplicados → agregando por '{how}'")
        if how == "mean":
            agg = {c: "mean" for c in value_cols if c in df.columns}
        else:
            agg = {c: "sum" for c in value_cols if c in df.columns}
        df = df.groupby("Time", as_index=False).agg(agg)
    else:
        _log.debug("_collapse_to_unique_time: sin duplicados")
    return df.sort_values("Time").reset_index(drop=True)


def prepare_inputs(df_c, df_pv, df_buy, df_sell):
    cfg = load_config()

    tc = find_time_col(df_c, cfg)
    df_c = norm_time(df_c, tc, cfg)
    _log.info(f"  [2.1] consumos: {len(df_c)} filas | time_col='{tc}'")

    tpv = find_time_col(df_pv, cfg)
    df_pv = norm_time(df_pv, tpv, cfg)
    pv_col = pick_value_col(df_pv, cfg.io.detect.pv_preferred_cols)
    if pv_col is None:
        raise ValueError("No encuentro columna de generación FV en el archivo PV.")
    _log.info(f"  [2.2] pv: columna='{pv_col}' | {len(df_pv)} filas")
    df_pv = df_pv.rename(columns={pv_col: "pv_kWh"})[["Time", "pv_kWh"]]

    tbuy = find_time_col(df_buy, cfg)
    df_buy = norm_time(df_buy, tbuy, cfg)
    buy_col = pick_value_col(df_buy, cfg.io.detect.buy_preferred_cols)
    if buy_col is None:
        raise ValueError("No encuentro columna de precio de compra.")
    _log.info(f"  [2.3] buy: columna='{buy_col}' | {len(df_buy)} filas")
    df_buy = df_buy.rename(columns={buy_col: "p_buy"})[["Time", "p_buy"]]

    tsell = find_time_col(df_sell, cfg)
    df_sell = norm_time(df_sell, tsell, cfg)
    sell_col = pick_value_col(df_sell, cfg.io.detect.sell_preferred_cols)
    if sell_col is None:
        raise ValueError("No encuentro columna de precio de venta.")
    _log.info(f"  [2.4] sell: columna='{sell_col}' | {len(df_sell)} filas")
    df_sell = df_sell.rename(columns={sell_col: "p_sell"})[["Time", "p_sell"]]

    prefixes = tuple(cfg.io.detect.consumption_prefixes)
    users = [c for c in df_c.columns if c.startswith(prefixes)]
    if not users:
        exclude = {"Time", "pv_kWh", "p_buy", "p_sell", "Electricity.Timestep", "timestep", "Timestep"}
        users_raw = [c for c in df_c.columns if c not in exclude]
        rename_map = {u: f"cons_{i+1}" for i, u in enumerate(users_raw)}
        df_c = df_c.rename(columns=rename_map)
        users = list(rename_map.values())
        _log.info(f"  [2.5] usuarios: renombrado automático → {users}")
    else:
        _log.info(f"  [2.5] usuarios: {len(users)} detectados → {users}")

    df_c    = _collapse_to_unique_time(df_c,    users,       how="sum")
    df_pv   = _collapse_to_unique_time(df_pv,   ["pv_kWh"],  how="sum")
    df_buy  = _collapse_to_unique_time(df_buy,  ["p_buy"],   how="mean")
    df_sell = _collapse_to_unique_time(df_sell, ["p_sell"],  how="mean")

    n_cons = len(df_c)
    n_pv   = len(df_pv)
    df = df_c.merge(df_pv, on="Time", how="inner")
    if len(df) < n_cons * 0.9:
        _log.warning(f"  merge perdió >{int((1 - len(df)/n_cons)*100)}% de filas — revisar solapamiento temporal")

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
            _log.info(f"  [2.6b] huecos temporales: {len(gaps)} rellenados por ffill ({n_before}→{len(df)} filas)")

    _log.info(f"  [2.6] merge: {len(df)} filas | rango={df['Time'].min().date()} – {df['Time'].max().date()}")
    _log.debug(f"  pv_kWh : total={df['pv_kWh'].sum():.1f} kWh, NaN={df['pv_kWh'].isna().sum()}")
    _log.debug(f"  p_buy  : media={df['p_buy'].mean():.4f} €/kWh, NaN={df['p_buy'].isna().sum()}")
    _log.debug(f"  p_sell : media={df['p_sell'].mean():.4f} €/kWh, NaN={df['p_sell'].isna().sum()}")
    for u in users:
        _log.debug(f"  {u}: total={df[u].sum():.1f} kWh, NaN={df[u].isna().sum()}")

    return PreparedInputs(df=df, users=users)
