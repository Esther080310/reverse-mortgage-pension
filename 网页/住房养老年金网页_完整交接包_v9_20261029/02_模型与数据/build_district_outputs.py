# -*- coding: utf-8 -*-
"""Build the authoritative Shanghai 16-district parameter and age-70 lookup tables."""
from __future__ import annotations

import csv
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
PACKAGE = ROOT / "以房养老_网页数据包_20261026" / "以房养老_网页数据包_20261026"
MODEL_DIR = PACKAGE / "model_api"
TABLES = PACKAGE / "tables"
sys.path.insert(0, str(MODEL_DIR))

DISTRICTS = {
    "huangpu": ("黄浦区", "核心区", 0.0186, 0.08),
    "xuhui": ("徐汇区", "核心区", 0.0186, 0.08),
    "changning": ("长宁区", "核心区", 0.0186, 0.08),
    "jingan": ("静安区", "核心区", 0.0186, 0.08),
    "putuo": ("普陀区", "城区", 0.0188, 0.10),
    "hongkou": ("虹口区", "城区", 0.0188, 0.10),
    "yangpu": ("杨浦区", "城区", 0.0188, 0.10),
    "pudong": ("浦东新区", "城区", 0.0188, 0.10),
    "minhang": ("闵行区", "城区", 0.0188, 0.10),
    "baoshan": ("宝山区", "城区", 0.0188, 0.10),
    "jiading": ("嘉定区", "城区", 0.0188, 0.10),
    "jinshan": ("金山区", "远郊", 0.0239, 0.15),
    "songjiang": ("松江区", "远郊", 0.0239, 0.15),
    "qingpu": ("青浦区", "远郊", 0.0239, 0.15),
    "fengxian": ("奉贤区", "远郊", 0.0239, 0.15),
    "chongming": ("崇明区", "远郊", 0.0239, 0.15),
}

# sigma 审慎上限：实测低于上限保留实测，高于上限按上限计。
# 理由见 model_api/liability_model.py 中 default_segment_assumptions 的注释（静安单年跳变案例）。
TIER_VOL_CAP = {"核心区": 0.11, "城区": 0.13, "远郊": 0.14}


def build_parameters() -> list[dict]:
    df = pd.read_excel(ROOT / "各区县房价.xlsx", sheet_name="区县")
    sh = df[df["城市"].astype(str).eq("上海")].copy()
    rows = []
    for key, (label, tier, rent_yield, discount) in DISTRICTS.items():
        sub = sh[sh["区县"].eq(label)].sort_values("年份")
        years = sub["年份"].to_numpy(float)
        prices = sub["均价(元/㎡)"].to_numpy(float)
        annual_log_returns = np.diff(np.log(prices)) / np.diff(years)
        full_years = set(range(int(years.min()), int(years.max()) + 1))
        missing = sorted(full_years - set(years.astype(int)))
        span = int(years[-1] - years[0])
        raw_vol = round(float(np.std(annual_log_returns, ddof=1)), 6)
        cap = TIER_VOL_CAP[tier]
        applied_vol = round(min(raw_vol, cap), 6)
        rows.append({
            "segment": key,
            "district_label": label,
            "tier": tier,
            "reference_area_sqm": 70,
            "latest_year": int(years[-1]),
            "latest_avg_price_per_sqm": round(prices[-1], 2),
            "reference_property_value": round(prices[-1] * 70, 2),
            "annual_house_vol": applied_vol,
            "raw_annual_house_vol": raw_vol,
            "vol_capped": "是" if raw_vol > cap else "否",
            "historical_cagr": round(float((prices[-1] / prices[0]) ** (1 / span) - 1), 6),
            "annual_rent_yield_proxy": rent_yield,
            "liquidity_discount_proxy": discount,
            "year_start": int(years[0]),
            "year_end": int(years[-1]),
            "observations": len(years),
            "missing_years": "|".join(map(str, missing)),
            "data_note": "跨年收益已按年份间隔年化" if missing else "年度序列完整",
        })
    return rows


def solve_task(task: tuple[str, str, int, float, str]) -> dict:
    os.chdir(MODEL_DIR)
    from model_api import solve_profile

    segment, sex, age, mi, policy = task
    return solve_profile(
        segment=segment,
        sex=sex,
        start_age=age,
        mortality_improvement=mi,
        initial_ltv=0.50,
        g_h_p=0.0,
        draw_policy=policy,
        n_sims=4000,
    )


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parameters = build_parameters()
    write_csv(TABLES / "district_parameters.csv", parameters)

    tasks = [
        (segment, sex, age, mi, policy)
        for segment in DISTRICTS
        for sex in ("Male", "Female")
        for age in range(60, 91)
        for mi in (0.0, 0.15)
        for policy in ("guaranteed_annuity", "adjustable_draw")
    ]
    solved = {}
    with ProcessPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(solve_task, task): task for task in tasks}
        for future in as_completed(futures):
            task = futures[future]
            solved[task] = future.result()
            print(f"completed {len(solved)}/{len(tasks)}: {task}", flush=True)

    labels = {row["segment"]: row for row in parameters}
    output = []
    for segment in DISTRICTS:
        for sex in ("Male", "Female"):
            for age in range(60, 91):
                for mi in (0.0, 0.15):
                    guaranteed = solved[(segment, sex, age, mi, "guaranteed_annuity")]
                    adjustable = solved[(segment, sex, age, mi, "adjustable_draw")]
                    meta = labels[segment]
                    output.append({
                    "segment": segment,
                    "segment_label": meta["district_label"],
                    "tier": meta["tier"],
                    "sex": sex,
                    "start_age": age,
                    "mortality_improvement": mi,
                    "property_value": guaranteed["property_value"],
                    "initial_ltv": 0.50,
                    "g_H_P": 0.0,
                    "annual_house_vol": meta["annual_house_vol"],
                    "guaranteed_monthly_pmt": guaranteed["monthly_pmt"],
                    "guaranteed_actual_monthly_draw": guaranteed["expected_actual_monthly_draw"],
                    "guaranteed_shortfall_probability": guaranteed["shortfall_probability"],
                    "guaranteed_shortfall_es95_rate": guaranteed["shortfall_es95_rate"],
                    "guaranteed_stopped_draw_probability": guaranteed["stopped_draw_probability"],
                    "adjustable_monthly_pmt": adjustable["monthly_pmt"],
                    "adjustable_actual_monthly_draw": adjustable["expected_actual_monthly_draw"],
                    "adjustable_shortfall_probability": adjustable["shortfall_probability"],
                    "adjustable_shortfall_es95_rate": adjustable["shortfall_es95_rate"],
                    "adjustable_stopped_draw_probability": adjustable["stopped_draw_probability"],
                    "n_sims": 4000,
                    })
    write_csv(TABLES / "district_model_lookup.csv", output)
    print(f"wrote {len(parameters)} parameter rows and {len(output)} lookup rows")


if __name__ == "__main__":
    main()
