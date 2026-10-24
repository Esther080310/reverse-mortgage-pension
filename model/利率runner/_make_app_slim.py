# -*- coding: utf-8 -*-
"""从主表机械裁剪生成前端精简表 app_main_slim.csv（不重新运行模型）。

按第三方复查建议(四)：主表有 57 列，前端多数只用 ~16 列。本脚本只做列裁剪，
数值与 liability_scenario_comparison_official_cl1_2025.csv 逐格一致，不触碰模型。
BASE 自动探测（兼容交接包 利率runner 同级布局与 live 工作区布局）。
"""
import os
from pathlib import Path

import pandas as pd

_HERE = Path(__file__).resolve()
_CANDIDATES = [
    _HERE.parents[1] / "CL1模型",
    _HERE.parents[0] / "房价数据和建模" / "负债端最终结果汇总_官方CL1_2025",
]
BASE = next((str(p) for p in _CANDIDATES if (p / "outputs").is_dir()), None)
if BASE is None:
    raise FileNotFoundError("未找到 CL1 模型目录。")

SRC = os.path.join(BASE, "outputs", "liability_scenario_comparison_official_cl1_2025.csv")
OUT = os.path.join(BASE, "outputs", "app_main_slim.csv")

SLIM_COLUMNS = [
    "scenario_id",
    "segment",
    "segment_label",
    "sex",
    "start_age",
    "mortality_improvement",
    "property_value",
    "guaranteed_solved_monthly_pmt",
    "guaranteed_solved_expected_actual_monthly_draw",
    "guaranteed_solved_shortfall_probability",
    "guaranteed_solved_shortfall_es95_rate",
    "guaranteed_solved_stopped_draw_probability",
    "guaranteed_solved_mean_settlement_age",
    "adjustable_solved_monthly_pmt",
    "adjustable_solved_expected_actual_monthly_draw",
    "adjustable_solved_stopped_draw_probability",
]

df = pd.read_csv(SRC)
missing = [c for c in SLIM_COLUMNS if c not in df.columns]
if missing:
    raise ValueError(f"主表缺少字段: {missing}")

slim = df[SLIM_COLUMNS].copy()
slim.to_csv(OUT, index=False, encoding="utf-8-sig")

# 自检：行数、缺失、重复
n_rows = len(slim)
n_missing = int(slim.isna().sum().sum())
n_dup = int(slim.duplicated().sum())
print(f"WROTE {OUT}")
print(f"rows={n_rows} cols={len(SLIM_COLUMNS)} missing_cells={n_missing} dup_rows={n_dup}")
assert n_rows == 12, f"expected 12 rows, got {n_rows}"
assert n_missing == 0, "app_main_slim has missing cells"
assert n_dup == 0, "app_main_slim has duplicate rows"
print("APP_SLIM_OK")
