import logging
import sys
import pandas as pd
from pyomo.environ import (
    ConcreteModel, RangeSet, Param, Var, Constraint, Objective, minimize,
    NonNegativeReals, Binary, SolverFactory, value,
)

from model.validation import validate_prepared_inputs
from data_io import prepare_inputs
from model.parameters import AppConfig, BatteryConfig

_log = logging.getLogger("TFG")


def probar_solver(name):
    s = SolverFactory(name)
    _saved_out, _saved_err = sys.stdout, sys.stderr
    try:
        ok = (s is not None) and s.available(exception_flag=False)
    finally:
        sys.stdout, sys.stderr = _saved_out, _saved_err
    return s, ok


def elegir_solver(requested, fallbacks, logger):
    req = (requested or "").strip().lower()
    order = []
    if req:
        order.append(req)
    for fb in (fallbacks or []):
        if fb:
            order.append(fb.strip().lower())
    if not order:
        order = ["cbc"]
    for name in order:
        s, ok = probar_solver(name)
        if ok:
            logger.info(f"solver: '{name}' disponible y seleccionado")
            return s, name
        logger.warning(f"solver: '{name}' no disponible")
    raise RuntimeError("Solver no disponible, prueba otro.")


_BLOCK_FMT = {"hour": "%Y-%m-%d %H:00", "day": "%Y-%m-%d",
              "week": "%Y-%W",          "month": "%Y-%m"}


def calcular_bloques(times, block_mode):
    fmt = _BLOCK_FMT.get(block_mode, "%Y-%m-%d")

    labels = []
    for ts in times:
        labels.append(ts.strftime(fmt))

    uniq = []
    for label in labels:
        if label not in uniq:
            uniq.append(label)

    b_map = {}
    for t_idx in range(len(times)):
        b_map[t_idx + 1] = uniq.index(labels[t_idx]) + 1

    return list(range(1, len(uniq) + 1)), b_map


def calcular_segmentos(times, updates_per_year):
    seg_of_t = {}

    if updates_per_year <= 0:
        for i in range(len(times)):
            seg_of_t[i + 1] = 1
        return seg_of_t, 1

    t0 = times.min()
    t1 = times.max()
    if pd.isna(t0) or pd.isna(t1):
        _log.warning("calcular_segmentos: rango temporal inválido, usando 1 segmento")
        for i in range(len(times)):
            seg_of_t[i + 1] = 1
        return seg_of_t, 1

    segments = int(updates_per_year)
    if segments <= 1:
        for i in range(len(times)):
            seg_of_t[i + 1] = 1
        return seg_of_t, 1

    years = pd.Series(times.dt.year).dropna().unique()
    single_year = len(years) == 1

    if single_year and segments in {2, 3, 4, 6, 12}:
        for t_idx in range(len(times)):
            mes = int(times.iloc[t_idx].month)
            seg_of_t[t_idx + 1] = ((mes - 1) // (12 // segments)) + 1
        return seg_of_t, segments

    span = (t1 - t0).total_seconds()
    if span <= 0:
        for i in range(len(times)):
            seg_of_t[i + 1] = 1
        return seg_of_t, 1

    seg_len = span / segments
    for t_idx in range(len(times)):
        k = int(((times.iloc[t_idx] - t0).total_seconds()) // seg_len) + 1
        seg_of_t[t_idx + 1] = max(1, min(k, segments))
    return seg_of_t, segments


def bloques_ex_ante(times, updates_per_year):
    if updates_per_year == 0:
        b_map = {}
        for i in range(len(times)):
            b_map[i + 1] = 1
        return [1], b_map

    seg_of_t, n_seg = calcular_segmentos(times, updates_per_year)

    labels = []
    for i in range(len(times)):
        labels.append(str(seg_of_t[i + 1]))

    uniq = []
    for label in labels:
        if label not in uniq:
            uniq.append(label)

    b_map = {}
    for t_idx in range(len(times)):
        b_map[t_idx + 1] = uniq.index(labels[t_idx]) + 1

    return list(range(1, len(uniq) + 1)), b_map


def corregir_alpha(alpha_vals, b_of_t, T, U, g, cons):
    b_to_t = {}
    for t_idx in range(1, T + 1):
        b = b_of_t[t_idx]
        if b not in b_to_t:
            b_to_t[b] = []
        b_to_t[b].append(t_idx)

    n_deg = 0
    for b, times_b in b_to_t.items():
        g_b = 0.0
        for t in times_b:
            g_b += g[t]
        d_b = 0.0
        for t in times_b:
            for u in range(1, U + 1):
                d_b += cons[(u, t)]

        # si FV es mayor o igual que la demanda o no hay FV el reparto es proporcional a la demanda
        if (g_b >= d_b or g_b <= 1e-6) and d_b > 0:
            n_deg += 1
            for u in range(1, U + 1):
                demanda_u = 0.0
                for t in times_b:
                    demanda_u += cons[(u, t)]
                alpha_vals[(u, b)] = demanda_u / d_b
    return n_deg


def _preparar_datos(df, users, b_of_t):
    T = len(df)
    U = len(users)
    cons = {}
    for u in range(U):
        for t in range(T):
            cons[(u + 1, t + 1)] = float(df.loc[t, users[u]])
    g = {}
    pbuy = {}
    psell = {}
    b_param = {}
    for t in range(T):
        g[t + 1]       = float(df.loc[t, "G"])
        pbuy[t + 1]    = float(df.loc[t, "p_buy"])
        psell[t + 1]   = float(df.loc[t, "p_sell"])
        b_param[t + 1] = int(b_of_t[t + 1])
    return cons, g, pbuy, psell, b_param


def resolver_lp(df, users, b_of_t, B, solver, tee, logger, step_num=5, datos=None):
    T = len(df)
    U = len(users)
    s = step_num

    logger.info(f"  [{s}.1] dimensiones: T={T} | U={U} | B={B} bloques | alpha={U*B} vars | self_v={U*T} vars")

    if datos is not None:
        cons, g, pbuy, psell, b_param = datos
    else:
        cons, g, pbuy, psell, b_param = _preparar_datos(df, users, b_of_t)

    g_total  = sum(g.values())
    d_total  = sum(cons.values())

    m = ConcreteModel()
    m.U = RangeSet(1, U)
    m.T = RangeSet(1, T)
    m.B = RangeSet(1, B)

    m.cons   = Param(m.U, m.T, initialize=cons)
    m.g      = Param(m.T,      initialize=g)
    m.pbuy   = Param(m.T,      initialize=pbuy)
    m.psell  = Param(m.T,      initialize=psell)
    m.b_of_t = Param(m.T,      initialize=b_param)

    m.alpha  = Var(m.U, m.B, domain=NonNegativeReals, bounds=(0.0, 1.0))
    m.self_v = Var(m.U, m.T, domain=NonNegativeReals)

    m.sum_alpha = Constraint(
        m.B, rule=lambda m, b: sum(m.alpha[u, b] for u in m.U) == 1.0
    )
    m.self_le_cons = Constraint(
        m.U, m.T, rule=lambda m, u, t: m.self_v[u, t] <= m.cons[u, t]
    )
    m.self_le_pv = Constraint(
        m.U, m.T,
        rule=lambda m, u, t: m.self_v[u, t] <= m.g[t] * m.alpha[u, int(value(m.b_of_t[t]))]
    )
    m.self_le_demand = Constraint(
        m.T, rule=lambda m, t: sum(m.self_v[u, t] for u in m.U) <= sum(m.cons[u, t] for u in m.U)
    )
    m.self_le_gen = Constraint(
        m.T, rule=lambda m, t: sum(m.self_v[u, t] for u in m.U) <= m.g[t]
    )

    def obj_rule(m):
        total = 0.0
        for t in m.T:
            self_tot = sum(m.self_v[u, t] for u in m.U)
            cons_tot = sum(m.cons[u, t] for u in m.U)
            total += m.pbuy[t] * (cons_tot - self_tot) - m.psell[t] * (m.g[t] - self_tot)
        return total

    m.obj = Objective(rule=obj_rule, sense=minimize)
    logger.info(f"  [{s}.2] lanzando solver...")
    _saved_out, _saved_err = sys.stdout, sys.stderr
    try:
        solver.solve(m, tee=tee)
    finally:
        sys.stdout, sys.stderr = _saved_out, _saved_err
    obj_val = float(value(m.obj))
    logger.info(f"  [{s}.3] solver completado | obj={obj_val:.4f} €")

    alpha_vals = {}
    for u in range(1, U + 1):
        for b in range(1, B + 1):
            alpha_vals[(u, b)] = float(value(m.alpha[u, b]))

    corregir_alpha(alpha_vals, b_of_t, T, U, g, cons)

    for b in range(1, B + 1):
        alpha_sum = 0.0
        for u in range(1, U + 1):
            alpha_sum += alpha_vals[(u, b)]
        if abs(alpha_sum - 1.0) > 0.01:
            logger.warning(f"  [{s}.3] WARN: alpha suma={alpha_sum:.4f} en bloque b={b} (esperado 1.0)")

    self_ts = []
    imp_ts  = []
    exp_ts  = []
    cost_ts = []
    per_user_self = {}
    per_user_imp  = {}
    for u in range(1, U + 1):
        per_user_self[u] = []
        per_user_imp[u]  = []

    for t in range(1, T + 1):
        g_t      = float(df.loc[t - 1, "G"])
        pbuy_t   = float(df.loc[t - 1, "p_buy"])
        psell_t  = float(df.loc[t - 1, "p_sell"])
        cons_tot = float(df.loc[t - 1, "D_total"])

        self_total = 0.0
        for u in range(1, U + 1):
            self_u = max(float(value(m.self_v[u, t])), 0.0)
            cons_u = float(df.loc[t - 1, users[u - 1]])
            imp_u  = max(cons_u - self_u, 0.0)
            per_user_self[u].append(self_u)
            per_user_imp[u].append(imp_u)
            self_total += self_u

        imp_t  = max(cons_tot - self_total, 0.0)
        exp_t  = max(g_t - self_total, 0.0)
        cost_t = pbuy_t * imp_t - psell_t * exp_t

        self_ts.append(self_total)
        imp_ts.append(imp_t)
        exp_ts.append(exp_t)
        cost_ts.append(cost_t)

    total_self = sum(self_ts)
    total_imp  = sum(imp_ts)
    total_exp  = sum(exp_ts)
    total_cost = sum(cost_ts)
    logger.info(
        f"  [{s}.4] balance: self={total_self:.1f} kWh | imp={total_imp:.1f} kWh | "
        f"exp={total_exp:.1f} kWh | cost={total_cost:.2f} €"
    )

    implied_imp  = d_total - total_self
    dem_ok  = abs(implied_imp - total_imp) <= max(1.0, 0.01 * d_total)
    fv_ok   = total_self <= g_total + 0.01
    cost_ok = abs(total_cost - obj_val) <= max(1.0, 0.01 * abs(obj_val))
    checks  = (f"balance_D={'OK' if dem_ok else 'WARN'} | "
               f"balance_FV={'OK' if fv_ok else 'WARN'} | "
               f"coste_reconstruct={'OK' if cost_ok else 'WARN'}")
    if dem_ok and fv_ok and cost_ok:
        logger.info(f"  [{s}.5] consistencia: {checks}")
    else:
        logger.warning(f"  [{s}.5] consistencia: {checks}")
        if not dem_ok:
            logger.warning(f"    imp calculado={total_imp:.1f} vs implícito={implied_imp:.1f} (dif={abs(implied_imp-total_imp):.1f} kWh)")
        if not fv_ok:
            logger.warning(f"    self={total_self:.1f} > G={g_total:.1f} kWh")
        if not cost_ok:
            logger.warning(f"    coste reconstruct={total_cost:.2f} vs obj={obj_val:.2f} (dif={abs(total_cost-obj_val):.2f} €)")

    return self_ts, imp_ts, exp_ts, cost_ts, alpha_vals, per_user_self, per_user_imp


def resolver_lp_bateria(
    df,
    users,
    b_of_t,
    B,
    bat_cap,
    bat_pow,
    eta_c,
    eta_d,
    soc_init,
    solver,
    tee,
    logger,
    step_num=7,
    datos=None,
):
    T = len(df)
    U = len(users)
    s = step_num

    logger.info(
        f"  [{s}.1] batería: cap={bat_cap:.1f} kWh | P_max={bat_pow:.1f} kW | "
        f"η_c={eta_c:.2f} | η_d={eta_d:.2f} | SOC_init={soc_init:.1f} kWh"
    )
    logger.info(
        f"  [{s}.1] dimensiones: T={T} | U={U} | B={B} bloques | "
        f"vars_bat={3 * T} (charge+discharge+SOC)"
    )

    if datos is not None:
        cons, g, pbuy, psell, b_param = datos
    else:
        cons, g, pbuy, psell, b_param = _preparar_datos(df, users, b_of_t)

    m = ConcreteModel()
    m.U = RangeSet(1, U)
    m.T = RangeSet(1, T)
    m.B = RangeSet(1, B)

    m.cons   = Param(m.U, m.T, initialize=cons)
    m.g      = Param(m.T,      initialize=g)
    m.pbuy   = Param(m.T,      initialize=pbuy)
    m.psell  = Param(m.T,      initialize=psell)
    m.b_of_t = Param(m.T,      initialize=b_param)

    m.alpha  = Var(m.U, m.B, domain=NonNegativeReals, bounds=(0.0, 1.0))
    m.self_v = Var(m.U, m.T, domain=NonNegativeReals)

    m.charge    = Var(m.T, domain=NonNegativeReals, bounds=(0.0, bat_pow))
    m.discharge = Var(m.T, domain=NonNegativeReals, bounds=(0.0, bat_pow))
    m.SOC       = Var(m.T, domain=NonNegativeReals, bounds=(0.0, bat_cap))

    # Binary variables to prevent simultaneous charge and discharge (MILP)
    m.charge_bin    = Var(m.T, domain=Binary)
    m.discharge_bin = Var(m.T, domain=Binary)
    m.no_simul      = Constraint(m.T, rule=lambda m, t: m.charge_bin[t] + m.discharge_bin[t] <= 1)
    m.charge_ub_bin = Constraint(m.T, rule=lambda m, t: m.charge[t]    <= bat_pow * m.charge_bin[t])
    m.discharge_ub_bin = Constraint(m.T, rule=lambda m, t: m.discharge[t] <= bat_pow * m.discharge_bin[t])

    m.sum_alpha = Constraint(
        m.B, rule=lambda m, b: sum(m.alpha[u, b] for u in m.U) == 1.0
    )
    m.self_le_cons = Constraint(
        m.U, m.T, rule=lambda m, u, t: m.self_v[u, t] <= m.cons[u, t]
    )
    m.self_le_pv = Constraint(
        m.U, m.T,
        rule=lambda m, u, t: m.self_v[u, t] <= m.g[t] * m.alpha[u, int(value(m.b_of_t[t]))]
    )
    m.self_le_demand = Constraint(
        m.T, rule=lambda m, t: sum(m.self_v[u, t] for u in m.U) <= sum(m.cons[u, t] for u in m.U)
    )
    m.self_le_gen = Constraint(
        m.T, rule=lambda m, t: sum(m.self_v[u, t] for u in m.U) <= m.g[t]
    )

    # la batería solo carga con excedente FV
    m.charge_from_surplus = Constraint(
        m.T,
        rule=lambda m, t: sum(m.self_v[u, t] for u in m.U) + m.charge[t] <= m.g[t]
    )
    # la batería solo descarga para cubrir demanda
    m.discharge_to_demand = Constraint(
        m.T,
        rule=lambda m, t: sum(m.self_v[u, t] for u in m.U) + m.discharge[t] <= sum(m.cons[u, t] for u in m.U)
    )
    m.soc_t1 = Constraint(
        expr=m.SOC[1] == soc_init + eta_c * m.charge[1] - m.discharge[1] / eta_d
    )
    if T > 1:
        m.soc_dyn = Constraint(
            RangeSet(2, T),
            rule=lambda m, t: m.SOC[t] == m.SOC[t - 1] + eta_c * m.charge[t] - m.discharge[t] / eta_d
        )
    # la batería termina vacía: se vende toda la energía almacenada
    m.soc_terminal = Constraint(expr=m.SOC[T] == 0)

    def obj_rule(m):
        total = 0.0
        for t in m.T:
            self_tot = sum(m.self_v[u, t] for u in m.U)
            cons_tot = sum(m.cons[u, t] for u in m.U)
            grid_import = cons_tot - self_tot - m.discharge[t]
            grid_export = m.g[t] - self_tot - m.charge[t]
            total += m.pbuy[t] * grid_import - m.psell[t] * grid_export
        return total

    m.obj = Objective(rule=obj_rule, sense=minimize)

    logger.info(f"  [{s}.2] lanzando solver (con batería)...")
    _saved_out, _saved_err = sys.stdout, sys.stderr
    try:
        solver.solve(m, tee=tee)
    finally:
        sys.stdout, sys.stderr = _saved_out, _saved_err
    obj_val = float(value(m.obj))
    logger.info(f"  [{s}.3] solver completado | obj={obj_val:.4f} €")

    alpha_vals = {}
    for u in range(1, U + 1):
        for b in range(1, B + 1):
            alpha_vals[(u, b)] = float(value(m.alpha[u, b]))

    n_deg_bat = corregir_alpha(alpha_vals, b_of_t, T, U, g, cons)
    if n_deg_bat:
        logger.debug(f"  [{s}.3] alpha post-proceso batería: {n_deg_bat} bloques degenerados → proporcional a demanda")

    self_ts:     list[float] = []
    imp_ts:      list[float] = []
    exp_ts:      list[float] = []
    cost_ts:     list[float] = []
    charge_ts:   list[float] = []
    discharge_ts: list[float] = []
    soc_ts:      list[float] = []
    per_user_self = {}
    per_user_imp = {}
    for u in range(1, U + 1):
        per_user_self[u] = []
        per_user_imp[u] = []

    for t in range(1, T + 1):
        g_t      = float(df.loc[t - 1, "G"])
        pbuy_t   = float(df.loc[t - 1, "p_buy"])
        psell_t  = float(df.loc[t - 1, "p_sell"])
        cons_tot = float(df.loc[t - 1, "D_total"])
        ch_t     = max(float(value(m.charge[t])),    0.0)
        dis_t    = max(float(value(m.discharge[t])), 0.0)
        soc_t    = max(float(value(m.SOC[t])),       0.0)

        self_total = 0.0
        for u in range(1, U + 1):
            self_u = max(float(value(m.self_v[u, t])), 0.0)
            cons_u = float(df.loc[t - 1, users[u - 1]])
            imp_u  = max(cons_u - self_u, 0.0)
            per_user_self[u].append(self_u)
            per_user_imp[u].append(imp_u)
            self_total += self_u

        imp_t  = max(cons_tot - self_total - dis_t, 0.0)
        exp_t  = max(g_t - self_total - ch_t, 0.0)
        cost_t = pbuy_t * imp_t - psell_t * exp_t

        self_ts.append(self_total)
        imp_ts.append(imp_t)
        exp_ts.append(exp_t)
        cost_ts.append(cost_t)
        charge_ts.append(ch_t)
        discharge_ts.append(dis_t)
        soc_ts.append(soc_t)

    total_self   = sum(self_ts)
    total_imp    = sum(imp_ts)
    total_exp    = sum(exp_ts)
    total_cost   = sum(cost_ts)
    total_charge = sum(charge_ts)
    total_disch  = sum(discharge_ts)
    logger.info(
        f"  [{s}.4] balance: self={total_self:.1f} kWh | imp={total_imp:.1f} kWh | "
        f"exp={total_exp:.1f} kWh | charge={total_charge:.1f} kWh | "
        f"discharge={total_disch:.1f} kWh | cost={total_cost:.2f} €"
    )

    return (
        self_ts, imp_ts, exp_ts, cost_ts,
        charge_ts, discharge_ts, soc_ts,
        alpha_vals, per_user_self, per_user_imp,
    )


def reparto_fijo(df, users, logger):
    T = len(df)
    U = len(users)

    dem_per_u = {}
    for i, u in enumerate(users):
        dem_per_u[i + 1] = float(df[u].sum())

    dem_global = sum(dem_per_u.values())

    alpha_fx = {}
    for i in range(U):
        if dem_global > 0:
            alpha_fx[i + 1] = dem_per_u[i + 1] / dem_global
        else:
            alpha_fx[i + 1] = 1.0 / U
    p_buy_fx  = float(df["p_buy"].mean())
    p_sell_fx = float(df["p_sell"].mean())

    partes = []
    for i in range(U):
        partes.append(f"u{i+1}={alpha_fx[i+1]:.3f}")
    logger.info(
        "  [fx] α: " + " | ".join(partes) +
        f" | p_buy_medio={p_buy_fx:.4f} | p_sell_medio={p_sell_fx:.4f}"
    )

    self_ts = []
    imp_ts  = []
    exp_ts  = []
    cost_ts = []
    pu_self = {}
    pu_imp = {}
    for i in range(U):
        pu_self[i + 1] = []
        pu_imp[i + 1] = []

    for t in range(T):
        g_t   = float(df.loc[t, "G"])
        d_tot = float(df.loc[t, "D_total"])
        self_total = 0.0
        for i, u in enumerate(users):
            u_idx  = i + 1
            cons_u = float(df.loc[t, u])
            self_u = min(cons_u, g_t * alpha_fx[u_idx])
            imp_u  = max(cons_u - self_u, 0.0)
            pu_self[u_idx].append(self_u)
            pu_imp[u_idx].append(imp_u)
            self_total += self_u
        imp_t  = max(d_tot - self_total, 0.0)
        exp_t  = max(g_t  - self_total, 0.0)
        cost_t = float(df.loc[t, "p_buy"]) * imp_t - float(df.loc[t, "p_sell"]) * exp_t
        self_ts.append(self_total)
        imp_ts.append(imp_t)
        exp_ts.append(exp_t)
        cost_ts.append(cost_t)

    return self_ts, imp_ts, exp_ts, cost_ts, alpha_fx, pu_self, pu_imp, p_buy_fx, p_sell_fx


def optimizar(
    df_c,
    df_pv,
    df_buy,
    df_sell,
    config: AppConfig,
    logger,
    solver_name: str | None = None,
    dynamic_block_mode: str | None = None,
    battery_cfg: BatteryConfig | None = None,
    base_cache: dict | None = None,
):
    cfg = config
    solver_name        = solver_name        or cfg.optimization.solver
    dynamic_block_mode = dynamic_block_mode or cfg.dynamic.block_mode
    updates_per_year   = int(cfg.ex_ante.updates_per_year)

    run_battery = battery_cfg is not None and battery_cfg.enabled

    if base_cache is not None:
        df          = base_cache["df"]
        users       = base_cache["users"]
        T, U        = base_cache["T"], base_cache["U"]
        b_of_t_ex   = base_cache["b_of_t_ex"]
        B_ex        = base_cache["B_ex"]
        b_of_t_dyn  = base_cache["b_of_t_dyn"]
        B_dyn       = base_cache["B_dyn"]
        solver      = base_cache["solver"]
        solver_used = base_cache["solver_used"]
        tee         = base_cache["tee"]
        datos_dyn   = base_cache["datos_dyn"]

        (self_ex_ts, imp_ex_ts, exp_ex_ts, cost_ex_ts,
         alpha_ex, pu_self_ex, pu_imp_ex) = base_cache["ex_ante"]

        (self_dyn_ts, imp_dyn_ts, exp_dyn_ts, cost_dyn_ts,
         alpha_dyn, pu_self_dyn, pu_imp_dyn) = base_cache["dynamic"]

        (self_fx_ts, imp_fx_ts, exp_fx_ts, cost_fx_ts,
         alpha_fx, pu_self_fx, pu_imp_fx,
         p_buy_fx, p_sell_fx) = base_cache["fixed"]
    else:
        logger.info("[2/7] PREPROCESO")
        prepared = prepare_inputs(df_c, df_pv, df_buy, df_sell)
        df       = prepared.df.copy()
        users    = prepared.users

        logger.info("[3/7] VALIDACIÓN")
        issues = validate_prepared_inputs(prepared, strict=cfg.validation.strict)
        errors = [i for i in issues if i.level == "ERROR"]
        if errors:
            for e in errors:
                logger.error(f"  ERROR [{e.code}] {e.message}")
            raise ValueError("Validation failed:\n" + "\n".join(f"[{e.code}] {e.message}" for e in errors))

        df = df.sort_values("Time").reset_index(drop=True)
        df["D_total"] = df[users].sum(axis=1)
        df["G"]       = df["pv_kWh"]
        T = len(df)
        U = len(users)

        if T == 0 or U == 0:
            raise ValueError("Datos vacíos tras preprocess.")

        logger.info("[4/7] CONFIGURACIÓN")
        solver, solver_used = elegir_solver(solver_name, cfg.optimization.solver_fallbacks, logger)
        tee = bool(cfg.optimization.tee)

        b_list_ex, b_of_t_ex   = bloques_ex_ante(df["Time"], updates_per_year)
        b_list_dyn, b_of_t_dyn = calcular_bloques(df["Time"], str(dynamic_block_mode))
        B_ex  = len(b_list_ex)
        B_dyn = len(b_list_dyn)

        logger.info(f"  [4.1] datos: T={T} | U={U} | D_total={df['D_total'].sum():.1f} kWh | G_total={df['G'].sum():.1f} kWh")
        logger.info(f"  [4.2] solver: '{solver_used}' | tee={tee}")
        logger.info(f"  [4.3] ex ante: {B_ex} bloques (updates_per_year={updates_per_year})")
        logger.info(f"  [4.4] dinámico: {B_dyn} bloques (mode='{dynamic_block_mode}')")

        # --- Pre-compute data dicts (shared by all solvers) ---
        datos_ex  = _preparar_datos(df, users, b_of_t_ex)
        datos_dyn = _preparar_datos(df, users, b_of_t_dyn) if b_of_t_dyn != b_of_t_ex else datos_ex

        logger.info("[5/7] OPTIMIZACIÓN EX ANTE")
        (self_ex_ts, imp_ex_ts, exp_ex_ts, cost_ex_ts,
         alpha_ex, pu_self_ex, pu_imp_ex) = resolver_lp(df, users, b_of_t_ex, B_ex, solver, tee, logger, step_num=5, datos=datos_ex)

        logger.info("[6/7] OPTIMIZACIÓN DINÁMICA")
        (self_dyn_ts, imp_dyn_ts, exp_dyn_ts, cost_dyn_ts,
         alpha_dyn, pu_self_dyn, pu_imp_dyn) = resolver_lp(df, users, b_of_t_dyn, B_dyn, solver, tee, logger, step_num=6, datos=datos_dyn)

        logger.info("[6.5/7] REPARTO FIJO PROPORCIONAL (baseline)")
        (self_fx_ts, imp_fx_ts, exp_fx_ts, cost_fx_ts,
         alpha_fx, pu_self_fx, pu_imp_fx,
         p_buy_fx, p_sell_fx) = reparto_fijo(df, users, logger)

    if run_battery:
        bat_cap  = float(battery_cfg.capacity_kwh)
        bat_pow  = float(battery_cfg.power_kw)
        eta_c    = float(battery_cfg.efficiency_charge)
        eta_d    = float(battery_cfg.efficiency_discharge)
        soc_init = float(battery_cfg.initial_soc_fraction) * bat_cap
        logger.info("[6.7/7] OPTIMIZACIÓN DINÁMICA + BATERÍA")
        (self_bat_ts, imp_bat_ts, exp_bat_ts, cost_bat_ts,
         charge_bat_ts, discharge_bat_ts, soc_bat_ts,
         alpha_bat, pu_self_bat, pu_imp_bat) = resolver_lp_bateria(
            df, users, b_of_t_dyn, B_dyn,
            bat_cap, bat_pow, eta_c, eta_d, soc_init,
            solver, tee, logger, step_num=7, datos=datos_dyn,
        )
    else:
        self_bat_ts = imp_bat_ts = exp_bat_ts = cost_bat_ts = []
        charge_bat_ts = discharge_bat_ts = soc_bat_ts = []
        alpha_bat = {}
        pu_self_bat = pu_imp_bat = {}

    cost_ex_ante = float(pd.Series(cost_ex_ts).sum())
    cost_prop    = float(pd.Series(cost_dyn_ts).sum())
    ahorro       = cost_ex_ante - cost_prop
    ahorro_pct   = (ahorro / cost_ex_ante * 100.0) if abs(cost_ex_ante) > 1e-9 else 0.0

    cost_pu_ex:   dict[str, float] = {}
    cost_pu_dyn:  dict[str, float] = {}
    cost_pu_fx:   dict[str, float] = {}
    cost_pu_bat:  dict[str, float] = {}
    self_pu_ex:   dict[str, float] = {}
    self_pu_dyn:  dict[str, float] = {}
    self_pu_fx:   dict[str, float] = {}
    self_pu_bat:  dict[str, float] = {}
    imp_pu_ex:    dict[str, float] = {}
    imp_pu_dyn:   dict[str, float] = {}
    imp_pu_fx:    dict[str, float] = {}
    imp_pu_bat:   dict[str, float] = {}

    cost_fixed = float(pd.Series(cost_fx_ts).sum())

    for i, u_name in enumerate(users):
        u_idx = i + 1
        cost_pu_ex[u_name]  = float(sum(
            float(df.loc[t, "p_buy"])  * pu_imp_ex[u_idx][t]
            - float(df.loc[t, "p_sell"]) * exp_ex_ts[t]  * alpha_ex.get((u_idx,  b_of_t_ex[t + 1]),  0.0)
            for t in range(T)
        ))
        cost_pu_dyn[u_name] = float(sum(
            float(df.loc[t, "p_buy"])  * pu_imp_dyn[u_idx][t]
            - float(df.loc[t, "p_sell"]) * exp_dyn_ts[t] * alpha_dyn.get((u_idx, b_of_t_dyn[t + 1]), 0.0)
            for t in range(T)
        ))
        cost_pu_fx[u_name]  = float(sum(
            float(df.loc[t, "p_buy"]) * pu_imp_fx[u_idx][t]
            - float(df.loc[t, "p_sell"]) * exp_fx_ts[t] * alpha_fx[u_idx]
            for t in range(T)
        ))
        self_pu_ex[u_name]  = float(sum(pu_self_ex[u_idx]))
        self_pu_dyn[u_name] = float(sum(pu_self_dyn[u_idx]))
        self_pu_fx[u_name]  = float(sum(pu_self_fx[u_idx]))
        imp_pu_ex[u_name]   = float(sum(pu_imp_ex[u_idx]))
        imp_pu_dyn[u_name]  = float(sum(pu_imp_dyn[u_idx]))
        imp_pu_fx[u_name]   = float(sum(pu_imp_fx[u_idx]))
        if run_battery and pu_self_bat and pu_imp_bat:
            cost_pu_bat[u_name] = float(sum(
                float(df.loc[t, "p_buy"]) * pu_imp_bat[u_idx][t]
                - float(df.loc[t, "p_sell"]) * exp_bat_ts[t] * alpha_bat.get((u_idx, b_of_t_dyn[t + 1]), 0.0)
                - float(df.loc[t, "p_buy"]) * discharge_bat_ts[t] * (
                    float(df.loc[t, users[i]]) / max(float(df.loc[t, "D_total"]), 1e-9)
                )
                for t in range(T)
            ))
            self_pu_bat[u_name] = float(sum(pu_self_bat[u_idx]))
            imp_pu_bat[u_name]  = float(sum(pu_imp_bat[u_idx]))

    logger.info("[7/7] RESULTADOS")
    logger.info(f"  [7.1] coste ex ante: {cost_ex_ante:.2f} € | coste dinámico: {cost_prop:.2f} € | ahorro: {ahorro:.2f} € ({ahorro_pct:.1f}%)")
    for u_name in users:
        sav_u = cost_pu_ex.get(u_name, 0) - cost_pu_dyn.get(u_name, 0)
        logger.info(f"  [7.2] {u_name}: ex={cost_pu_ex[u_name]:.2f} € | dyn={cost_pu_dyn[u_name]:.2f} € | ahorro={sav_u:.2f} €")

    sum_pu_ex  = sum(cost_pu_ex.values())
    sum_pu_dyn = sum(cost_pu_dyn.values())
    tol_ex  = max(1.0, 0.005 * abs(cost_ex_ante))
    tol_dyn = max(1.0, 0.005 * abs(cost_prop))
    ex_ok  = abs(sum_pu_ex  - cost_ex_ante) <= tol_ex
    dyn_ok = abs(sum_pu_dyn - cost_prop)    <= tol_dyn
    logger.info(
        f"  [7.3] consistencia costes: "
        f"ex ante sum_pu={sum_pu_ex:.2f} vs total={cost_ex_ante:.2f} → {'OK' if ex_ok else f'WARN dif={abs(sum_pu_ex-cost_ex_ante):.2f} €'} | "
        f"dinámico sum_pu={sum_pu_dyn:.2f} vs total={cost_prop:.2f} → {'OK' if dyn_ok else f'WARN dif={abs(sum_pu_dyn-cost_prop):.2f} €'}"
    )
    if not ex_ok:
        logger.warning(f"  consistencia ex ante: sum(cost_per_user)={sum_pu_ex:.2f} ≠ total={cost_ex_ante:.2f} (dif={abs(sum_pu_ex-cost_ex_ante):.2f} €)")
    if not dyn_ok:
        logger.warning(f"  consistencia dinámico: sum(cost_per_user)={sum_pu_dyn:.2f} ≠ total={cost_prop:.2f} (dif={abs(sum_pu_dyn-cost_prop):.2f} €)")

    cost_bat_total = float(pd.Series(cost_bat_ts).sum()) if run_battery and cost_bat_ts else None
    if run_battery and cost_bat_total is not None and cost_pu_bat:
        sum_pu_bat = sum(cost_pu_bat.values())
        tol_bat = max(1.0, 0.005 * abs(cost_bat_total))
        bat_ok = abs(sum_pu_bat - cost_bat_total) <= tol_bat
        logger.info(
            f"  [7.3b] consistencia batería: sum_pu={sum_pu_bat:.2f} vs total={cost_bat_total:.2f} "
            f"→ {'OK' if bat_ok else f'WARN dif={abs(sum_pu_bat-cost_bat_total):.2f} €'}"
        )

    display_names = {}
    for i, u in enumerate(users):
        display_names[u] = f"Usuario {i + 1}"

    alpha_fixed_per_user = {}
    for i in range(U):
        alpha_fixed_per_user[users[i]] = alpha_fx[i + 1]

    summary: dict = {
        "cost_ex_ante":   cost_ex_ante,
        "cost_prop":      cost_prop,
        "ahorro":         ahorro,
        "ahorro_pct":     ahorro_pct,

        "imp_ex_ante":  float(sum(imp_ex_ts)),
        "self_ex_ante": float(sum(self_ex_ts)),
        "exp_ex_ante":  float(sum(exp_ex_ts)),

        "imp_prop":  float(sum(imp_dyn_ts)),
        "self_prop": float(sum(self_dyn_ts)),
        "exp_prop":  float(sum(exp_dyn_ts)),

        "cost_fixed":              cost_fixed,
        "imp_fixed":               float(sum(imp_fx_ts)),
        "self_fixed":              float(sum(self_fx_ts)),
        "exp_fixed":               float(sum(exp_fx_ts)),
        "p_buy_fixed":             p_buy_fx,
        "p_sell_fixed":            p_sell_fx,
        "cost_per_user_fixed":     cost_pu_fx,
        "self_per_user_fixed":     self_pu_fx,
        "imp_per_user_fixed":      imp_pu_fx,
        "alpha_fixed_per_user":    alpha_fixed_per_user,

        "battery_enabled":         run_battery,
        "cost_bat":                cost_bat_total,
        "imp_bat":                 float(sum(imp_bat_ts))  if run_battery and imp_bat_ts  else None,
        "self_bat":                float(sum(self_bat_ts)) if run_battery and self_bat_ts else None,
        "exp_bat":                 float(sum(exp_bat_ts))  if run_battery and exp_bat_ts  else None,
        "charge_bat_total":        float(sum(charge_bat_ts))    if run_battery and charge_bat_ts    else None,
        "discharge_bat_total":     float(sum(discharge_bat_ts)) if run_battery and discharge_bat_ts else None,
        "cost_per_user_bat":       cost_pu_bat if run_battery else {},
        "self_per_user_bat":       self_pu_bat if run_battery else {},
        "imp_per_user_bat":        imp_pu_bat  if run_battery else {},
        "bat_capacity_kwh":        battery_cfg.capacity_kwh  if run_battery else None,
        "bat_power_kw":            battery_cfg.power_kw       if run_battery else None,

        "exante_updates_per_year": int(updates_per_year),
        "dynamic_block_mode":      str(dynamic_block_mode),
        "B_ex":      int(B_ex),
        "B_dynamic": int(B_dyn),
        "solver":    str(solver_used),

        "demand_total": float(df["D_total"].sum()),
        "gen_total":    float(df["G"].sum()),

        "users":              users,
        "user_display_names": display_names,
        "cost_per_user_ex_ante":  cost_pu_ex,
        "cost_per_user_prop":     cost_pu_dyn,
        "self_per_user_ex_ante":  self_pu_ex,
        "self_per_user_prop":     self_pu_dyn,
        "imp_per_user_ex_ante":   imp_pu_ex,
        "imp_per_user_prop":      imp_pu_dyn,
    }

    df_ts = pd.DataFrame({
        "Time":          df["Time"],
        "pv_kWh":        df["G"],
        "demand_kWh":    df["D_total"],
        "p_buy":         df["p_buy"],
        "p_sell":        df["p_sell"],

        "self_ex_ante":  pd.Series(self_ex_ts),
        "imp_ex_ante":   pd.Series(imp_ex_ts),
        "exp_ex_ante":   pd.Series(exp_ex_ts),
        "cost_ex_ante":  pd.Series(cost_ex_ts),

        "self_prop":     pd.Series(self_dyn_ts),
        "imp_prop":      pd.Series(imp_dyn_ts),
        "exp_prop":      pd.Series(exp_dyn_ts),
        "cost_prop":     pd.Series(cost_dyn_ts),

        "self_fixed":    pd.Series(self_fx_ts),
        "imp_fixed":     pd.Series(imp_fx_ts),
        "exp_fixed":     pd.Series(exp_fx_ts),
        "cost_fixed":    pd.Series(cost_fx_ts),
    })
    df_ts["cost_ex_ante_cum"] = df_ts["cost_ex_ante"].cumsum()
    df_ts["cost_prop_cum"]    = df_ts["cost_prop"].cumsum()
    df_ts["cost_fixed_cum"]   = df_ts["cost_fixed"].cumsum()

    if run_battery and cost_bat_ts:
        df_ts["self_bat"]    = pd.Series(self_bat_ts)
        df_ts["imp_bat"]     = pd.Series(imp_bat_ts)
        df_ts["exp_bat"]     = pd.Series(exp_bat_ts)
        df_ts["cost_bat"]    = pd.Series(cost_bat_ts)
        df_ts["charge_bat"]  = pd.Series(charge_bat_ts)
        df_ts["disch_bat"]   = pd.Series(discharge_bat_ts)
        df_ts["soc_bat"]     = pd.Series(soc_bat_ts)
        df_ts["cost_bat_cum"] = df_ts["cost_bat"].cumsum()

    extra_cols = {}
    for i, u_name in enumerate(users):
        u_idx = i + 1
        s     = f"u{u_idx}"
        extra_cols[f"self_ex_{s}"]   = pu_self_ex[u_idx]
        extra_cols[f"imp_ex_{s}"]    = pu_imp_ex[u_idx]
        extra_cols[f"self_prop_{s}"] = pu_self_dyn[u_idx]
        extra_cols[f"imp_prop_{s}"]  = pu_imp_dyn[u_idx]
        extra_cols[f"self_fx_{s}"]   = pu_self_fx[u_idx]
        extra_cols[f"imp_fx_{s}"]    = pu_imp_fx[u_idx]
        extra_cols[f"alpha_ex_{s}"]   = [alpha_ex.get((u_idx,  b_of_t_ex[t + 1]),  0.0) for t in range(T)]
        extra_cols[f"alpha_prop_{s}"] = [alpha_dyn.get((u_idx, b_of_t_dyn[t + 1]), 0.0) for t in range(T)]
        extra_cols[f"alpha_fx_{s}"]   = [alpha_fx[u_idx]] * T  # constante
        if run_battery and pu_self_bat and u_idx in pu_self_bat:
            extra_cols[f"self_bat_{s}"]   = pu_self_bat[u_idx]
            extra_cols[f"imp_bat_{s}"]    = pu_imp_bat[u_idx]
            extra_cols[f"alpha_bat_{s}"]  = [alpha_bat.get((u_idx, b_of_t_dyn[t + 1]), 0.0) for t in range(T)]

    df_ts = pd.concat([df_ts, pd.DataFrame(extra_cols, index=df_ts.index)], axis=1)

    out_base_cache = {
        # Infrastructure (steps 2-4)
        "df": df, "users": users, "T": T, "U": U,
        "b_of_t_ex": b_of_t_ex, "B_ex": B_ex,
        "b_of_t_dyn": b_of_t_dyn, "B_dyn": B_dyn,
        "solver": solver, "solver_used": solver_used, "tee": tee,
        "datos_dyn": datos_dyn,
        # Solver results (steps 5, 6, 6.5)
        "ex_ante": (self_ex_ts, imp_ex_ts, exp_ex_ts, cost_ex_ts,
                    alpha_ex, pu_self_ex, pu_imp_ex),
        "dynamic": (self_dyn_ts, imp_dyn_ts, exp_dyn_ts, cost_dyn_ts,
                    alpha_dyn, pu_self_dyn, pu_imp_dyn),
        "fixed":   (self_fx_ts, imp_fx_ts, exp_fx_ts, cost_fx_ts,
                    alpha_fx, pu_self_fx, pu_imp_fx,
                    p_buy_fx, p_sell_fx),
    }

    return summary, df_ts, out_base_cache
