"""Actuarial cash-flow and risk model for the annuity-style product prototype.

The model reads the official 2025 CL1 pension-business life table and simulates
settlement time, collateral value, debt, non-recourse shortfall, and residual
bequest. It supports two contract designs:

* guaranteed_annuity: the promised monthly benefit is never credit-limited;
* adjustable_draw: payments may be reduced by a disclosed credit-limit rule.

This is a physical-measure (P-measure) scenario model, not a fair-value or
risk-neutral option-pricing engine.
"""

from __future__ import annotations

import argparse
import csv
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


LIFE_TABLE_FILE = "official_cl1_life_table_2025.csv"

# 统一求解路径数与种子方案（2026-10-20 修订）：所有表对同一画像使用同一路径数
# 与 profile_seed，保证"同一老人"在主表/LTV表/棘轮表/利率表/统计基准中数字一致，
# 消除旧版"主表4000路径 vs LTV表3000路径、各表种子基不同"导致的同画像跨表冲突。
SOLVE_SIMS = 4_000
FIXED_STRESS_SIMS = 10_000


def profile_seed(
    segment: str, sex: str, start_age: int, mortality_improvement: float
) -> int:
    """Deterministic canonical seed for a (segment, sex, age, mortality) profile.

    Uses zlib.crc32 (stable across processes, unlike Python's built-in hash which
    is salted per process) so every table reproduces identical Monte-Carlo paths
    for the same profile. Tables that vary one parameter (ltv/ratchet/cost/rate)
    keep this seed fixed to obtain common-random-number paired comparisons.
    """
    key = (
        f"{segment}|{sex}|{start_age}|{round(float(mortality_improvement), 4)}"
    ).encode("utf-8")
    return 20260000 + int(zlib.crc32(key) % 1_000_000)


@dataclass(frozen=True)
class ProductAssumptions:
    sex: str = "Female"
    start_age: int = 70
    property_value: float = 5_000_000.0
    annual_house_vol: float = 0.0357
    annual_rent_yield: float = 0.0183
    # 无风险短率初值 r₀ = 中债官方 1Y 现券到期收益率(2026-03)=1.22%。
    initial_rate: float = 0.0122
    pricing_discount_rate: float | None = None
    annual_cost_rate: float = 0.010
    liquidity_discount: float = 0.10
    initial_ltv: float = 0.50
    max_age: int = 110
    mortality_improvement: float = 0.0
    n_sims: int = 10_000
    seed: int = 20260706

    # CIR 短率参数：由中债官方 1Y 国债到期收益率月末序列(2008-01~2026-03,219月)
    # 以 AR(1)/OU 校准：κ=-ln(b)/dt=0.572(半衰期1.21年)、θ=a/(1-b)=2.22%(长期中枢)、
    # σ_r=std(resid)/√(r̄·dt)=0.051。来源:房价数据和建模/国债收益率_月末_200801_202603.csv。
    # ρ(房价收益×利率变动)经同数据实测≈0且统计不显著(|t|<2)，故 z_house 与 z_rate 独立抽取。
    cir_kappa: float = 0.572
    cir_theta: float = 0.0222
    cir_sigma: float = 0.051

    # 房价漂移测度（选项2 / 参数治理定案）：
    #   drift_mode="gHP"（默认主模型）：dH/H = g_H^P·dt + σ_H·dW^P，用独立标定的
    #     物理测度P名义房价增值率 g_H^P，利率仅通过债务累积(r+c)渠道起作用。
    #   drift_mode="rq"（对照）：dH/H = (r−q)dt + σ_H·dW，为风险中性Q测度估值关系，
    #     仅留作对照，不用于对外真实世界风险约束结论。
    # g_H_P 名义基准=0%（暂定审慎定价基准，政策情景假设非统计预测）；压力档 −1%、
    #   上行敏感性 +2%/+4% 由 run 脚本以覆写方式产出。
    drift_mode: str = "gHP"
    g_H_P: float = 0.0

    # A finite-MGF normal mixture supplies fat tails while preserving unit
    # innovation variance. The stress component occurs with probability 5%
    # and has three times the base-component standard deviation.
    house_shock_model: str = "normal_mixture"
    tail_mixture_probability: float = 0.05
    tail_scale_multiplier: float = 3.0

    # Contract design. The main product guarantees the promised monthly
    # annuity. The adjustable extension may reduce draws under a credit rule.
    draw_policy: str = "guaranteed_annuity"

    # Adjustable-draw ratchet: annual reassessment, triggered only when D/H
    # exceeds 70%, with a floor at 70% of the initial credit limit.
    use_ratchet: bool = True
    ratchet_trigger_ltv: float = 0.70
    ratchet_floor_ratio: float = 0.70

    # Joint-life mode: settlement happens at the last survivor's death.
    joint_life: bool = False
    spouse_sex: str = "Male"
    spouse_start_age: int | None = None


@dataclass(frozen=True)
class SimulationSummary:
    monthly_pmt: float
    n_sims: int
    mean_death_age: float
    median_death_age: float
    p90_death_age: float
    expected_debt: float
    expected_total_drawn: float
    expected_present_value_drawn: float
    expected_actual_monthly_draw: float
    expected_net_house_value: float
    expected_shortfall: float
    shortfall_probability: float
    conditional_expected_shortfall: float
    shortfall_var95: float
    shortfall_es95: float
    expected_bequest: float
    stopped_draw_probability: float
    expected_shortfall_rate: float
    conditional_shortfall_rate: float
    shortfall_var95_rate: float
    shortfall_es95_rate: float


def load_life_table(path: str | Path = LIFE_TABLE_FILE) -> pd.DataFrame:
    """Load and validate the life table used by the liability model."""
    life = pd.read_csv(path)
    required = {"sex", "age", "qx", "px", "lx", "dx", "ex", "mortality_improvement"}
    missing = required.difference(life.columns)
    if missing:
        raise ValueError(f"Life table missing columns: {sorted(missing)}")
    life = life.copy()
    life["sex"] = life["sex"].astype(str)
    life["age"] = life["age"].astype(int)
    life["qx"] = life["qx"].astype(float).clip(0.0, 1.0)
    life["mortality_improvement"] = life["mortality_improvement"].astype(float)
    return life


def select_life_curve(life: pd.DataFrame, assumptions: ProductAssumptions) -> pd.DataFrame:
    """Select one sex and mortality-improvement scenario from the life table."""
    return select_life_curve_by_values(
        life,
        sex=assumptions.sex,
        start_age=assumptions.start_age,
        max_age=assumptions.max_age,
        mortality_improvement=assumptions.mortality_improvement,
    )


def select_life_curve_by_values(
    life: pd.DataFrame,
    sex: str,
    start_age: int,
    max_age: int,
    mortality_improvement: float,
) -> pd.DataFrame:
    """Select one sex, age, and mortality-improvement scenario from the life table."""
    sub = life[
        (life["sex"].str.lower() == sex.lower())
        & np.isclose(life["mortality_improvement"], mortality_improvement)
        & (life["age"] >= start_age)
        & (life["age"] <= max_age)
    ].sort_values("age")
    if sub.empty:
        raise ValueError(
            "No life-table rows match "
            f"sex={sex!r}, start_age={start_age}, "
            f"mortality_improvement={mortality_improvement}."
        )
    return sub.reset_index(drop=True)


def monthly_mortality_schedule(life_curve: pd.DataFrame) -> np.ndarray:
    """Convert annual qx values to a monthly conditional death probability path."""
    qx = life_curve["qx"].to_numpy(dtype=float)
    month_probs: list[float] = []
    for annual_qx in qx:
        if annual_qx >= 1.0:
            # Terminal age: distribute certain death uniformly across the year.
            month_probs.extend([1.0 / remaining for remaining in range(12, 0, -1)])
        else:
            q_month = 1.0 - np.power(1.0 - annual_qx, 1.0 / 12.0)
            month_probs.extend([float(q_month)] * 12)
    return np.array(month_probs, dtype=float)


def sample_death_months(q_month: np.ndarray, n_sims: int, rng: np.random.Generator) -> np.ndarray:
    """Sample death months from a monthly conditional mortality schedule."""
    max_months = len(q_month)
    death_month = np.full(n_sims, max_months, dtype=int)
    alive = np.ones(n_sims, dtype=bool)
    for month in range(1, max_months + 1):
        q = q_month[month - 1]
        active = np.flatnonzero(alive)
        if active.size == 0:
            break
        died_this_month = rng.random(active.size) < q
        if month == max_months:
            died_this_month[:] = True
        died = active[died_this_month]
        if died.size:
            death_month[died] = month
            alive[died] = False
    return death_month


def settlement_months_from_life_table(
    life: pd.DataFrame,
    assumptions: ProductAssumptions,
    rng: np.random.Generator,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Sample settlement months for single-life or joint last-survivor contracts."""
    primary_curve = select_life_curve(life, assumptions)
    primary_schedule = monthly_mortality_schedule(primary_curve)
    primary_death = sample_death_months(primary_schedule, assumptions.n_sims, rng)

    if not assumptions.joint_life:
        return primary_death, {"primary_death_month": primary_death}

    spouse_start_age = assumptions.spouse_start_age
    if spouse_start_age is None:
        spouse_start_age = assumptions.start_age
    spouse_curve = select_life_curve_by_values(
        life,
        sex=assumptions.spouse_sex,
        start_age=spouse_start_age,
        max_age=assumptions.max_age,
        mortality_improvement=assumptions.mortality_improvement,
    )
    spouse_schedule = monthly_mortality_schedule(spouse_curve)
    spouse_death = sample_death_months(spouse_schedule, assumptions.n_sims, rng)
    settlement_month = np.maximum(primary_death, spouse_death)
    return settlement_month, {
        "primary_death_month": primary_death,
        "spouse_death_month": spouse_death,
    }


def _house_log_growth(
    rng: np.random.Generator,
    drift: np.ndarray,
    annual_vol: float,
    dt: float,
    assumptions: ProductAssumptions,
) -> np.ndarray:
    """Sample one-period log growth with an explicit finite MGF correction."""
    scale = annual_vol * np.sqrt(dt)
    if assumptions.house_shock_model == "gaussian":
        z = rng.standard_normal(drift.size)
        log_mgf = 0.5 * scale**2
    elif assumptions.house_shock_model == "normal_mixture":
        probability = assumptions.tail_mixture_probability
        multiplier = assumptions.tail_scale_multiplier
        if not 0.0 < probability < 1.0:
            raise ValueError("tail_mixture_probability must be between 0 and 1.")
        if multiplier <= 1.0:
            raise ValueError("tail_scale_multiplier must exceed 1.")
        variance_scale = (1.0 - probability) + probability * multiplier**2
        base_sd = 1.0 / np.sqrt(variance_scale)
        tail_sd = multiplier / np.sqrt(variance_scale)
        component_sd = np.where(rng.random(drift.size) < probability, tail_sd, base_sd)
        z = rng.standard_normal(drift.size) * component_sd
        log_mgf = np.log(
            (1.0 - probability) * np.exp(0.5 * (scale * base_sd) ** 2)
            + probability * np.exp(0.5 * (scale * tail_sd) ** 2)
        )
    else:
        raise ValueError(
            f"Unsupported house_shock_model={assumptions.house_shock_model!r}."
        )
    return drift * dt + scale * z - log_mgf


def simulate_liability_paths(
    monthly_pmt: float,
    assumptions: ProductAssumptions,
    life: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Run Monte Carlo paths for death time, debt, collateral, and shortfall."""
    if monthly_pmt < 0:
        raise ValueError("monthly_pmt must be non-negative.")
    if assumptions.draw_policy not in {"guaranteed_annuity", "adjustable_draw"}:
        raise ValueError(
            "draw_policy must be 'guaranteed_annuity' or 'adjustable_draw'."
        )

    life = load_life_table() if life is None else life
    dt = 1.0 / 12.0
    rng = np.random.default_rng(assumptions.seed)
    settlement_month, mortality_details = settlement_months_from_life_table(life, assumptions, rng)
    max_months = int(settlement_month.max())

    n = assumptions.n_sims
    house = np.full(n, assumptions.property_value, dtype=float)
    rate = np.full(n, assumptions.initial_rate, dtype=float)
    debt = np.zeros(n, dtype=float)
    credit_limit = np.full(n, assumptions.property_value * assumptions.initial_ltv, dtype=float)
    stopped_draw = np.zeros(n, dtype=bool)

    final_month = settlement_month.copy()
    final_debt = np.zeros(n, dtype=float)
    final_house = np.zeros(n, dtype=float)
    final_rate = np.zeros(n, dtype=float)
    total_drawn = np.zeros(n, dtype=float)
    present_value_drawn = np.zeros(n, dtype=float)
    pricing_rate = (
        assumptions.initial_rate
        if assumptions.pricing_discount_rate is None
        else assumptions.pricing_discount_rate
    )

    for month in range(1, max_months + 1):
        active = np.flatnonzero(settlement_month >= month)
        if active.size == 0:
            break

        # The baseline assumes independent innovations. This is a scenario
        # assumption supported by the current sample, not proof of independence.
        z_rate = rng.standard_normal(active.size)

        current_rate = rate[active]
        cir_drift = assumptions.cir_kappa * (assumptions.cir_theta - current_rate) * dt
        cir_diffusion = assumptions.cir_sigma * np.sqrt(np.maximum(current_rate, 0.0)) * np.sqrt(dt) * z_rate
        current_rate = np.maximum(current_rate + cir_drift + cir_diffusion, 0.0)
        rate[active] = current_rate

        if assumptions.drift_mode == "rq":
            house_drift = current_rate - assumptions.annual_rent_yield
        else:
            house_drift = np.full(active.size, assumptions.g_H_P)
        house_growth = _house_log_growth(
            rng,
            house_drift,
            assumptions.annual_house_vol,
            dt,
            assumptions,
        )
        house[active] *= np.exp(house_growth)

        monthly_accumulation_rate = np.power(1.0 + current_rate + assumptions.annual_cost_rate, dt) - 1.0
        debt[active] *= 1.0 + monthly_accumulation_rate

        if (
            assumptions.draw_policy == "adjustable_draw"
            and assumptions.use_ratchet
            and month % 12 == 0
        ):
            debt_to_house = np.divide(
                debt[active],
                house[active],
                out=np.full(active.size, np.inf),
                where=house[active] > 0,
            )
            triggered = debt_to_house > assumptions.ratchet_trigger_ltv
            if np.any(triggered):
                triggered_paths = active[triggered]
                initial_limit = assumptions.property_value * assumptions.initial_ltv
                candidate_limit = np.minimum(
                    credit_limit[triggered_paths],
                    assumptions.initial_ltv * house[triggered_paths],
                )
                credit_limit[triggered_paths] = np.maximum(
                    candidate_limit,
                    assumptions.ratchet_floor_ratio * initial_limit,
                )

        if assumptions.draw_policy == "guaranteed_annuity":
            draw = np.full(active.size, monthly_pmt, dtype=float)
        else:
            allowed_draw = np.maximum(credit_limit[active] - debt[active], 0.0)
            draw = np.minimum(monthly_pmt, allowed_draw)
        debt[active] += draw
        total_drawn[active] += draw
        present_value_drawn[active] += draw / np.power(1.0 + pricing_rate, month * dt)
        if assumptions.draw_policy == "adjustable_draw":
            stopped_draw[active] |= draw < monthly_pmt * (1.0 - 1e-10)

        settled = active[settlement_month[active] == month]
        if settled.size:
            final_debt[settled] = debt[settled]
            final_house[settled] = house[settled]
            final_rate[settled] = rate[settled]

    liquidation_value = final_house * (1.0 - assumptions.liquidity_discount)
    shortfall = np.maximum(final_debt - liquidation_value, 0.0)
    bequest = np.maximum(liquidation_value - final_debt, 0.0)

    result = pd.DataFrame(
        {
            "death_month": final_month,
            "death_age": assumptions.start_age + final_month / 12.0,
            "settlement_month": final_month,
            "settlement_age": assumptions.start_age + final_month / 12.0,
            "primary_death_month": mortality_details["primary_death_month"],
            "primary_death_age": assumptions.start_age + mortality_details["primary_death_month"] / 12.0,
            "debt_at_death": final_debt,
            "total_drawn": total_drawn,
            "present_value_drawn": present_value_drawn,
            "actual_monthly_draw": np.divide(total_drawn, final_month, out=np.zeros_like(total_drawn), where=final_month > 0),
            "house_value_at_death": final_house,
            "net_house_value_at_death": liquidation_value,
            "shortfall": shortfall,
            "bequest": bequest,
            "rate_at_death": final_rate,
            "stopped_draw": stopped_draw,
        }
    )
    if assumptions.joint_life:
        spouse_start_age = assumptions.spouse_start_age if assumptions.spouse_start_age is not None else assumptions.start_age
        result["spouse_death_month"] = mortality_details["spouse_death_month"]
        result["spouse_death_age"] = spouse_start_age + mortality_details["spouse_death_month"] / 12.0
    return result


def summarize_results(paths: pd.DataFrame, monthly_pmt: float, assumptions: ProductAssumptions) -> SimulationSummary:
    """Create a compact actuarial risk summary."""
    losses = paths["shortfall"].to_numpy(dtype=float)
    expected_shortfall = float(losses.mean())
    positive_losses = losses[losses > 0]
    conditional_expected_shortfall = (
        float(positive_losses.mean()) if positive_losses.size else 0.0
    )
    shortfall_var95 = float(np.quantile(losses, 0.95, method="higher"))
    tail_count = max(1, int(np.ceil(0.05 * losses.size)))
    shortfall_es95 = float(np.partition(losses, losses.size - tail_count)[-tail_count:].mean())
    denominator = max(assumptions.property_value, 1.0)
    return SimulationSummary(
        monthly_pmt=float(monthly_pmt),
        n_sims=int(len(paths)),
        mean_death_age=float(paths["death_age"].mean()),
        median_death_age=float(paths["death_age"].median()),
        p90_death_age=float(paths["death_age"].quantile(0.90)),
        expected_debt=float(paths["debt_at_death"].mean()),
        expected_total_drawn=float(paths["total_drawn"].mean()),
        expected_present_value_drawn=float(paths["present_value_drawn"].mean()),
        expected_actual_monthly_draw=float(paths["actual_monthly_draw"].mean()),
        expected_net_house_value=float(paths["net_house_value_at_death"].mean()),
        expected_shortfall=expected_shortfall,
        shortfall_probability=float((losses > 0).mean()),
        conditional_expected_shortfall=conditional_expected_shortfall,
        shortfall_var95=shortfall_var95,
        shortfall_es95=shortfall_es95,
        expected_bequest=float(paths["bequest"].mean()),
        stopped_draw_probability=float(paths["stopped_draw"].mean()),
        expected_shortfall_rate=expected_shortfall / denominator,
        conditional_shortfall_rate=conditional_expected_shortfall / denominator,
        shortfall_var95_rate=shortfall_var95 / denominator,
        shortfall_es95_rate=shortfall_es95 / denominator,
    )


def solve_monthly_pmt(
    assumptions: ProductAssumptions,
    life: pd.DataFrame | None = None,
    target_shortfall_rate: float = 0.0,
    risk_measure: str = "expected",
    max_stopped_draw_probability: float | None = None,
    max_expected_present_value_rate: float | None = None,
    tolerance: float = 1.0,
    max_iterations: int = 40,
) -> tuple[float, SimulationSummary]:
    """Find the largest monthly payment that satisfies a shortfall constraint.

    risk_measure can be "expected", "var95", "es95", or "conditional".
    The target is expressed as a fraction of the initial property value.
    """
    life = load_life_table() if life is None else life
    target = assumptions.property_value * target_shortfall_rate

    def metric(pmt: float) -> tuple[float, SimulationSummary]:
        paths = simulate_liability_paths(pmt, assumptions, life)
        summary = summarize_results(paths, pmt, assumptions)
        values = {
            "expected": summary.expected_shortfall,
            "var95": summary.shortfall_var95,
            "es95": summary.shortfall_es95,
            "conditional": summary.conditional_expected_shortfall,
        }
        if risk_measure not in values:
            raise ValueError(f"Unsupported risk_measure={risk_measure!r}.")
        value = values[risk_measure]
        return value, summary

    def feasible(value: float, summary: SimulationSummary) -> bool:
        if value > target:
            return False
        if max_stopped_draw_probability is not None:
            if summary.stopped_draw_probability > max_stopped_draw_probability:
                return False
        if max_expected_present_value_rate is not None:
            present_value_limit = (
                assumptions.property_value * max_expected_present_value_rate
            )
            if summary.expected_present_value_drawn > present_value_limit:
                return False
        return True

    low = 0.0
    high = assumptions.property_value * assumptions.initial_ltv / 12.0
    last_summary: SimulationSummary | None = None

    while True:
        value, last_summary = metric(high)
        if not feasible(value, last_summary) or high > assumptions.property_value:
            break
        low = high
        high *= 2.0

    for _ in range(max_iterations):
        mid = (low + high) / 2.0
        value, last_summary = metric(mid)
        if abs(high - low) <= tolerance:
            break
        if feasible(value, last_summary):
            low = mid
        else:
            high = mid

    value, last_summary = metric(low)
    return low, last_summary


def default_segment_assumptions(segment: str) -> ProductAssumptions:
    """Convenience presets matching the documented Shanghai asset-side matrix."""
    presets = {
        # σ_H 采用 gotohui 上海区级年度均价(2011-2020)实测波动率四舍五入：
        # 黄浦10.97%→11%、闵行12.86%→13%、金山13.85%→14%，并被安居客城市全周期
        # 年度σ=13.24%独立印证。属本文设计值(方案A分层标注)，非官方发布口径。
        # 尾部由有限矩母函数的正态混合分布与确定性压力情景补偿。
        # q 采用一房一万2026.3上海各区租金回报率(截至2026.3.22,有出处)分区值，
        # 叠加户型微调(本文设计参数): 老破小+0.10pp、改善型-0.10pp。
        # 黄浦1.76%+0.10=1.86%、闵行1.98%-0.10=1.88%、金山2.29%+0.10=2.39%。
        # q 为对照 (r−q) 用途保留；g_H^P 主模型下 q 退出定价漂移，仅作净租金参考。
        # g_H_P 名义基准=0%（统一, 政策情景假设）；压力 −1% / 上行 +2/+4% 由 run 脚本覆写。
        # 清算折价 ψ 分区值（本文设计，参考易居研究院议价空间与成交周期资金成本）：
        # 核心区流动性好折价低、远郊接盘少折价高。此前 presets 漏设 liquidity_discount
        # 致三区均落到 dataclass 默认 10%，与白皮书 8%/10%/15% 不一致；2026-10-20 修复入码。
        "huangpu_small": dict(property_value=10.1e4 * 70, annual_house_vol=0.11, annual_rent_yield=0.0186, liquidity_discount=0.08, g_H_P=0.0),
        "minhang_mid": dict(property_value=4.9e4 * 110, annual_house_vol=0.13, annual_rent_yield=0.0188, liquidity_discount=0.10, g_H_P=0.0),
        "jinshan_small": dict(property_value=1.4e4 * 70, annual_house_vol=0.14, annual_rent_yield=0.0239, liquidity_discount=0.15, g_H_P=0.0),
    }
    if segment not in presets:
        raise ValueError(f"Unknown segment {segment!r}. Choose from {sorted(presets)}.")
    return ProductAssumptions(**presets[segment])


def write_summary_csv(path: Path, summaries: Iterable[SimulationSummary]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [asdict(s) for s in summaries]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run liability-side reverse mortgage simulations.")
    parser.add_argument("--life-table", default=LIFE_TABLE_FILE)
    parser.add_argument("--segment", default="minhang_mid", choices=["huangpu_small", "minhang_mid", "jinshan_small"])
    parser.add_argument("--sex", default=None, choices=["Male", "Female"])
    parser.add_argument("--start-age", type=int, default=None)
    parser.add_argument("--property-value", type=float, default=None)
    parser.add_argument("--monthly-pmt", type=float, default=None)
    parser.add_argument("--solve", action="store_true", help="Solve maximum monthly PMT under the shortfall target.")
    parser.add_argument("--target-shortfall-rate", type=float, default=0.0)
    parser.add_argument(
        "--risk-measure",
        default="expected",
        choices=["expected", "var95", "es95", "conditional"],
    )
    parser.add_argument("--max-stopped-draw-probability", type=float, default=None)
    parser.add_argument("--max-expected-present-value-rate", type=float, default=None)
    parser.add_argument(
        "--draw-policy",
        default=None,
        choices=["guaranteed_annuity", "adjustable_draw"],
    )
    parser.add_argument("--mortality-improvement", type=float, default=None)
    parser.add_argument("--n-sims", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--output", default="outputs/liability_summary.csv")
    return parser.parse_args()


def with_overrides(base: ProductAssumptions, args: argparse.Namespace) -> ProductAssumptions:
    updates = asdict(base)
    for arg_name, field_name in [
        ("sex", "sex"),
        ("start_age", "start_age"),
        ("property_value", "property_value"),
        ("mortality_improvement", "mortality_improvement"),
        ("n_sims", "n_sims"),
        ("seed", "seed"),
        ("draw_policy", "draw_policy"),
    ]:
        value = getattr(args, arg_name)
        if value is not None:
            updates[field_name] = value
    return ProductAssumptions(**updates)


def main() -> None:
    args = parse_args()
    assumptions = with_overrides(default_segment_assumptions(args.segment), args)
    life = load_life_table(args.life_table)

    if args.solve:
        pmt, summary = solve_monthly_pmt(
            assumptions,
            life=life,
            target_shortfall_rate=args.target_shortfall_rate,
            risk_measure=args.risk_measure,
            max_stopped_draw_probability=args.max_stopped_draw_probability,
            max_expected_present_value_rate=args.max_expected_present_value_rate,
        )
    else:
        pmt = args.monthly_pmt if args.monthly_pmt is not None else 8_000.0
        paths = simulate_liability_paths(pmt, assumptions, life)
        summary = summarize_results(paths, pmt, assumptions)

    output = Path(args.output)
    write_summary_csv(output, [summary])

    print("Liability model completed")
    print(f"segment={args.segment}, sex={assumptions.sex}, start_age={assumptions.start_age}")
    print(f"monthly_pmt={summary.monthly_pmt:,.2f}")
    print(f"expected_shortfall={summary.expected_shortfall:,.2f}")
    print(f"shortfall_probability={summary.shortfall_probability:.2%}")
    print(f"shortfall_es95_rate={summary.shortfall_es95_rate:.2%}")
    print(f"output={output.resolve()}")


if __name__ == "__main__":
    main()
