from dataclasses import dataclass, field
import yaml


def lister(x, default):
    if x is None:
        return list(default)
    if isinstance(x, list):
        return [str(v) for v in x]
    return [str(x)]


@dataclass
class OptimizationConfig:
    solver: str
    solver_fallbacks: list[str]
    tee: bool

    def validate(self):
        if not self.solver:
            raise ValueError("optimization.solver no puede estar vacío")
        self.solver_fallbacks = [s for s in self.solver_fallbacks if s.strip() and s != self.solver]


@dataclass
class DynamicConfig:
    block_mode: str

    def validate(self):
        if self.block_mode not in {"hour", "day", "week", "month"}:
            raise ValueError("dynamic.block_mode debe ser: hour, day, week o month")


@dataclass
class BatteryConfig:
    enabled: bool
    capacity_kwh: float
    power_kw: float
    efficiency_charge: float
    efficiency_discharge: float
    initial_soc_fraction: float
    replacement_cost_eur: float
    lifecycle_cycles: int

    def validate(self):
        if self.capacity_kwh <= 0:
            raise ValueError("battery.capacity_kwh debe ser mayor que 0")
        if self.power_kw <= 0:
            raise ValueError("battery.power_kw debe ser mayor que 0")
        if not (0.0 < self.efficiency_charge <= 1.0):
            raise ValueError("battery.efficiency_charge debe estar en el rango (0, 1]")
        if not (0.0 < self.efficiency_discharge <= 1.0):
            raise ValueError("battery.efficiency_discharge debe estar en el rango (0, 1]")
        if not (0.0 <= self.initial_soc_fraction <= 1.0):
            raise ValueError("battery.initial_soc_fraction debe estar en el rango [0, 1]")
        if self.replacement_cost_eur < 0:
            raise ValueError("battery.replacement_cost_eur no puede ser negativo")
        if self.lifecycle_cycles <= 0:
            raise ValueError("battery.lifecycle_cycles debe ser mayor que 0")


@dataclass
class ValidationConfig:
    strict: bool
    min_rows_after_merge: int

    def validate(self):
        if self.min_rows_after_merge <= 0:
            raise ValueError("validation.min_rows_after_merge debe ser mayor que 0")


@dataclass
class ExAnteConfig:
    updates_per_year: int

    def validate(self):
        if self.updates_per_year < 0:
            raise ValueError("ex_ante.updates_per_year debe ser mayor o igual que 0")


@dataclass
class CsvConfig:
    encoding: str
    fallback_encoding: str
    sep_primary: str
    sep_fallback: str

    def validate(self):
        for attr in ("encoding", "fallback_encoding", "sep_primary", "sep_fallback"):
            if not getattr(self, attr):
                raise ValueError(f"io.csv.{attr} no puede estar vacío")


@dataclass
class TimeConfig:
    dayfirst: bool
    utc: bool
    floor: str

    def validate(self):
        if self.floor not in {"min", "h", "d"}:
            raise ValueError("io.time.floor debe ser: min, h o d")


@dataclass
class ColumnsConfig:
    time: list[str]
    pv: str
    buy: str
    sell: str
    consumption_prefix: str

    def validate(self):
        if not self.time:
            raise ValueError("io.columns.time no puede ser una lista vacía")
        if not self.pv:
            raise ValueError("io.columns.pv no puede estar vacío")
        if not self.buy:
            raise ValueError("io.columns.buy no puede estar vacío")
        if not self.sell:
            raise ValueError("io.columns.sell no puede estar vacío")
        if not self.consumption_prefix:
            raise ValueError("io.columns.consumption_prefix no puede estar vacío")


@dataclass
class IoConfig:
    csv: CsvConfig
    time: TimeConfig
    columns: ColumnsConfig

    def validate(self):
        self.csv.validate()
        self.time.validate()
        self.columns.validate()


@dataclass
class LoggingConfig:
    directory: str
    level: str
    file_encoding: str

    def validate(self):
        if not self.directory:
            raise ValueError("logging.directory no puede estar vacío")


@dataclass
class PathsConfig:
    resources_dir: str

    def validate(self):
        if not self.resources_dir:
            raise ValueError("paths.resources_dir no puede estar vacío")


@dataclass
class AppConfig:
    paths: PathsConfig
    experiment_name: str
    optimization: OptimizationConfig
    validation: ValidationConfig
    ex_ante: ExAnteConfig
    dynamic: DynamicConfig
    battery: BatteryConfig
    io: IoConfig
    logging: LoggingConfig

    def validate(self):
        self.paths.validate()
        self.optimization.validate()
        self.validation.validate()
        self.ex_ante.validate()
        self.dynamic.validate()
        self.battery.validate()
        self.io.validate()
        self.logging.validate()


def load_config(path="parameters.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    o   = data.get("optimization", {}) or {}
    ea  = data.get("ex_ante",      {}) or {}
    dyn = data.get("dynamic",      {}) or {}
    bat = data.get("battery",      {}) or {}
    io  = data.get("io",           {}) or {}
    csv = io.get("csv",     {}) or {}
    tim = io.get("time",    {}) or {}
    col = io.get("columns", {}) or {}
    log = data.get("logging",    {}) or {}
    val = data.get("validation", {}) or {}
    pth = data.get("paths",      {}) or {}
    exp = data.get("experiment", {}) or {}

    cfg = AppConfig(
        paths=PathsConfig(
            resources_dir=pth.get("resources_dir", "inputs"),
        ),
        experiment_name=str(exp.get("name", "baseline")),
        optimization=OptimizationConfig(
            solver=o.get("solver", "gurobi"),
            solver_fallbacks=lister(o.get("solver_fallbacks", ["cbc"]), ["cbc"]),
            tee=bool(o.get("tee", False)),
        ),
        validation=ValidationConfig(
            strict=bool(val.get("strict", True)),
            min_rows_after_merge=int(val.get("min_rows_after_merge", 24)),
        ),
        ex_ante=ExAnteConfig(
            updates_per_year=int(ea.get("updates_per_year", 4)),
        ),
        dynamic=DynamicConfig(
            block_mode=str(dyn.get("block_mode", "hour")),
        ),
        battery=BatteryConfig(
            enabled=bool(bat.get("enabled", False)),
            capacity_kwh=float(bat.get("capacity_kwh", 10.0)),
            power_kw=float(bat.get("power_kw", 5.0)),
            efficiency_charge=float(bat.get("efficiency_charge", 0.95)),
            efficiency_discharge=float(bat.get("efficiency_discharge", 0.95)),
            initial_soc_fraction=float(bat.get("initial_soc_fraction", 0.0)),
            replacement_cost_eur=float(bat.get("replacement_cost_eur", 500.0)),
            lifecycle_cycles=int(bat.get("lifecycle_cycles", 7000)),
        ),
        io=IoConfig(
            csv=CsvConfig(
                encoding=csv.get("encoding", "utf-8"),
                fallback_encoding=csv.get("fallback_encoding", "latin-1"),
                sep_primary=csv.get("sep_primary", ","),
                sep_fallback=csv.get("sep_fallback", ";"),
            ),
            time=TimeConfig(
                dayfirst=bool(tim.get("dayfirst", False)),
                utc=bool(tim.get("utc", True)),
                floor=tim.get("floor", "h"),
            ),
            columns=ColumnsConfig(
                time=col.get("time", ["Time", "datetime"]),
                pv=str(col.get("pv", "G_kWh")),
                buy=str(col.get("buy", "p_buy_eur_kwh")),
                sell=str(col.get("sell", "p_sell_eur_kwh")),
                consumption_prefix=str(col.get("consumption_prefix", "cons_")),
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
