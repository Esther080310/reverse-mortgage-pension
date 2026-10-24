# -*- coding: utf-8 -*-
"""CL1 利率敏感性 runner（专业修订版回灌，2026-10-20）。

对保证给付年金主模型跑两组 CIR 参数敏感性实验：
  - initial_rate_only：仅改初始短率 r0（θ=2.22% 固定）
  - theta_only：仅改长期中枢 θ（r0=1.22% 固定）
避免旧版"同时改 r0 与 θ 却称固定利率"的口径混淆。
约束：ES95(shortfall)/H0<=1% 且 E[PV(draw)]/H0<=初始LTV。
路径自动探测（兼容交接包布局 利率runner/↔CL1模型/ 与 live 工作区布局），从任意电脑运行无需手改 BASE。
结果写 outputs/cl1_rate_sensitivity_wang65_gHP0.csv + _cl1_rate_sweep.txt。
"""
from __future__ import annotations

import os
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd

# 自动探测 CL1 模型目录：候选1=交接包布局(本脚本在 利率runner/、与 CL1模型/ 同级)；
# 候选2=live 工作区布局(本脚本在工作区根)。命中含 scripts/liability_model.py 的目录即用。
_HERE = Path(__file__).resolve()
_CANDIDATES = [
    _HERE.parents[1] / "CL1模型",
    _HERE.parents[0] / "房价数据和建模" / "负债端最终结果汇总_官方CL1_2025",
]
BASE = next((str(p) for p in _CANDIDATES if (p / "scripts" / "liability_model.py").is_file()), None)
if BASE is None:
    raise FileNotFoundError("未找到 CL1 模型目录：利率runner/ 应与 CL1模型/ 同级，或脚本置于工作区根目录。")
os.chdir(BASE)
sys.path.insert(0, os.path.join(BASE, "scripts"))

from liability_model import (  # noqa: E402
    ProductAssumptions,
    default_segment_assumptions,
    load_life_table,
    profile_seed,
    solve_monthly_pmt,
    SOLVE_SIMS,
)

N_SIMS = SOLVE_SIMS
# 与统计验证/主表口径统一：老王（黄浦男65）唯一权威种子，
# 保证利率基准（theta_only@2.22%）==统计基准==老王头条数，消除旧版 2194 vs 2265 矛盾。
SEED = profile_seed("huangpu_small", "Male", 65, 0.0)
life = load_life_table(os.path.join(BASE, "official_cl1_life_table_2025.csv"))


def make(initial_rate: float, theta: float) -> ProductAssumptions:
    base = asdict(default_segment_assumptions("huangpu_small"))
    base.update(
        {
            "sex": "Male",
            "start_age": 65,
            "initial_ltv": 0.50,
            "n_sims": N_SIMS,
            "seed": SEED,
            "drift_mode": "gHP",
            "g_H_P": 0.0,
            "initial_rate": initial_rate,
            "cir_theta": theta,
            "draw_policy": "guaranteed_annuity",
            "use_ratchet": False,
        }
    )
    return ProductAssumptions(**base)


def solve(assumptions: ProductAssumptions) -> tuple[float, object]:
    return solve_monthly_pmt(
        assumptions,
        life=life,
        target_shortfall_rate=0.01,
        risk_measure="es95",
        max_expected_present_value_rate=assumptions.initial_ltv,
        tolerance=5.0,
        max_iterations=24,
    )


rows: list[dict] = []
lines: list[str] = []
for experiment, rates in [
    ("initial_rate_only", [0.0100, 0.0122, 0.0150, 0.0200, 0.0222, 0.0250, 0.0300, 0.0350]),
    ("theta_only", [0.0100, 0.0122, 0.0150, 0.0200, 0.0222, 0.0250, 0.0300, 0.0350]),
]:
    for value in rates:
        initial_rate = value if experiment == "initial_rate_only" else 0.0122
        theta = value if experiment == "theta_only" else 0.0222
        assumptions = make(initial_rate, theta)
        pmt, summary = solve(assumptions)
        rows.append(
            {
                "experiment": experiment,
                "initial_rate": initial_rate,
                "cir_theta": theta,
                "guaranteed_monthly_pmt": pmt,
                "shortfall_probability": summary.shortfall_probability,
                "shortfall_var95_rate": summary.shortfall_var95_rate,
                "shortfall_es95_rate": summary.shortfall_es95_rate,
                "expected_present_value_draw_rate": summary.expected_present_value_drawn
                / assumptions.property_value,
                "mean_settlement_age": summary.mean_death_age,
            }
        )
        line = (
            f"{experiment} value={value:.2%}: PMT={pmt:,.0f}, "
            f"ES95/H0={summary.shortfall_es95_rate:.3%}"
        )
        lines.append(line)
        print(line, flush=True)

output = os.path.join(BASE, "outputs", "cl1_rate_sensitivity_wang65_gHP0.csv")
pd.DataFrame(rows).to_csv(output, index=False, encoding="utf-8-sig")
with open(os.path.join(BASE, "_cl1_rate_sweep.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print("CL1 SWEEP OK ->", output)
