from dataclasses import dataclass, field
from typing import Optional
import yaml


def _as_list(x, default: list[str]) -> list[str]:
    if x is None:
        return list(default)
    if isinstance(x, list):
        return [str(v) for v in x]
    return [str(x)]


@dataclass
class OptimizationConfig:
    solver: str = "gurobi"
    solver_fallbacks: list[str] = field(default_factory=lambda: ["cbc"])
    tee: bool = False

    def validate(self) -> None:
        if not self.solver:
            raise ValueError("optimization.solver must be a non-empty string")
        self.solver_fallbacks = [s for s in self.solver_fallbacks if s.strip() and s != self.solver]


@dataclass
class DynamicConfig:
    block_mode: str = "day"

    def validate(self) -> None:
        if self.block_mode not in {"hour", "day", "week", "month"}:
            raise ValueError("dynamic.block_mode must be one of: hour, day, week, month")


@dataclass
class BatteryConfig:
    enabled: bool = False
    capacity_kwh: float = 10.0
    power_kw: float = 5.0
    efficiency_charge: float = 0.95
    efficiency_discharge: float = 0.95
    initial_soc_fraction: float = 0.5

    def validate(self) -> None:
        if self.capacity_kwh <= 0:
            raise ValueError("battery.capacity_kwh must be > 0")
        if self.power_kw <= 0:
            raise ValueError("battery.power_kw must be > 0")
        if not (0.0 < self.efficiency_charge <= 1.0):
            raise ValueError("battery.efficiency_charge must be in (0, 1]")
        if not (0.0 < self.efficiency_discharge <= 1.0):
            raise ValueError("battery.efficiency_discharge must be in (0, 1]")
        if not (0.0 <= self.initial_soc_fraction <= 1.0):
            raise ValueError("battery.initial_soc_fraction must be in [0, 1]")


@dataclass
class ValidationConfig:
    strict: bool = True
    min_rows_after_merge: int = 24

    def validate(self) -> None:
        if self.min_rows_after_merge <= 0:
            raise ValueError("validation.min_rows_after_merge must be > 0")


@dataclass
class ExAnteConfig:
    mode: str = "equal"
    fixed_coefficients: dict[str, float] = field(default_factory=dict)
    normalize_if_needed: bool = True
    updates_per_year: int = 4
    block_mode: str = "month"

    def validate(self) -> None:
        if self.mode not in {"equal", "fixed_coefficients"}:
            raise ValueError("ex_ante.mode must be one of: equal, fixed_coefficients")
        self.fixed_coefficients = {
            str(k): float(v) for k, v in self.fixed_coefficients.items() if v is not None
        }
        if self.mode == "fixed_coefficients" and not self.fixed_coefficients:
            raise ValueError("ex_ante.fixed_coefficients required when mode=fixed_coefficients")
        if any(v < 0 for v in self.fixed_coefficients.values()):
            raise ValueError("ex_ante.fixed_coefficients values must be >= 0")
        if self.updates_per_year < 0:
            raise ValueError("ex_ante.updates_per_year must be >= 0")
        if self.block_mode not in {"hour", "day", "week", "month"}:
            raise ValueError("ex_ante.block_mode must be one of: hour, day, week, month")


@dataclass
class CsvConfig:
    encoding: str = "utf-8"
    fallback_encoding: str = "latin-1"
    sep_primary: str = ","
    sep_fallback: str = ";"

    def validate(self) -> None:
        for attr in ("encoding", "fallback_encoding", "sep_primary", "sep_fallback"):
            if not getattr(self, attr):
                raise ValueError(f"io.csv.{attr} must be a non-empty string")


@dataclass
class TimeConfig:
    dayfirst: bool = True
    utc: bool = True
    floor: str = "h"
    drop_duplicates: bool = True

    def validate(self) -> None:
        if self.floor not in {"min", "h", "d"}:
            raise ValueError("io.time.floor must be one of: min, h, d")


@dataclass
class DetectConfig:
    time_patterns: list[str] = field(default_factory=lambda: [
        r"\butc[_\-\s]*timestamp\b",
        r"\btimestamp\b",
        r"\bdatetime\b",
        r"\bdate[_\-\s]*time\b",
        r"\btime\b",
        r"\bfecha\b",
    ])
    pv_preferred_cols: list[str] = field(default_factory=lambda: ["pv_kWh", "G_kWh", "pv", "gen", "generation"])
    buy_preferred_cols: list[str] = field(default_factory=lambda: ["p_buy", "buy_eur_kWh", "price_buy", "buy_price"])
    sell_preferred_cols: list[str] = field(default_factory=lambda: ["p_sell", "sell_eur_kWh", "price_sell", "sell_price"])
    consumption_prefixes: list[str] = field(default_factory=lambda: ["cons_"])

    def validate(self) -> None:
        for attr in ("time_patterns", "pv_preferred_cols", "buy_preferred_cols",
                     "sell_preferred_cols", "consumption_prefixes"):
            v = getattr(self, attr)
            if not isinstance(v, list) or not all(isinstance(x, str) and x for x in v):
                raise TypeError(f"io.detect.{attr} must be a list[str]")


@dataclass
class IoConfig:
    csv: CsvConfig = field(default_factory=CsvConfig)
    time: TimeConfig = field(default_factory=TimeConfig)
    detect: DetectConfig = field(default_factory=DetectConfig)

    def validate(self) -> None:
        self.csv.validate()
        self.time.validate()
        self.detect.validate()


@dataclass
class LoggingConfig:
    directory: str = "logs"
    level: str = "INFO"
    file_encoding: str = "utf-8"

    def validate(self) -> None:
        if not self.directory:
            raise ValueError("logging.directory must be non-empty")


@dataclass
class PathsConfig:
    resources_dir: str = "resources"
    output_dir: str = "outputs"

    def validate(self) -> None:
        if not self.resources_dir:
            raise ValueError("paths.resources_dir must be non-empty")


@dataclass
class AppConfig:
    paths: PathsConfig = field(default_factory=PathsConfig)
    experiment_name: str = "baseline"
    optimization: OptimizationConfig = field(default_factory=OptimizationConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    ex_ante: ExAnteConfig = field(default_factory=ExAnteConfig)
    dynamic: DynamicConfig = field(default_factory=DynamicConfig)
    battery: BatteryConfig = field(default_factory=BatteryConfig)
    io: IoConfig = field(default_factory=IoConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    def validate(self) -> None:
        self.paths.validate()
        self.optimization.validate()
        self.validation.validate()
        self.ex_ante.validate()
        self.dynamic.validate()
        self.battery.validate()
        self.io.validate()
        self.logging.validate()


def load_config(path: str = "parameters.yaml") -> AppConfig:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    o   = data.get("optimization", {}) or {}
    ea  = data.get("ex_ante",      {}) or {}
    dyn = data.get("dynamic",      {}) or {}
    bat = data.get("battery",      {}) or {}
    io  = data.get("io",           {}) or {}
    csv = io.get("csv",    {}) or {}
    tim = io.get("time",   {}) or {}
    det = io.get("detect", {}) or {}
    log = data.get("logging",    {}) or {}
    val = data.get("validation", {}) or {}
    pth = data.get("paths",      {}) or {}
    exp = data.get("experiment", {}) or {}
    dd  = DetectConfig()

    # support old nested solver_options and thresholds keys for backward compat
    sol = (o.get("solver_options") or {})
    thr = (val.get("thresholds") or {})

    cfg = AppConfig(
        paths=PathsConfig(
            resources_dir=pth.get("resources_dir", "resources"),
            output_dir=pth.get("output_dir", "outputs"),
        ),
        experiment_name=str(exp.get("name", "baseline")),
        optimization=OptimizationConfig(
            solver=o.get("solver", "gurobi"),
            solver_fallbacks=_as_list(o.get("solver_fallbacks", ["cbc"]), ["cbc"]),
            tee=bool(sol.get("tee", o.get("tee", False))),
        ),
        validation=ValidationConfig(
            strict=bool(val.get("strict", True)),
            min_rows_after_merge=int(thr.get("min_rows_after_merge",
                                     val.get("min_rows_after_merge", 24))),
        ),
        ex_ante=ExAnteConfig(
            mode=ea.get("mode", "equal"),
            fixed_coefficients=ea.get("fixed_coefficients") or {},
            normalize_if_needed=bool(ea.get("normalize_if_needed", True)),
            updates_per_year=int(ea.get("updates_per_year", 4)),
            block_mode=str(ea.get("block_mode", "month")),
        ),
        dynamic=DynamicConfig(
            block_mode=str(dyn.get("block_mode", "day")),
        ),
        battery=BatteryConfig(
            enabled=bool(bat.get("enabled", False)),
            capacity_kwh=float(bat.get("capacity_kwh", 10.0)),
            power_kw=float(bat.get("power_kw", 5.0)),
            efficiency_charge=float(bat.get("efficiency_charge", 0.95)),
            efficiency_discharge=float(bat.get("efficiency_discharge", 0.95)),
            initial_soc_fraction=float(bat.get("initial_soc_fraction", 0.5)),
        ),
        io=IoConfig(
            csv=CsvConfig(
                encoding=csv.get("encoding", "utf-8"),
                fallback_encoding=csv.get("fallback_encoding", "latin-1"),
                sep_primary=csv.get("sep_primary", ","),
                sep_fallback=csv.get("sep_fallback", ";"),
            ),
            time=TimeConfig(
                dayfirst=bool(tim.get("dayfirst", True)),
                utc=bool(tim.get("utc", True)),
                floor=tim.get("floor", "h"),
                drop_duplicates=bool(tim.get("drop_duplicates", True)),
            ),
            detect=DetectConfig(
                time_patterns=_as_list(det.get("time_patterns"), dd.time_patterns),
                pv_preferred_cols=_as_list(det.get("pv_preferred_cols"), dd.pv_preferred_cols),
                buy_preferred_cols=_as_list(det.get("buy_preferred_cols"), dd.buy_preferred_cols),
                sell_preferred_cols=_as_list(det.get("sell_preferred_cols"), dd.sell_preferred_cols),
                consumption_prefixes=_as_list(det.get("consumption_prefixes"), dd.consumption_prefixes),
            ),
        ),
        logging=LoggingConfig(
            directory=log.get("directory", "logs"),
            level=log.get("level", "INFO"),
            file_encoding=log.get("file_encoding", "utf-8"),
        ),
    )
    cfg.validate()
    return cfg
