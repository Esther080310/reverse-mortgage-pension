"""Extended analyses for the revised annuity-style product prototype."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter

from liability_model import (
    ProductAssumptions,
    default_segment_assumptions,
    load_life_table,
    profile_seed,
    solve_monthly_pmt,
    SOLVE_SIMS,
)

plt.rcParams["font.sans-serif"] = [
    "Arial Unicode MS",
    "PingFang SC",
    "SimHei",
    "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False

OUTPUT_DIR = Path("outputs")
FIGURE_DIR = OUTPUT_DIR / "figures"
ES95_TARGET_SHORTFALL_RATE = 0.01
N_SIMS = SOLVE_SIMS

SEGMENT_LABELS = {
    "huangpu_small": "黄浦老破小",
    "minhang_mid": "闵行改善型",
    "jinshan_small": "金山老破小",
}


def money(value: float) -> str:
    return f"{value:,.0f}"


def percent(value: float) -> str:
    return f"{value:.2%}"


def build_assumptions(segment: str, seed: int, **updates: object) -> ProductAssumptions:
    base = asdict(default_segment_assumptions(segment))
    base.update(
        {
            "n_sims": N_SIMS,
            "seed": seed,
            "draw_policy": "guaranteed_annuity",
            "use_ratchet": False,
        }
    )
    base.update(updates)
    return ProductAssumptions(**base)


def solve_guaranteed(
    assumptions: ProductAssumptions, life: pd.DataFrame
) -> tuple[float, object]:
    return solve_monthly_pmt(
        assumptions,
        life=life,
        target_shortfall_rate=ES95_TARGET_SHORTFALL_RATE,
        risk_measure="es95",
        max_expected_present_value_rate=assumptions.initial_ltv,
        tolerance=5.0,
        max_iterations=24,
    )


def run_joint_life_analysis(life: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    scenario_id = 0
    for segment in SEGMENT_LABELS:
        for mortality_improvement in [0.0, 0.15]:
            scenario_id += 1
            seed = profile_seed(segment, "Female", 70, mortality_improvement)
            single = build_assumptions(
                segment,
                seed,
                sex="Female",
                start_age=70,
                mortality_improvement=mortality_improvement,
                joint_life=False,
            )
            couple = build_assumptions(
                segment,
                seed,
                sex="Female",
                start_age=68,
                spouse_sex="Male",
                spouse_start_age=70,
                mortality_improvement=mortality_improvement,
                joint_life=True,
            )
            single_pmt, single_summary = solve_guaranteed(single, life)
            couple_pmt, couple_summary = solve_guaranteed(couple, life)
            rows.append(
                {
                    "scenario_id": scenario_id,
                    "segment": segment,
                    "segment_label": SEGMENT_LABELS[segment],
                    "mortality_improvement": mortality_improvement,
                    "single_case": "女性70岁",
                    "joint_case": "女性68岁+男性70岁，最后生存者清算",
                    "single_monthly_pmt": single_pmt,
                    "single_shortfall_es95_rate": single_summary.shortfall_es95_rate,
                    "joint_monthly_pmt": couple_pmt,
                    "joint_shortfall_es95_rate": couple_summary.shortfall_es95_rate,
                    "joint_mean_settlement_age_primary": couple_summary.mean_death_age,
                    "pmt_reduction_rate": (
                        1.0 - couple_pmt / single_pmt if single_pmt else 0.0
                    ),
                }
            )
            print(
                f"[JOINT {scenario_id:02d}] {segment}: "
                f"single={single_pmt:,.0f}, joint={couple_pmt:,.0f}"
            )
    return pd.DataFrame(rows)


def run_cost_liquidity_sensitivity(life: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    scenario_id = 0
    for segment_index, segment in enumerate(SEGMENT_LABELS, start=1):
        paired_seed = profile_seed(segment, "Female", 70, 0.0)
        for cost in [0.005, 0.010, 0.015]:
            for discount in [0.05, 0.10, 0.15, 0.20]:
                scenario_id += 1
                assumptions = build_assumptions(
                    segment,
                    paired_seed,
                    sex="Female",
                    start_age=70,
                    mortality_improvement=0.0,
                    annual_cost_rate=cost,
                    liquidity_discount=discount,
                )
                pmt, summary = solve_guaranteed(assumptions, life)
                rows.append(
                    {
                        "scenario_id": scenario_id,
                        "segment": segment,
                        "segment_label": SEGMENT_LABELS[segment],
                        "sex": assumptions.sex,
                        "start_age": assumptions.start_age,
                        "annual_cost_rate": cost,
                        "liquidity_discount": discount,
                        "solved_monthly_pmt": pmt,
                        "shortfall_probability": summary.shortfall_probability,
                        "shortfall_var95_rate": summary.shortfall_var95_rate,
                        "shortfall_es95_rate": summary.shortfall_es95_rate,
                        "expected_present_value_draw_rate": summary.expected_present_value_drawn
                        / assumptions.property_value,
                    }
                )
                print(
                    f"[COST {scenario_id:02d}] {segment} cost={cost:.1%} "
                    f"discount={discount:.0%}: pmt={pmt:,.0f}"
                )
    return pd.DataFrame(rows)


def simulate_crisis_path(
    segment: str = "minhang_mid",
    monthly_pmt: float = 8_000.0,
    shock_month: int = 120,
    shock_drop: float = 0.30,
    recovery_rate: float = 0.01,
) -> pd.DataFrame:
    assumptions = default_segment_assumptions(segment)
    months = 30 * 12
    dt = 1.0 / 12.0
    house = assumptions.property_value
    guaranteed_debt = 0.0
    adjustable_debt = 0.0
    initial_limit = assumptions.property_value * assumptions.initial_ltv
    adjustable_limit = initial_limit
    monthly_rate = (
        1.0 + assumptions.initial_rate + assumptions.annual_cost_rate
    ) ** dt - 1.0
    rows: list[dict] = []

    for month in range(1, months + 1):
        if month == shock_month:
            house *= 1.0 - shock_drop
        elif month > shock_month:
            house *= 1.0 + recovery_rate * dt
        else:
            house *= 1.0 + assumptions.g_H_P * dt

        guaranteed_debt *= 1.0 + monthly_rate
        adjustable_debt *= 1.0 + monthly_rate

        if month % 12 == 0 and adjustable_debt / house > assumptions.ratchet_trigger_ltv:
            adjustable_limit = max(
                min(adjustable_limit, assumptions.initial_ltv * house),
                assumptions.ratchet_floor_ratio * initial_limit,
            )

        guaranteed_draw = monthly_pmt
        adjustable_draw = min(
            monthly_pmt, max(adjustable_limit - adjustable_debt, 0.0)
        )
        guaranteed_debt += guaranteed_draw
        adjustable_debt += adjustable_draw
        rows.append(
            {
                "month": month,
                "year": month / 12.0,
                "house_value": house,
                "adjustable_credit_limit": adjustable_limit,
                "guaranteed_debt": guaranteed_debt,
                "adjustable_debt": adjustable_debt,
                "guaranteed_draw": guaranteed_draw,
                "adjustable_draw": adjustable_draw,
                "ratchet_triggered": adjustable_limit < initial_limit,
                "adjustable_draw_cut": adjustable_draw < monthly_pmt,
            }
        )
    return pd.DataFrame(rows)


def plot_crisis(df: pd.DataFrame, path: Path) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    axes[0].plot(df["year"], df["house_value"], label="房屋价值", linewidth=2)
    axes[0].plot(
        df["year"],
        df["adjustable_credit_limit"],
        label="动态调额授信额度",
        linestyle="--",
    )
    axes[0].set_ylabel("金额（万元）")
    axes[0].set_title("房价压力下两种给付责任的现金流差异")
    axes[0].legend()
    axes[0].grid(alpha=0.25)

    axes[1].plot(
        df["year"], df["guaranteed_debt"], label="保证给付债务余额", linewidth=2
    )
    axes[1].plot(
        df["year"], df["adjustable_debt"], label="动态调额债务余额", linewidth=2
    )
    cut = df[df["adjustable_draw_cut"]]
    if not cut.empty:
        axes[1].axvline(
            cut["year"].iloc[0],
            color="#c00000",
            linestyle="--",
            label="动态调额首次少付",
        )
    axes[1].set_xlabel("经过年数")
    axes[1].set_ylabel("金额（万元）")
    axes[1].legend()
    axes[1].grid(alpha=0.25)
    for axis in axes:
        axis.axvline(10, color="#7f7f7f", linestyle=":", alpha=0.8)
        axis.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value / 1e4:,.0f}"))
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180)
    plt.close(fig)


def write_joint_markdown(df: pd.DataFrame, path: Path) -> None:
    lines = [
        "# 夫妻双生命保证给付年金分析",
        "",
        "夫妻情景按最后生存者清算。月领结果同时受存续期和ES95约束影响。",
        "",
        "| 场景 | 长寿压力 | 单人月领 | 夫妻月领 | 月领下降 | 夫妻ES95/H0 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for _, row in df.iterrows():
        lines.append(
            f"| {row['segment_label']} | {percent(row['mortality_improvement'])} | "
            f"{money(row['single_monthly_pmt'])} | {money(row['joint_monthly_pmt'])} | "
            f"{percent(row['pmt_reduction_rate'])} | "
            f"{percent(row['joint_shortfall_es95_rate'])} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_cost_markdown(df: pd.DataFrame, path: Path) -> None:
    lines = [
        "# 保证给付年金的成本与流动性敏感性",
        "",
        "| 场景 | 成本率 | 清算折价 | 月领 | 短缺概率 | VaR95/H0 | ES95/H0 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for _, row in df.iterrows():
        lines.append(
            f"| {row['segment_label']} | {percent(row['annual_cost_rate'])} | "
            f"{percent(row['liquidity_discount'])} | {money(row['solved_monthly_pmt'])} | "
            f"{percent(row['shortfall_probability'])} | "
            f"{percent(row['shortfall_var95_rate'])} | "
            f"{percent(row['shortfall_es95_rate'])} |"
        )
    lines.extend(
        [
            "",
            "VaR95为95%分位损失；ES95为最差5%路径平均损失。本表不将任一指标直接解释为保费或监管资本。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_crisis_markdown(df: pd.DataFrame, path: Path) -> None:
    first_trigger = df.loc[df["ratchet_triggered"], "year"].min()
    first_cut = df.loc[df["adjustable_draw_cut"], "year"].min()
    trigger_text = "未触发" if np.isnan(first_trigger) else f"约第{first_trigger:.2f}年"
    cut_text = "未发生" if np.isnan(first_cut) else f"约第{first_cut:.2f}年"
    lines = [
        "# 房价危机路径：保证给付与动态调额对比",
        "",
        "确定性情景：闵行改善型房产第10年一次性下跌30%，随后每年恢复1%，名义月领8000元。",
        "",
        "![压力路径](figures/house_crisis_ratchet_trigger.png)",
        "",
        f"- 70% D/H触发棘轮：{trigger_text}。",
        f"- 动态调额首次少付：{cut_text}。",
        "- 保证给付方案持续支付8000元，尾部缺口由未来确定的风险承担主体承接；动态调额方案以老人现金流下降换取债务控制。",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    life = load_life_table()
    joint = run_joint_life_analysis(life)
    cost = run_cost_liquidity_sensitivity(life)
    crisis = simulate_crisis_path()
    joint.to_csv(
        OUTPUT_DIR / "liability_joint_life_official_cl1_2025.csv",
        index=False,
        encoding="utf-8-sig",
    )
    cost.to_csv(
        OUTPUT_DIR / "liability_cost_liquidity_sensitivity_official_cl1_2025.csv",
        index=False,
        encoding="utf-8-sig",
    )
    crisis.to_csv(
        OUTPUT_DIR / "liability_house_crisis_ratchet_path.csv",
        index=False,
        encoding="utf-8-sig",
    )
    plot_crisis(crisis, FIGURE_DIR / "house_crisis_ratchet_trigger.png")
    write_joint_markdown(
        joint, OUTPUT_DIR / "liability_joint_life_official_cl1_2025.md"
    )
    write_cost_markdown(
        cost,
        OUTPUT_DIR / "liability_cost_liquidity_sensitivity_official_cl1_2025.md",
    )
    write_crisis_markdown(
        crisis, OUTPUT_DIR / "liability_house_crisis_ratchet_path.md"
    )
    print("Joint-life, cost/liquidity, and crisis outputs completed.")


if __name__ == "__main__":
    main()
