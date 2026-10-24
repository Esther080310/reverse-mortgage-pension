"""Run a transparent, non-official dynamic-LTV research demonstration.

HECM uses Principal Limit Factors (PLF) that vary by the age of the youngest
borrower and the expected interest rate. This script applies that idea to the
trust reverse-mortgage liability model: PLF is used as the initial LTV.

The bundled table is self-designed and must not be described as an official HUD
table or used as a commercial quote table.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pandas as pd

from liability_model import (
    ProductAssumptions,
    default_segment_assumptions,
    load_life_table,
    solve_monthly_pmt,
    SOLVE_SIMS,
)


OUTPUT_DIR = Path("outputs")
PLF_TABLE = Path("hecm_style_plf_table.csv")
N_SIMS = SOLVE_SIMS
ES95_TARGET_SHORTFALL_RATE = 0.01

SEGMENTS = ["huangpu_small", "minhang_mid", "jinshan_small"]
AGES = [62, 65, 70, 75, 80, 85, 90]
EXPECTED_RATES = [0.03, 0.05, 0.06]

SEGMENT_LABELS = {
    "huangpu_small": "黄浦老破小",
    "minhang_mid": "闵行改善型",
    "jinshan_small": "金山老破小",
}


def format_currency(value: float) -> str:
    return f"{value:,.0f}"


def format_percent(value: float) -> str:
    return f"{value:.2%}"


def load_plf_table(path: Path = PLF_TABLE) -> pd.DataFrame:
    table = pd.read_csv(path)
    required = {"expected_rate", "age", "plf"}
    missing = required.difference(table.columns)
    if missing:
        raise ValueError(f"PLF table missing columns: {sorted(missing)}")
    table = table.copy()
    table["expected_rate"] = table["expected_rate"].astype(float)
    table["age"] = table["age"].astype(int)
    table["plf"] = table["plf"].astype(float)
    return table.sort_values(["expected_rate", "age"]).reset_index(drop=True)


def plf_for(table: pd.DataFrame, age: int, expected_rate: float) -> float:
    hit = table[
        (table["age"] == age)
        & (table["expected_rate"].round(6) == round(expected_rate, 6))
    ]
    if hit.empty:
        raise ValueError(f"No PLF for age={age}, expected_rate={expected_rate}.")
    return float(hit.iloc[0]["plf"])


def build_assumptions(segment: str, age: int, plf: float, expected_rate: float, seed: int) -> ProductAssumptions:
    base = asdict(default_segment_assumptions(segment))
    base.update(
        {
            "sex": "Female",
            "start_age": age,
            "initial_ltv": plf,
            "initial_rate": expected_rate,
            "cir_theta": expected_rate,
            "mortality_improvement": 0.0,
            "n_sims": N_SIMS,
            "seed": seed,
            "draw_policy": "guaranteed_annuity",
            "use_ratchet": False,
        }
    )
    return ProductAssumptions(**base)


def run_dynamic_ltv() -> pd.DataFrame:
    life = load_life_table()
    plf_table = load_plf_table()
    rows: list[dict] = []
    scenario_id = 0

    for segment_index, segment in enumerate(SEGMENTS, start=1):
        paired_seed = 20262000 + segment_index
        for expected_rate in EXPECTED_RATES:
            for age in AGES:
                scenario_id += 1
                plf = plf_for(plf_table, age, expected_rate)
                assumptions = build_assumptions(
                    segment,
                    age=age,
                    plf=plf,
                    expected_rate=expected_rate,
                    seed=paired_seed,
                )
                pmt, summary = solve_monthly_pmt(
                    assumptions,
                    life=life,
                    target_shortfall_rate=ES95_TARGET_SHORTFALL_RATE,
                    risk_measure="es95",
                    max_expected_present_value_rate=plf,
                    tolerance=5.0,
                    max_iterations=24,
                )
                rows.append(
                    {
                        "scenario_id": scenario_id,
                        "segment": segment,
                        "segment_label": SEGMENT_LABELS[segment],
                        "sex": assumptions.sex,
                        "start_age": age,
                        "expected_rate": expected_rate,
                        "hecm_style_plf": plf,
                        "property_value": assumptions.property_value,
                        "solved_monthly_pmt": pmt,
                        "actual_monthly_draw": summary.expected_actual_monthly_draw,
                        "mean_settlement_age": summary.mean_death_age,
                        "shortfall_probability": summary.shortfall_probability,
                        "shortfall_var95_rate": summary.shortfall_var95_rate,
                        "shortfall_es95_rate": summary.shortfall_es95_rate,
                        "expected_present_value_draw_rate": summary.expected_present_value_drawn
                        / assumptions.property_value,
                        "stopped_draw_probability": summary.stopped_draw_probability,
                    }
                )
                print(
                    f"[DYN {scenario_id:02d}] {segment} age={age} rate={expected_rate:.0%} "
                    f"plf={plf:.1%}: pmt={pmt:,.0f}"
                )
    return pd.DataFrame(rows)


def write_markdown(df: pd.DataFrame, path: Path) -> None:
    lines = [
        "# 动态LTV方法演示",
        "",
        "本分析仅借鉴PLF随年龄和预期利率变化的思想。`hecm_style_plf_table.csv`是本项目自制、可替换的研究演示表，没有逐点复刻或校准HUD官方PLF，不能用于商业报价。",
        "",
        "本表中的PLF在保证给付年金模型中表示签约时允许配置的给付现值预算比例。",
        "",
        "## 1. PLF 参考表",
        "",
        "| 预期利率 | 年龄 | HECM风格PLF |",
        "| ---: | ---: | ---: |",
    ]
    plf = load_plf_table()
    for _, row in plf.iterrows():
        lines.append(f"| {format_percent(row['expected_rate'])} | {int(row['age'])} | {format_percent(row['plf'])} |")

    lines.extend(
        [
            "",
            "## 2. 动态 LTV 结果主表",
            "",
            "| 场景 | 年龄 | 预期利率 | PLF/LTV | 保证给付月领 | 短缺概率 | VaR95/H0 | ES95/H0 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for _, row in df.iterrows():
        lines.append(
            "| "
            f"{row['segment']} | "
            f"{int(row['start_age'])} | "
            f"{format_percent(row['expected_rate'])} | "
            f"{format_percent(row['hecm_style_plf'])} | "
            f"{format_currency(row['solved_monthly_pmt'])} | "
            f"{format_percent(row['shortfall_probability'])} | "
            f"{format_percent(row['shortfall_var95_rate'])} | "
            f"{format_percent(row['shortfall_es95_rate'])} |"
        )

    age_summary = df.groupby("start_age")["solved_monthly_pmt"].mean().sort_index()
    rate_summary = df.groupby("expected_rate")["solved_monthly_pmt"].mean().sort_index()
    segment_summary = df.groupby("segment")["solved_monthly_pmt"].mean().sort_values(ascending=False)

    lines.extend(
        [
            "",
            "## 3. 汇总观察",
            "",
            "| 年龄 | 平均名义月领 |",
            "| ---: | ---: |",
        ]
    )
    for age, value in age_summary.items():
        lines.append(f"| {int(age)} | {format_currency(value)} |")

    lines.extend(["", "| 预期利率 | 平均名义月领 |", "| ---: | ---: |"])
    for rate, value in rate_summary.items():
        lines.append(f"| {format_percent(rate)} | {format_currency(value)} |")

    lines.extend(["", "| 房产场景 | 平均名义月领 |", "| --- | ---: |"])
    for segment, value in segment_summary.items():
        lines.append(f"| {segment} | {format_currency(value)} |")

    lines.extend(
        [
            "",
            "## 4. 解释口径",
            "",
            "- 年龄越高时剩余支付期限通常越短，方法上可以配置更高的给付现值预算比例。",
            "- 预期利率同时影响给付现值折现和债务累积，结果需结合具体合同责任解释。",
            "- 该表只用于展示动态LTV方法，不构成中国市场参数建议。",
            "",
            "## 5. 可写入论文的表述",
            "",
            "为展示年龄与利率进入给付预算的方法，本文设置一张自制动态LTV参考表，并在保证给付责任下开展情景分析。该表属于研究设计参数，后续需通过行业访谈、本土历史数据和监管意见重新校准。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df = run_dynamic_ltv()
    csv_path = OUTPUT_DIR / "liability_dynamic_ltv_hecm_style_official_cl1_2025.csv"
    md_path = OUTPUT_DIR / "liability_dynamic_ltv_hecm_style_official_cl1_2025.md"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    write_markdown(df, md_path)
    print(f"Dynamic LTV CSV written to {csv_path.resolve()}")
    print(f"Dynamic LTV Markdown written to {md_path.resolve()}")


if __name__ == "__main__":
    main()
