import logging
import os
import glob
import pathlib
import pandas as pd

from model.parameters import BatteryConfig
from data_io import parse_upload
from optimizacion import optimizar

_PROJECT_ROOT = pathlib.Path(__file__).parent.parent


def crear_logger(cfg, run_id: str) -> logging.Logger:
    log_dir = pathlib.Path(cfg.logging.directory)
    if not log_dir.is_absolute():
        log_dir = _PROJECT_ROOT / log_dir
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger("TFG")
    logger.setLevel(getattr(logging, cfg.logging.level.upper(), logging.INFO))
    for h in list(logger.handlers):
        logger.removeHandler(h)

    fh = logging.FileHandler(log_dir / f"{run_id}.log", encoding=cfg.logging.file_encoding)
    fh.setFormatter(logging.Formatter("%(levelname)-7s %(message)s"))
    logger.addHandler(fh)
    logger.propagate = False
    return logger


def buscar_csv(resources_dir: str, patterns: list[str]) -> str:
    for pat in patterns:
        hits = glob.glob(os.path.join(resources_dir, pat))
        if hits:
            return sorted(hits)[0]
    raise FileNotFoundError(f"No CSV encontrado en {resources_dir}")


def leer_csv(path: str, cfg) -> pd.DataFrame:
    for sep in [cfg.io.csv.sep_primary, cfg.io.csv.sep_fallback]:
        try:
            df = pd.read_csv(path, sep=sep, encoding=cfg.io.csv.encoding)
        except UnicodeDecodeError:
            df = pd.read_csv(path, sep=sep, encoding=cfg.io.csv.fallback_encoding)
        if df.shape[1] > 1:
            return df
    return pd.read_csv(path, sep=None, engine="python")


def cargar_datos_defecto(cfg, logger):
    d = cfg.paths.resources_dir
    if not os.path.isabs(d):
        d = str(_PROJECT_ROOT / d)
    logger.debug(f"buscando CSVs en '{d}'")
    cons  = buscar_csv(d, ["*cons*.csv", "*consumo*.csv", "*perfil*.csv"])
    pv    = buscar_csv(d, ["*pv*.csv"])
    buy   = buscar_csv(d, ["*buy*.csv", "*compra*.csv"])
    sell  = buscar_csv(d, ["*sell*.csv", "*venta*.csv"])
    logger.info(
        f"  [1.2] archivos: cons={os.path.basename(cons)} | pv={os.path.basename(pv)} | "
        f"buy={os.path.basename(buy)} | sell={os.path.basename(sell)}"
    )
    return (
        leer_csv(cons, cfg),
        leer_csv(pv,   cfg),
        leer_csv(buy,  cfg),
        leer_csv(sell, cfg),
    )


def precio_fijo_df(df_time: pd.DataFrame, col: str, value: float):
    tcol = "Time" if "Time" in df_time.columns else df_time.columns[0]
    return pd.DataFrame({tcol: df_time[tcol], col: [float(value)] * len(df_time)})


def run_pipeline(
    cfg,
    mode: str,
    upload_contents: dict | None = None,
    manual: dict | None = None,
    overrides: dict | None = None,
    run_id: str | None = None,
    base_cache: dict | None = None,
) -> tuple:
    from datetime import datetime
    overrides = overrides or {}
    upload_contents = upload_contents or {}
    manual = manual or {}

    run_id  = run_id or datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    logger  = crear_logger(cfg, run_id)
    run_tag = f"{cfg.experiment_name}__{run_id}"

    solver_name        = str(overrides.get("solver_name") or cfg.optimization.solver)
    dynamic_block_mode = str(overrides.get("dynamic_block_mode") or cfg.dynamic.block_mode)
    tariff_mode        = str(overrides.get("tariff_mode") or "indexed")

    manual_buy_enabled  = bool(overrides.get("manual_buy_enabled", False))
    manual_sell_enabled = bool(overrides.get("manual_sell_enabled", False))
    p_buy_manual  = float(overrides.get("p_buy_manual",  manual.get("p_buy_manual",  0.20)) or 0.20)
    p_sell_manual = float(overrides.get("p_sell_manual", manual.get("p_sell_manual", 0.08)) or 0.08)

    exante_updates_per_year = overrides.get("exante_updates_per_year")

    logger.info(f"RUN {run_tag}")

    bat_cfg = None
    if overrides.get("battery_enabled"):
        bat_cfg = BatteryConfig(
            enabled=True,
            capacity_kwh=float(overrides.get("battery_capacity_kwh", 10.0)),
            power_kw=float(overrides.get("battery_power_kw", 5.0)),
            efficiency_charge=float(overrides.get("battery_eta_c", 0.95)),
            efficiency_discharge=float(overrides.get("battery_eta_d", 0.95)),
            initial_soc_fraction=float(overrides.get("battery_soc_init", cfg.battery.initial_soc_fraction)),
            replacement_cost_eur=float(overrides.get("battery_replacement_cost", cfg.battery.replacement_cost_eur)),
            lifecycle_cycles=int(overrides.get("battery_lifecycle_cycles", cfg.battery.lifecycle_cycles)),
        )

    if base_cache is not None:
        logger.info("[1/7] CARGA DE DATOS")
        if bat_cfg:
            logger.info(
                f"  [1.4] batería habilitada: cap={bat_cfg.capacity_kwh} kWh | "
                f"P={bat_cfg.power_kw} kW | eff_c={bat_cfg.efficiency_charge} | eff_d={bat_cfg.efficiency_discharge}"
            )
        df_c = df_pv = df_buy = df_sell = None  # not needed, data is in base_cache
    else:
        logger.info("[1/7] CARGA DE DATOS")
        logger.info(
            f"  [1.1] modo={mode} | solver={solver_name} | tariff={tariff_mode} | "
            f"dyn_mode={dynamic_block_mode} | ex_updates={exante_updates_per_year}"
        )
        if bat_cfg:
            logger.info(
                f"  [1.4] batería habilitada: cap={bat_cfg.capacity_kwh} kWh | "
                f"P={bat_cfg.power_kw} kW | eff_c={bat_cfg.efficiency_charge} | eff_d={bat_cfg.efficiency_discharge}"
            )

        if mode == "default":
            df_c, df_pv, df_buy, df_sell = cargar_datos_defecto(cfg, logger)
        elif mode == "csv":
            df_c  = parse_upload(upload_contents["cons"])
            df_pv = parse_upload(upload_contents["pv"])
            logger.info(f"  [1.2] uploads: cons={df_c.shape[0]} filas | pv={df_pv.shape[0]} filas")
            need_buy_file  = (tariff_mode == "indexed") and (not manual_buy_enabled)
            need_sell_file = (tariff_mode == "indexed") and (not manual_sell_enabled)
            if tariff_mode == "fixed":
                df_buy  = precio_fijo_df(df_c, "p_buy",  p_buy_manual)
                df_sell = precio_fijo_df(df_c, "p_sell", p_sell_manual)
                logger.info(f"  [1.3] precios fijos: p_buy={p_buy_manual} €/kWh | p_sell={p_sell_manual} €/kWh")
            else:
                if need_buy_file and not upload_contents.get("buy"):
                    raise ValueError("Falta CSV de precio compra (indexada) o activa Manual compra.")
                if need_sell_file and not upload_contents.get("sell"):
                    raise ValueError("Falta CSV de precio venta (indexada) o activa Manual venta.")
                df_buy  = parse_upload(upload_contents["buy"])  if upload_contents.get("buy")  else precio_fijo_df(df_c, "p_buy",  p_buy_manual)
                df_sell = parse_upload(upload_contents["sell"]) if upload_contents.get("sell") else precio_fijo_df(df_c, "p_sell", p_sell_manual)
                if manual_buy_enabled:
                    df_buy  = precio_fijo_df(df_c, "p_buy",  p_buy_manual)
                if manual_sell_enabled:
                    df_sell = precio_fijo_df(df_c, "p_sell", p_sell_manual)
                buy_src  = f"manual {p_buy_manual} €/kWh"  if manual_buy_enabled  else "CSV"
                sell_src = f"manual {p_sell_manual} €/kWh" if manual_sell_enabled else "CSV"
                logger.info(f"  [1.3] precios: buy={buy_src} | sell={sell_src}")
        else:
            raise ValueError("mode debe ser 'csv' o 'default'.")

    old_updates = cfg.ex_ante.updates_per_year
    try:
        if exante_updates_per_year is not None:
            cfg.ex_ante.updates_per_year = int(exante_updates_per_year)

        results = optimizar(
            df_c, df_pv, df_buy, df_sell,
            config=cfg,
            logger=logger,
            solver_name=solver_name,
            dynamic_block_mode=dynamic_block_mode,
            battery_cfg=bat_cfg,
            base_cache=base_cache,
        )
    finally:
        cfg.ex_ante.updates_per_year = old_updates

    logger.info(f"RUN OK | {run_tag}")
    summary, df_ts, out_base_cache = results
    return (summary, df_ts), run_tag, None, out_base_cache
