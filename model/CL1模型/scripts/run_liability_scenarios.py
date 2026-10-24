"""Run the paper-ready liability scenarios under two contract designs."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pandas as pd

from liability_model import (
    ProductAssumptions,
    default_segment_assumptions,
    load_life_table,
    profile_seed,
    simulate_liability_paths,
    solve_monthly_pmt,
    summarize_results,
    SOLVE_SIMS,
    FIXED_STRESS_SIMS,
)


OUTPUT_DIR = Path("outputs")
FIXED_MONTHLY_PMT = 8_000.0
ES95_TARGET_SHORTFALL_RATE = 0.01
MAX_STOPPED_DRAW_PROBABILITY = 0.05
N_SIMS_FIXED = FIXED_STRESS_SIMS
N_SIMS_SOLVE = SOLVE_SIMS
N_SIMS_SENSITIVITY = SOLVE_SIMS  # 统一到 4000（原 3000 与主表 4000 不一致致同画像跨表冲突）
LTV_SENSITIVITY_LEVELS = [0.40, 0.50, 0.60]

SEGMENT_LABELS = {
    "huangpu_small": "黄浦老破小",
    "minhang_mid": "闵行改善型",
    "jinshan_small": "金山老破小",
}


def build_assumptions(
    segment: str,
    sex: str,
    mortality_improvement: float,
    n_sims: int,
    seed: int,
    draw_policy: str,
    initial_ltv: float | None = None,
    use_ratchet: bool | None = None,
) -> ProductAssumptions:
    base = asdict(default_segment_assumptions(segment))
    base.update(
        {
            "sex": sex,
            "mortality_improvement": mortality_improvement,
            "n_sims": n_sims,
            "seed": seed,
            "draw_policy": draw_policy,
        }
    )
    if initial_ltv is not None:
        base["initial_ltv"] = initial_ltv
    if use_ratchet is not None:
        base["use_ratchet"] = use_ratchet
    return ProductAssumptions(**base)


def solve_guaranteed(
    assumptions: ProductAssumptions,
    life: pd.DataFrame,
) -> tuple[float, object]:
    """Solve a guaranteed annuity under ES95 and origination PV constraints."""
    return solve_monthly_pmt(
        assumptions,
        life=life,
        target_shortfall_rate=ES95_TARGET_SHORTFALL_RATE,
        risk_measure="es95",
        max_expected_present_value_rate=assumptions.initial_ltv,
        tolerance=5.0,
        max_iterations=24,
    )


def solve_adjustable(
    assumptions: ProductAssumptions,
    life: pd.DataFrame,
) -> tuple[float, object]:
    """Solve the adjustable-draw extension under ES95 and stop constraints."""
    return solve_monthly_pmt(
        assumptions,
        life=life,
        target_shortfall_rate=ES95_TARGET_SHORTFALL_RATE,
        risk_measure="es95",
        max_stopped_draw_probability=MAX_STOPPED_DRAW_PROBABILITY,
        tolerance=5.0,
        max_iterations=24,
    )


def summary_fields(prefix: str, summary: object) -> dict[str, float]:
    return {
        f"{prefix}_expected_shortfall": summary.expected_shortfall,
        f"{prefix}_shortfall_probability": summary.shortfall_probability,
        f"{prefix}_conditional_expected_shortfall": summary.conditional_expected_shortfall,
        f"{prefix}_shortfall_var95": summary.shortfall_var95,
        f"{prefix}_shortfall_es95": summary.shortfall_es95,
        f"{prefix}_expected_shortfall_rate": summary.expected_shortfall_rate,
        f"{prefix}_shortfall_var95_rate": summary.shortfall_var95_rate,
        f"{prefix}_shortfall_es95_rate": summary.shortfall_es95_rate,
        f"{prefix}_expected_total_drawn": summary.expected_total_drawn,
        f"{prefix}_expected_present_value_drawn": summary.expected_present_value_drawn,
        f"{prefix}_expected_actual_monthly_draw": summary.expected_actual_monthly_draw,
        f"{prefix}_stopped_draw_probability": summary.stopped_draw_probability,
        f"{prefix}_mean_settlement_age": summary.mean_death_age,
    }


def run_all_scenarios() -> pd.DataFrame:
    life = load_life_table()
    rows: list[dict] = []
    scenario_id = 0

    for segment in SEGMENT_LABELS:
        for sex in ["Male", "Female"]:
            for mortality_improvement in [0.0, 0.15]:
                scenario_id += 1
                seed = profile_seed(segment, sex, 70, mortality_improvement)
                guaranteed_fixed = build_assumptions(
                    segment,
                    sex,
                    mortality_improvement,
                    N_SIMS_FIXED,
                    seed,
                    "guaranteed_annuity",
                    use_ratchet=False,
                )
                fixed_paths = simulate_liability_paths(
                    FIXED_MONTHLY_PMT, guaranteed_fixed, life
                )
                fixed_summary = summarize_results(
                    fixed_paths, FIXED_MONTHLY_PMT, guaranteed_fixed
                )

                guaranteed = build_assumptions(
                    segment,
                    sex,
                    mortality_improvement,
                    N_SIMS_SOLVE,
                    seed,
                    "guaranteed_annuity",
                    use_ratchet=False,
                )
                guaranteed_pmt, guaranteed_summary = solve_guaranteed(guaranteed, life)

                adjustable = build_assumptions(
                    segment,
                    sex,
                    mortality_improvement,
                    N_SIMS_SOLVE,
                    seed,
                    "adjustable_draw",
                    use_ratchet=True,
                )
                adjustable_pmt, adjustable_summary = solve_adjustable(adjustable, life)

                row = {
                    "scenario_id": scenario_id,
                    "segment": segment,
                    "segment_label": SEGMENT_LABELS[segment],
                    "sex": sex,
                    "start_age": guaranteed.start_age,
                    "mortality_improvement": mortality_improvement,
                    "mortality_improvement_note": (
                        "本文统一下调qx 15%的静态长寿压力情景"
                        if mortality_improvement
                        else "官方CL1基准qx"
                    ),
                    "property_value": guaranteed.property_value,
                    "annual_house_vol": guaranteed.annual_house_vol,
                    "annual_rent_yield": guaranteed.annual_rent_yield,
                    "g_H_P": guaranteed.g_H_P,
                    "house_shock_model": guaranteed.house_shock_model,
                    "fixed_guaranteed_monthly_pmt": FIXED_MONTHLY_PMT,
                    "guaranteed_solved_monthly_pmt": guaranteed_pmt,
                    "guaranteed_pv_budget_rate": guaranteed.initial_ltv,
                    "adjustable_solved_monthly_pmt": adjustable_pmt,
                    "adjustable_ratchet_trigger_ltv": adjustable.ratchet_trigger_ltv,
                    "adjustable_ratchet_floor_ratio": adjustable.ratchet_floor_ratio,
                }
                row.update(summary_fields("fixed_guaranteed", fixed_summary))
                row.update(summary_fields("guaranteed_solved", guaranteed_summary))
                row.update(summary_fields("adjustable_solved", adjustable_summary))
                rows.append(row)

                print(
                    f"[{scenario_id:02d}] {segment} {sex} mi={mortality_improvement}: "
                    f"guaranteed={guaranteed_pmt:,.0f}, "
                    f"adjustable={adjustable_pmt:,.0f}"
                )

    return pd.DataFrame(rows)


def run_ltv_sensitivity() -> pd.DataFrame:
    life = load_life_table()
    rows: list[dict] = []
    scenario_id = 0
    comparison_group = 0

    for segment in SEGMENT_LABELS:
        for sex in ["Male", "Female"]:
            for mortality_improvement in [0.0, 0.15]:
                comparison_group += 1
                paired_seed = profile_seed(segment, sex, 70, mortality_improvement)
                for ltv in LTV_SENSITIVITY_LEVELS:
                    scenario_id += 1
                    common = {
                        "segment": segment,
                        "sex": sex,
                        "mortality_improvement": mortality_improvement,
                        "n_sims": N_SIMS_SENSITIVITY,
                        "seed": paired_seed,
                        "initial_ltv": ltv,
                    }
                    guaranteed = build_assumptions(
                        **common,
                        draw_policy="guaranteed_annuity",
                        use_ratchet=False,
                    )
                    adjustable = build_assumptions(
                        **common,
                        draw_policy="adjustable_draw",
                        use_ratchet=True,
                    )
                    guaranteed_pmt, guaranteed_summary = solve_guaranteed(
                        guaranteed, life
                    )
                    adjustable_pmt, adjustable_summary = solve_adjustable(
                        adjustable, life
                    )
                    rows.append(
                        {
                            "scenario_id": scenario_id,
                            "segment": segment,
                            "segment_label": SEGMENT_LABELS[segment],
                            "sex": sex,
                            "mortality_improvement": mortality_improvement,
                            "initial_ltv": ltv,
                            "property_value": guaranteed.property_value,
                            "guaranteed_monthly_pmt": guaranteed_pmt,
                            "guaranteed_shortfall_probability": guaranteed_summary.shortfall_probability,
                            "guaranteed_shortfall_var95_rate": guaranteed_summary.shortfall_var95_rate,
                            "guaranteed_shortfall_es95_rate": guaranteed_summary.shortfall_es95_rate,
                            "guaranteed_expected_pv_draw_rate": guaranteed_summary.expected_present_value_drawn
                            / guaranteed.property_value,
                            "adjustable_monthly_pmt": adjustable_pmt,
                            "adjustable_actual_monthly_draw": adjustable_summary.expected_actual_monthly_draw,
                            "adjustable_shortfall_probability": adjustable_summary.shortfall_probability,
                            "adjustable_shortfall_es95_rate": adjustable_summary.shortfall_es95_rate,
                            "adjustable_stopped_draw_probability": adjustable_summary.stopped_draw_probability,
                        }
                    )
                    print(
                        f"[LTV {scenario_id:02d}] {segment} {sex} ltv={ltv:.0%}: "
                        f"guaranteed={guaranteed_pmt:,.0f}, "
                        f"adjustable={adjustable_pmt:,.0f}"
                    )
    return pd.DataFrame(rows)


def run_ratchet_comparison() -> pd.DataFrame:
    life = load_life_table()
    rows: list[dict] = []
    scenario_id = 0
    comparison_group = 0

    for segment in SEGMENT_LABELS:
        for sex in ["Male", "Female"]:
            for mortality_improvement in [0.0, 0.15]:
                comparison_group += 1
                paired_seed = profile_seed(segment, sex, 70, mortality_improvement)
                for use_ratchet in [True, False]:
                    scenario_id += 1
                    assumptions = build_assumptions(
                        segment,
                        sex,
                        mortality_improvement,
                        N_SIMS_SENSITIVITY,
                        paired_seed,
                        "adjustable_draw",
                        initial_ltv=0.50,
                        use_ratchet=use_ratchet,
                    )
                    fixed_paths = simulate_liability_paths(
                        FIXED_MONTHLY_PMT, assumptions, life
                    )
                    fixed_summary = summarize_results(
                        fixed_paths, FIXED_MONTHLY_PMT, assumptions
                    )
                    solved_pmt, solved_summary = solve_adjustable(assumptions, life)
                    rows.append(
                        {
                            "scenario_id": scenario_id,
                            "segment": segment,
                            "segment_label": SEGMENT_LABELS[segment],
                            "sex": sex,
                            "mortality_improvement": mortality_improvement,
                            "use_ratchet": use_ratchet,
                            "ratchet_trigger_ltv": assumptions.ratchet_trigger_ltv,
                            "ratchet_floor_ratio": assumptions.ratchet_floor_ratio,
                            "property_value": assumptions.property_value,
                            "fixed_monthly_pmt": FIXED_MONTHLY_PMT,
                            "fixed_actual_monthly_draw": fixed_summary.expected_actual_monthly_draw,
                            "fixed_shortfall_probability": fixed_summary.shortfall_probability,
                            "fixed_shortfall_es95_rate": fixed_summary.shortfall_es95_rate,
                            "fixed_stopped_draw_probability": fixed_summary.stopped_draw_probability,
                            "solved_monthly_pmt": solved_pmt,
                            "solved_actual_monthly_draw": solved_summary.expected_actual_monthly_draw,
                            "solved_shortfall_probability": solved_summary.shortfall_probability,
                            "solved_shortfall_es95_rate": solved_summary.shortfall_es95_rate,
                            "solved_stopped_draw_probability": solved_summary.stopped_draw_probability,
                        }
                    )
                    print(
                        f"[RATCHET {scenario_id:02d}] {segment} {sex} "
                        f"ratchet={use_ratchet}: solved={solved_pmt:,.0f}"
                    )
    return pd.DataFrame(rows)


def format_currency(value: float) -> str:
    return f"{value:,.0f}"


def format_percent(value: float) -> str:
    return f"{value:.2%}"


def write_markdown_summary(df: pd.DataFrame, path: Path) -> None:
    lines = [
        "# 负债端情景分析结果汇总",
        "",
        "本表比较两种合同责任。主产品“保证给付年金”不允许停付，以 ES95/H0≤1% 和预期给付现值/H0≤初始LTV反解月领；扩展产品“动态调额提款”允许按合同规则降额，以 ES95/H0≤1% 和路径截断概率≤5%反解名义额度。结果属于研究情景，不是商业报价。",
        "",
        "| 场景 | 性别 | 长寿压力 | 房产初值 | 保证给付月领 | 保证给付ES95/H0 | 保证给付短缺概率 | 动态调额名义月领 | 动态调额实际月均 | 动态调额截断概率 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for _, row in df.iterrows():
        lines.append(
            "| "
            f"{row['segment_label']} | {row['sex']} | "
            f"{format_percent(row['mortality_improvement'])} | "
            f"{format_currency(row['property_value'])} | "
            f"{format_currency(row['guaranteed_solved_monthly_pmt'])} | "
            f"{format_percent(row['guaranteed_solved_shortfall_es95_rate'])} | "
            f"{format_percent(row['guaranteed_solved_shortfall_probability'])} | "
            f"{format_currency(row['adjustable_solved_monthly_pmt'])} | "
            f"{format_currency(row['adjustable_solved_expected_actual_monthly_draw'])} | "
            f"{format_percent(row['adjustable_solved_stopped_draw_probability'])} |"
        )
    best = df.loc[df["guaranteed_solved_monthly_pmt"].idxmax()]
    worst = df.loc[df["guaranteed_solved_monthly_pmt"].idxmin()]
    lines.extend(
        [
            "",
            "## 解释边界",
            "",
            f"- 保证给付年金的最高情景为{best['segment_label']}、{best['sex']}、长寿压力{format_percent(best['mortality_improvement'])}，月领约{format_currency(best['guaranteed_solved_monthly_pmt'])}元。",
            f"- 最低情景为{worst['segment_label']}、{worst['sex']}、长寿压力{format_percent(worst['mortality_improvement'])}，月领约{format_currency(worst['guaranteed_solved_monthly_pmt'])}元。",
            "- VaR95是95%分位数，ES95是最差5%路径损失的平均值；二者不得混用。",
            "- “死亡率改善15%”是本文把各年龄qx统一下调15%的静态压力情景，并非官方CL1字段或正式死亡率改善模型。",
            "- 保证给付方案的尾部损失需要由未来确定的风险承担主体承接；本模型不预设由信托公司单独承担。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_ltv_markdown(df: pd.DataFrame, path: Path) -> None:
    lines = [
        "# LTV敏感性分析",
        "",
        "保证给付年金中，LTV表示签约时允许配置给付承诺的现值预算比例；动态调额提款中，LTV表示授信上限。两种含义分开报告。",
        "",
        "| 场景 | 性别 | 长寿压力 | LTV | 保证给付月领 | 保证给付ES95/H0 | 动态调额名义月领 | 动态调额实际月均 | 动态调额截断概率 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for _, row in df.iterrows():
        lines.append(
            f"| {row['segment_label']} | {row['sex']} | "
            f"{format_percent(row['mortality_improvement'])} | "
            f"{format_percent(row['initial_ltv'])} | "
            f"{format_currency(row['guaranteed_monthly_pmt'])} | "
            f"{format_percent(row['guaranteed_shortfall_es95_rate'])} | "
            f"{format_currency(row['adjustable_monthly_pmt'])} | "
            f"{format_currency(row['adjustable_actual_monthly_draw'])} | "
            f"{format_percent(row['adjustable_stopped_draw_probability'])} |"
        )
    lines.extend(
        [
            "",
            "LTV提高通常增加可配置的给付预算或授信空间，但不等于风险消失；应与ES95、损失概率和消费者现金流连续性共同解释。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_ratchet_markdown(df: pd.DataFrame, path: Path) -> None:
    lines = [
        "# 动态调额提款的棘轮机制对比",
        "",
        "本表只用于动态调额提款扩展方案。保证给付年金不因授信重估而停付。棘轮按年检查：仅当D/H>70%时下调授信，且授信不低于初始额度的70%。两项均为待行业访谈校验的本文设计参数。",
        "",
        "| 场景 | 性别 | 长寿压力 | 棘轮 | 固定8000实际月均 | 固定8000截断概率 | 反解名义月领 | 反解实际月均 | ES95/H0 | 反解截断概率 |",
        "| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for _, row in df.iterrows():
        lines.append(
            f"| {row['segment_label']} | {row['sex']} | "
            f"{format_percent(row['mortality_improvement'])} | "
            f"{'开启' if row['use_ratchet'] else '关闭'} | "
            f"{format_currency(row['fixed_actual_monthly_draw'])} | "
            f"{format_percent(row['fixed_stopped_draw_probability'])} | "
            f"{format_currency(row['solved_monthly_pmt'])} | "
            f"{format_currency(row['solved_actual_monthly_draw'])} | "
            f"{format_percent(row['solved_shortfall_es95_rate'])} | "
            f"{format_percent(row['solved_stopped_draw_probability'])} |"
        )
    lines.extend(
        [
            "",
            "棘轮体现机构风险与老人现金流之间的取舍，不能用于证明保证给付年金能够终身稳定支付。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    scenarios = run_all_scenarios()
    ltv = run_ltv_sensitivity()
    ratchet = run_ratchet_comparison()

    scenarios.to_csv(
        OUTPUT_DIR / "liability_scenario_comparison_official_cl1_2025.csv",
        index=False,
        encoding="utf-8-sig",
    )
    ltv.to_csv(
        OUTPUT_DIR / "liability_ltv_sensitivity_official_cl1_2025.csv",
        index=False,
        encoding="utf-8-sig",
    )
    ratchet.to_csv(
        OUTPUT_DIR / "liability_ratchet_comparison_official_cl1_2025.csv",
        index=False,
        encoding="utf-8-sig",
    )
    write_markdown_summary(
        scenarios,
        OUTPUT_DIR / "liability_scenario_summary_official_cl1_2025.md",
    )
    write_ltv_markdown(
        ltv, OUTPUT_DIR / "liability_ltv_sensitivity_official_cl1_2025.md"
    )
    write_ratchet_markdown(
        ratchet,
        OUTPUT_DIR / "liability_ratchet_comparison_official_cl1_2025.md",
    )
    print("Scenario, LTV, and ratchet outputs completed.")


if __name__ == "__main__":
    main()
