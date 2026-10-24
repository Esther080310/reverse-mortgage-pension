# -*- coding: utf-8 -*-
"""按【CL1 生产模型·专业修订版】重画利率敏感性图（2026-10-20 回灌）。

数据源 = outputs/cl1_rate_sensitivity_wang65_gHP0.csv（新格式：experiment 两列拆分
initial_rate_only / theta_only，与第四节利率敏感性表同源，从机制上保证 表=图=代码）。
口径：黄浦老破小 · 男65 · LTV50% · g_H^P=0% · 保证给付年金主模型 ·
      ES95(shortfall)/H0<=1% 且 E[PV(draw)]/H0<=LTV0 反解名义月领金。
绕开中文路径：脚本名 ASCII；BASE 自动探测（兼容交接包 利率runner/↔CL1模型/ 与 live 工作区），任意电脑可跑。
"""
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import FuncFormatter

_HERE = Path(__file__).resolve()
_CANDIDATES = [
    _HERE.parents[1] / "CL1模型",
    _HERE.parents[0] / "房价数据和建模" / "负债端最终结果汇总_官方CL1_2025",
]
BASE = next((str(p) for p in _CANDIDATES if (p / "outputs").is_dir()), None)
if BASE is None:
    raise FileNotFoundError("未找到 CL1 模型目录：利率runner/ 应与 CL1模型/ 同级，或脚本置于工作区根目录。")
CSV = os.path.join(BASE, "outputs", "cl1_rate_sensitivity_wang65_gHP0.csv")
OUT = os.path.join(BASE, "outputs", "figures", "cl1_rate_sensitivity_wang65.png")

plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

data = pd.read_csv(CSV)

fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
titles = {
    "initial_rate_only": "仅改变CIR初始短率 r0（θ=2.22%固定）",
    "theta_only": "仅改变CIR长期中枢 θ（r0=1.22%固定）",
}
for axis, experiment in zip(axes, titles):
    subset = data[data["experiment"] == experiment]
    x_column = "initial_rate" if experiment == "initial_rate_only" else "cir_theta"
    axis.plot(
        subset[x_column] * 100,
        subset["guaranteed_monthly_pmt"],
        "o-",
        color="#1f4e79",
        linewidth=2,
    )
    axis.set_title(titles[experiment])
    axis.set_xlabel("利率参数（%）")
    axis.grid(alpha=0.3)
    axis.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:,.0f}"))
axes[0].set_ylabel("保证给付年金月领（元）")
fig.suptitle("CIR参数敏感性：黄浦老破小、男性65岁、LTV 50%（保证给付主模型，ES95约束）")
fig.tight_layout()
fig.savefig(OUT, dpi=180)
plt.close(fig)
print("CHART OK")
print(OUT)
