# -*- coding: utf-8 -*-
"""model_api.py —— 给外部后端/前端的稳定调用入口（唯一权威算法出口）。

用途：让"定制测算"的每一个数字都**真实跑模型**得出，禁止前端自创公式/插值/缩放。
输入任意画像（分区或自定义房价、性别、年龄、LTV、漂移、合同类型），
输出该画像在 ES95/H0<=1%（保证给付另加 E[PV(draw)]/H0<=LTV0）约束下的反解月领与风险指标。

种子与路径数与仓库所有表一致（profile_seed + SOLVE_SIMS），故同画像结果与
outputs/*.csv 完全相同，可交叉验证。

CLI 示例：
    python model_api.py --segment huangpu --sex Male --age 70
    python model_api.py --segment minhang --sex Female --age 65 --property-value 5000000 --ltv 0.5 --drift 0.0 --policy adjustable_draw
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from liability_model import (
    ProductAssumptions,
    default_segment_assumptions,
    load_life_table,
    profile_seed,
    solve_monthly_pmt,
    SOLVE_SIMS,
)

ES95_TARGET = 0.01
MAX_STOPPED = 0.05


def solve_profile(
    segment: str,
    sex: str,
    start_age: int,
    mortality_improvement: float = 0.0,
    property_value: float | None = None,
    initial_ltv: float = 0.50,
    g_h_p: float = 0.0,
    draw_policy: str = "guaranteed_annuity",
    n_sims: int = SOLVE_SIMS,
) -> dict:
    """Solve one profile. Returns authoritative PMT + risk metrics (same seed/paths as repo tables)."""
    base = asdict(default_segment_assumptions(segment))
    base.update(
        {
            "sex": sex,
            "start_age": int(start_age),
            "mortality_improvement": float(mortality_improvement),
            "initial_ltv": float(initial_ltv),
            "g_H_P": float(g_h_p),
            "draw_policy": draw_policy,
            "n_sims": int(n_sims),
            "seed": profile_seed(segment, sex, int(start_age), float(mortality_improvement)),
        }
    )
    if property_value is not None:
        base["property_value"] = float(property_value)
    assumptions = ProductAssumptions(**base)
    life = load_life_table()

    pmt, summary = solve_monthly_pmt(
        assumptions,
        life=life,
        target_shortfall_rate=ES95_TARGET,
        risk_measure="es95",
        max_expected_present_value_rate=(
            assumptions.initial_ltv if draw_policy == "guaranteed_annuity" else None
        ),
        max_stopped_draw_probability=(
            None if draw_policy == "guaranteed_annuity" else MAX_STOPPED
        ),
        tolerance=5.0,
        max_iterations=24,
    )
    return {
        "segment": segment,
        "sex": sex,
        "start_age": int(start_age),
        "mortality_improvement": float(mortality_improvement),
        "property_value": assumptions.property_value,
        "initial_ltv": assumptions.initial_ltv,
        "g_H_P": assumptions.g_H_P,
        "draw_policy": draw_policy,
        "monthly_pmt": round(pmt, 2),
        "shortfall_probability": summary.shortfall_probability,
        "shortfall_es95_rate": summary.shortfall_es95_rate,
        "shortfall_var95_rate": summary.shortfall_var95_rate,
        "stopped_draw_probability": summary.stopped_draw_probability,
        "expected_actual_monthly_draw": round(summary.expected_actual_monthly_draw, 2),
        "mean_settlement_age": round(summary.mean_death_age, 2),
        "expected_present_value_draw_rate": round(
            summary.expected_present_value_drawn / assumptions.property_value, 6
        ),
        "seed": assumptions.seed,
        "n_sims": assumptions.n_sims,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Authoritative on-demand solver for the web app backend.")
    p.add_argument("--segment", required=True, choices=[
        "huangpu", "xuhui", "changning", "jingan", "putuo", "hongkou",
        "yangpu", "pudong", "minhang", "baoshan", "jiading", "jinshan",
        "songjiang", "qingpu", "fengxian", "chongming",
    ])
    p.add_argument("--sex", required=True, choices=["Male", "Female"])
    p.add_argument("--age", type=int, required=True)
    p.add_argument("--mi", type=float, default=0.0, help="mortality improvement, 0 or 0.15")
    p.add_argument("--property-value", type=float, default=None, help="override house value (yuan)")
    p.add_argument("--ltv", type=float, default=0.50)
    p.add_argument("--drift", type=float, default=0.0, help="g_H_P, e.g. -0.01/0/0.02")
    p.add_argument("--policy", default="guaranteed_annuity", choices=["guaranteed_annuity", "adjustable_draw"])
    p.add_argument("--n-sims", type=int, default=SOLVE_SIMS)
    args = p.parse_args()
    result = solve_profile(
        args.segment, args.sex, args.age, args.mi, args.property_value,
        args.ltv, args.drift, args.policy, args.n_sims,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
