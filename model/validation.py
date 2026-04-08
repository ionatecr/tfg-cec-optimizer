import logging
from dataclasses import dataclass
from typing import Literal
import pandas as pd

from data_io import PreparedInputs

_log = logging.getLogger("TFG")

Level = Literal["INFO","WARN","ERROR"]

@dataclass(frozen=True)
class Issue:
    level: Level
    code: str
    message: str
    hint: str = ""


def validate_prepared_inputs(prep: PreparedInputs, strict: bool = True) -> list[Issue]:
    issues: list[Issue] = []
    df = prep.df

    required = {prep.time_col, prep.pv_col, prep.buy_col, prep.sell_col}
    missing = [c for c in required if c not in df.columns]
    if missing:
        _log.error(f"  [3.1] columnas requeridas: FALTA {missing}")
        issues.append(Issue("ERROR", "MISSING_COLUMNS",
                            f"Faltan columnas requeridas: {missing}",
                            "Revisa el preprocess/renombrado en data_io.prepare_inputs()."))
    else:
        _log.info("  [3.1] columnas requeridas: OK")

    if not prep.users:
        _log.error("  [3.2] usuarios: NINGUNO DETECTADO")
        issues.append(Issue("ERROR", "NO_USERS",
                            "No se han detectado usuarios (consumos).",
                            "Asegúrate de que existan columnas cons_* o que el renombrado automático funcione."))
    else:
        _log.info(f"  [3.2] usuarios ({len(prep.users)}): OK → {prep.users}")

    if any(i.level == "ERROR" for i in issues) and strict:
        _log.warning("  validación abortada por errores críticos")
        return issues

    if prep.time_col in df.columns:
        dtype_ok = pd.api.types.is_datetime64_any_dtype(df[prep.time_col])
        n_nat    = int(df[prep.time_col].isna().sum())
        n_dup    = int(df[prep.time_col].duplicated().sum())
        t_ok = dtype_ok and n_nat == 0 and n_dup == 0
        status = "OK" if t_ok else f"{'dtype=ERR ' if not dtype_ok else ''}{'NaT=' + str(n_nat) + ' ' if n_nat else ''}{'dup=' + str(n_dup) if n_dup else ''}".strip()
        _log.info(f"  [3.3] Time: dtype={'OK' if dtype_ok else 'FALLO'} | NaT={n_nat} | duplicados={n_dup} → {status}")
        if not dtype_ok:
            issues.append(Issue("ERROR" if strict else "WARN", "TIME_NOT_DATETIME",
                                "La columna Time no es datetime.",
                                "Convierte en norm_time() con pd.to_datetime(...)."))
        if n_nat > 0:
            issues.append(Issue("ERROR" if strict else "WARN", "TIME_HAS_NAT",
                                f"Hay {n_nat} filas con Time = NaT.",
                                "Revisa el parseo del timestamp (formato/UTC/dayfirst)."))
        if n_dup > 0:
            issues.append(Issue("ERROR" if strict else "WARN", "TIME_DUPLICATES",
                                f"Hay {n_dup} timestamps duplicados en Time.",
                                "En norm_time() ya haces drop_duplicates; revisa si se está aplicando."))

    if (len(df) > 2 and prep.time_col in df.columns
            and pd.api.types.is_datetime64_any_dtype(df[prep.time_col])):
        diffs = df[prep.time_col].diff().dropna()
        if not diffs.empty:
            dt_mode = diffs.mode().iloc[0]
            gaps = diffs[diffs > 2 * dt_mode]
            if gaps.empty:
                _log.info(f"  [3.4] regularidad temporal: dt={dt_mode} | 0 huecos → OK")
            else:
                _log.warning(f"  [3.4] regularidad temporal: {len(gaps)} huecos > 2×{dt_mode} → WARN")
                issues.append(Issue("WARN", "TIME_GAPS",
                                    f"{len(gaps)} huecos en la serie temporal superiores a 2×dt ({dt_mode}).",
                                    "Puede haber días/horas faltantes que afecten al resultado."))

    numeric_cols = [prep.pv_col, prep.buy_col, prep.sell_col] + list(prep.users)
    bad_cols = [c for c in numeric_cols if c in df.columns and not pd.api.types.is_numeric_dtype(df[c])]
    if bad_cols:
        _log.error(f"  [3.5] tipos numéricos: NO NUMÉRICO en {bad_cols}")
        for c in bad_cols:
            issues.append(Issue("ERROR" if strict else "WARN", "NON_NUMERIC",
                                f"La columna {c} no es numérica.",
                                "Convierte a float con pd.to_numeric(..., errors='coerce')."))
    else:
        _log.info(f"  [3.5] tipos numéricos: OK ({len(numeric_cols)} columnas)")

    neg_cols = [c for c in [prep.pv_col] + list(prep.users)
                if c in df.columns and pd.api.types.is_numeric_dtype(df[c]) and (df[c] < 0).any()]
    if neg_cols:
        for c in neg_cols:
            n_neg = int((df[c] < 0).sum())
            _log.warning(f"  [3.6] valores negativos: {n_neg} en '{c}' → WARN")
            issues.append(Issue("WARN", "NEGATIVE_VALUES",
                                f"{n_neg} valores negativos en {c}.",
                                "Si es un error de datos, clipea a 0 o revisa el CSV."))
    else:
        _log.info("  [3.6] valores negativos: OK")

    if len(df) == 0:
        _log.error("  [3.7] longitud: VACÍO")
        issues.append(Issue("ERROR" if strict else "WARN", "EMPTY_DF",
                            "Tras los merges, el dataframe final está vacío.",
                            "Puede haber timestamps que no coinciden entre ficheros (inner merge)."))
    elif len(df) < 24:
        _log.warning(f"  [3.7] longitud: {len(df)} filas → WARN (muy corta)")
        issues.append(Issue("WARN", "SHORT_SERIES",
                            f"Serie temporal corta: {len(df)} filas.",
                            "Puede afectar estabilidad y conclusiones; revisa intersección temporal."))
    else:
        _log.info(f"  [3.7] longitud: {len(df)} filas → OK")

    if len(df) == 0:
        return issues

    if prep.pv_col in df.columns and prep.users:
        gen_total = float(df[prep.pv_col].sum())
        dem_total = float(df[prep.users].sum().sum())
        if dem_total > 0:
            fv_ratio = gen_total / dem_total
            if fv_ratio < 0.01:
                _log.warning(f"  [3.8] ratio FV/demanda: {fv_ratio:.1%} → WARN (muy bajo)")
                issues.append(Issue("WARN", "FV_LOW_RATIO",
                                    f"Generación FV ({gen_total:.0f} kWh) es solo el {fv_ratio:.1%} de la demanda total.",
                                    "Verifica la escala del archivo PV o si los datos corresponden al mismo periodo."))
            elif fv_ratio > 5.0:
                _log.warning(f"  [3.8] ratio FV/demanda: {fv_ratio:.1%} → WARN (>5×)")
                issues.append(Issue("WARN", "FV_HIGH_RATIO",
                                    f"Generación FV supera 5× la demanda total ({fv_ratio:.1%}).",
                                    "Comprueba las unidades: ¿kWh vs MWh?"))
            else:
                _log.info(f"  [3.8] ratio FV/demanda: {fv_ratio:.1%} | G={gen_total:.0f} kWh | D={dem_total:.0f} kWh → OK")

    if (prep.buy_col in df.columns and prep.sell_col in df.columns
            and pd.api.types.is_numeric_dtype(df[prep.buy_col])
            and pd.api.types.is_numeric_dtype(df[prep.sell_col])):
        n_inv    = int((df[prep.buy_col] < df[prep.sell_col]).sum())
        pct_inv  = n_inv / len(df)
        n_neg_b  = int((df[prep.buy_col] < 0).sum())
        p_buy_m  = float(df[prep.buy_col].mean())
        p_sell_m = float(df[prep.sell_col].mean())
        inv_tag  = f"WARN ({pct_inv:.1%} invertidos)" if pct_inv > 0.10 else "OK"
        neg_tag  = f"WARN ({n_neg_b} negativos)" if n_neg_b else "OK"
        _log.info(f"  [3.9] precios: p_buy_media={p_buy_m:.4f} | p_sell_media={p_sell_m:.4f} | "
                  f"invertidos={pct_inv:.1%} → {inv_tag} | p_buy<0={n_neg_b} → {neg_tag}")
        if pct_inv > 0.10:
            issues.append(Issue("WARN", "PRICE_INVERTED",
                                f"En el {pct_inv:.1%} de los periodos el precio de compra es inferior al de venta.",
                                "Revisa que los archivos buy/sell no estén intercambiados."))
        if n_neg_b > 0:
            issues.append(Issue("WARN", "NEGATIVE_BUY_PRICE",
                                f"{n_neg_b} periodos con precio de compra negativo.",
                                "Normal en PVPC con muchas renovables; verifica que no sea un error."))

    zero_u = [u for u in prep.users if u in df.columns
              and pd.api.types.is_numeric_dtype(df[u]) and float(df[u].sum()) <= 0]
    if zero_u:
        _log.warning(f"  [3.10] demanda por usuario: WARN demanda nula en {zero_u}")
        for u in zero_u:
            issues.append(Issue("WARN", "ZERO_DEMAND_USER",
                                f"El usuario '{u}' tiene demanda total = 0 kWh.",
                                "Puede ser un error de datos o un usuario inactivo."))
    else:
        totals = {u: f"{df[u].sum():.0f}" for u in prep.users if u in df.columns}
        _log.info(f"  [3.10] demanda por usuario: OK → {totals} kWh")

    if (prep.pv_col in df.columns and prep.time_col in df.columns
            and pd.api.types.is_datetime64_any_dtype(df[prep.time_col])):
        night_mask = df[prep.time_col].dt.hour.isin(range(1, 6))
        if night_mask.any():
            total_pv = float(df[prep.pv_col].sum())
            night_pv = float(df.loc[night_mask, prep.pv_col].sum())
            if total_pv > 0:
                night_r = night_pv / total_pv
                if night_r > 0.05:
                    _log.warning(f"  [3.11] FV nocturna (1h–5h): {night_r:.1%} del total → WARN")
                    issues.append(Issue("WARN", "FV_NIGHT_GENERATION",
                                        f"El {night_r:.1%} de la generación FV ocurre entre la 1h y las 5h.",
                                        "Revisa si hay un desfase horario (UTC vs local) o error en el archivo PV."))
                else:
                    _log.info(f"  [3.11] FV nocturna (1h–5h): {night_r:.1%} → OK")

    n_err  = sum(1 for i in issues if i.level == "ERROR")
    n_warn = sum(1 for i in issues if i.level == "WARN")
    _log.info(f"  resultado: {n_err} errores, {n_warn} warnings")
    return issues
