"""Statistical uncertainty and robustness checks for the main prototype."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from liability_model import (
    ProductAssumptions,
    default_segment_assumptions,
    load_life_table,
    profile_seed,
    solve_monthly_pmt,
    SOLVE_SIMS,
)


OUTPUT_DIR = Path("outputs")
N_SIMS = SOLVE_SIMS
# 老王（黄浦男65 LTV50 g_H^P=0% 保证给付）的唯一权威种子，与利率runner/主表口径一致。
CANONICAL_SEED = profile_seed("huangpu_small", "Male", 65, 0.0)
# 五种子里第一个即权威点估计，其余四个用于展示蒙特卡洛随机性区间。
SEEDS = [CANONICAL_SEED + k for k in range(5)]


def assumptions_for(
    seed: int,
    annual_house_vol: float | None = None,
    g_h_p: float = 0.0,
    house_shock_model: str = "normal_mixture",
) -> ProductAssumptions:
    base = asdict(default_segment_assumptions("huangpu_small"))
    base.update(
        {
            "sex": "Male",
            "start_age": 65,
            "initial_ltv": 0.50,
            "n_sims": N_SIMS,
            "seed": seed,
            "g_H_P": g_h_p,
            "house_shock_model": house_shock_model,
            "draw_policy": "guaranteed_annuity",
            "use_ratchet": False,
        }
    )
    if annual_house_vol is not None:
        base["annual_house_vol"] = annual_house_vol
    return ProductAssumptions(**base)


def solve(assumptions: ProductAssumptions, life: pd.DataFrame) -> tuple[float, object]:
    return solve_monthly_pmt(
        assumptions,
        life=life,
        target_shortfall_rate=0.01,
        risk_measure="es95",
        max_expected_present_value_rate=assumptions.initial_ltv,
        tolerance=5.0,
        max_iterations=24,
    )


def run_seed_stability(life: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for seed in SEEDS:
        assumptions = assumptions_for(seed)
        pmt, summary = solve(assumptions, life)
        probability_se = np.sqrt(
            summary.shortfall_probability
            * (1.0 - summary.shortfall_probability)
            / N_SIMS
        )
        rows.append(
            {
                "seed": seed,
                "n_sims": N_SIMS,
                "monthly_pmt": pmt,
                "shortfall_probability": summary.shortfall_probability,
                "shortfall_probability_mc_se": probability_se,
                "shortfall_var95_rate": summary.shortfall_var95_rate,
                "shortfall_es95_rate": summary.shortfall_es95_rate,
                "expected_present_value_draw_rate": summary.expected_present_value_drawn
                / assumptions.property_value,
            }
        )
        print(f"[SEED] {seed}: PMT={pmt:,.0f}")
    return pd.DataFrame(rows)


def run_specification_sensitivity(life: pd.DataFrame) -> pd.DataFrame:
    specifications = [
        ("baseline_mixture_sigma11", 0.11, 0.00, "normal_mixture"),
        ("gaussian_sigma11", 0.11, 0.00, "gaussian"),
        ("volatility_lower_bound5", 0.05, 0.00, "normal_mixture"),
        ("volatility_upper_bound18", 0.18, 0.00, "normal_mixture"),
        ("negative_drift_minus1", 0.11, -0.01, "normal_mixture"),
        ("positive_drift_plus2", 0.11, 0.02, "normal_mixture"),
    ]
    rows: list[dict] = []
    for index, (name, volatility, drift, shock_model) in enumerate(specifications):
        # 所有规格共用权威种子（配对），使规格间差异只反映分布/参数假设、不混入种子噪声。
        assumptions = assumptions_for(
            CANONICAL_SEED,
            annual_house_vol=volatility,
            g_h_p=drift,
            house_shock_model=shock_model,
        )
        pmt, summary = solve(assumptions, life)
        rows.append(
            {
                "specification": name,
                "annual_house_vol": volatility,
                "g_H_P": drift,
                "house_shock_model": shock_model,
                "monthly_pmt": pmt,
                "shortfall_probability": summary.shortfall_probability,
                "shortfall_var95_rate": summary.shortfall_var95_rate,
                "shortfall_es95_rate": summary.shortfall_es95_rate,
                "expected_present_value_draw_rate": summary.expected_present_value_drawn
                / assumptions.property_value,
            }
        )
        print(f"[SPEC] {name}: PMT={pmt:,.0f}")
    return pd.DataFrame(rows)


def write_report(seed_df: pd.DataFrame, spec_df: pd.DataFrame, path: Path) -> None:
    pmt_mean = seed_df["monthly_pmt"].mean()
    pmt_sd = seed_df["monthly_pmt"].std(ddof=1)
    pmt_half_width = 2.776 * pmt_sd / np.sqrt(len(seed_df))
    lines = [
        "# 统计不确定性与稳健性验证",
        "",
        "验证对象：黄浦老破小、男性65岁、LTV 50%、保证给付年金。所有规格均事先设定，不按结果筛选。",
        "",
        "## 1. 多随机种子稳定性",
        "",
        "| 随机种子 | 路径数 | 月领 | 短缺概率 | 概率MC标准误 | VaR95/H0 | ES95/H0 |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for _, row in seed_df.iterrows():
        lines.append(
            f"| {int(row['seed'])} | {int(row['n_sims'])} | "
            f"{row['monthly_pmt']:,.0f} | {row['shortfall_probability']:.2%} | "
            f"{row['shortfall_probability_mc_se']:.2%} | "
            f"{row['shortfall_var95_rate']:.2%} | "
            f"{row['shortfall_es95_rate']:.2%} |"
        )
    lines.extend(
        [
            "",
            f"- 五个种子的月领均值为{pmt_mean:,.0f}元，种子间标准差为{pmt_sd:,.0f}元。",
            f"- 基于五次独立反解的t区间，月领均值95%区间约为[{pmt_mean - pmt_half_width:,.0f}, {pmt_mean + pmt_half_width:,.0f}]元。该区间只反映蒙特卡洛随机性，不包含参数估计误差。",
            "",
            "## 2. 替代规格与参数压力",
            "",
            "| 规格 | 年波动率 | 房价漂移 | 冲击模型 | 月领 | 短缺概率 | VaR95/H0 | ES95/H0 |",
            "| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for _, row in spec_df.iterrows():
        lines.append(
            f"| {row['specification']} | {row['annual_house_vol']:.2%} | "
            f"{row['g_H_P']:.2%} | {row['house_shock_model']} | "
            f"{row['monthly_pmt']:,.0f} | {row['shortfall_probability']:.2%} | "
            f"{row['shortfall_var95_rate']:.2%} | "
            f"{row['shortfall_es95_rate']:.2%} |"
        )
    lines.extend(
        [
            "",
            "## 3. 解释边界",
            "",
            "- 波动率5%与18%来自当前小样本估计区间的近似上下界，只作为参数压力，不是新的点估计。",
            "- 正态混合与高斯规格用于检验尾部分布假设敏感性；确定性房价骤跌另见危机路径表。",
            "- 这些结果不能替代外部样本验证，也不能直接转换为正式保费、资本或报价。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    life = load_life_table()
    seed_df = run_seed_stability(life)
    spec_df = run_specification_sensitivity(life)
    seed_df.to_csv(
        OUTPUT_DIR / "statistical_seed_stability.csv",
        index=False,
        encoding="utf-8-sig",
    )
    spec_df.to_csv(
        OUTPUT_DIR / "statistical_specification_sensitivity.csv",
        index=False,
        encoding="utf-8-sig",
    )
    write_report(
        seed_df,
        spec_df,
        OUTPUT_DIR / "统计不确定性与稳健性验证.md",
    )
    print("Statistical validation outputs completed.")


if __name__ == "__main__":
    main()
