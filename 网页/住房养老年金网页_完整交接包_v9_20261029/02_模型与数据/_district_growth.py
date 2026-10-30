# -*- coding: utf-8 -*-
"""只读核算：马克数据网《各区县房价.xlsx》上海 黄浦/闵行/金山 历史房价增长。
复用 data_cleaning_and_volatility.calculate_district_sigma_from_markdata 的口径：
sheet='区县'，城市=='上海'，价格列含'均价'，年度对数收益=diff(log(price))。
额外报告：年份跨度、缺失/断档、CAGR、对数收益均值、简单收益均值、口径评估。
不修改任何数据或模型文件。
"""
import os
import numpy as np
import pandas as pd

MARK = (r"d:\软件工具\WPS\241912900\WPS云盘\科创\挑战杯、互联网加\以房养老信托"
        r"\以房养老大创\房价数据和建模\马克网")
path = os.path.join(MARK, "各区县房价", "各区县房价.xlsx")

lines = []
def P(s=""):
    lines.append(str(s))

P("=" * 72)
P("只读核算：马克数据网《各区县房价.xlsx》 上海 黄浦/闵行/金山 历史房价增长")
P("=" * 72)
P(f"[文件] {path}")
P(f"[文件存在] {os.path.isfile(path)}")

xl = pd.ExcelFile(path)
P(f"[全部工作表] {xl.sheet_names}")

dd = pd.read_excel(path, sheet_name="区县")
dd.columns = [str(c).strip() for c in dd.columns]
P(f"[区县表列名] {list(dd.columns)}")
P(f"[区县表总行数] {len(dd)}")

pcands = [c for c in dd.columns if "均价" in c]
P(f"[含'均价'的列] {pcands}")
pcol = pcands[0]
P(f"[采用价格列] {pcol}")

dd["年份"] = pd.to_numeric(dd["年份"], errors="coerce")
dd[pcol] = pd.to_numeric(dd[pcol], errors="coerce")

cities = sorted(dd["城市"].astype(str).unique().tolist())
P(f"[城市数] {len(cities)}；含'上海': {'上海' in cities}")

shd = dd[dd["城市"].astype(str) == "上海"].copy()
P(f"[上海原始行数] {len(shd)}")
P(f"[上海区县清单] {sorted(shd['区县'].astype(str).unique().tolist())}")
P(f"[上海年份范围(全部区县)] {shd['年份'].min():.0f} ~ {shd['年份'].max():.0f}")
P("")

summary = {}
for dist, key in [("黄浦区", "黄浦"), ("闵行区", "闵行"), ("金山区", "金山")]:
    raw = shd[shd["区县"].astype(str) == dist]
    sub = raw.dropna(subset=["年份", pcol]).sort_values("年份")
    yrs = sub["年份"].values.astype(int)
    pv = sub[pcol].values.astype(float)
    P("-" * 72)
    P(f"【{key}（{dist}）】")
    P(f"  原始行数={len(raw)}；去NaN后样本数 n={len(yrs)}")
    P(f"  年份序列: {yrs.tolist()}")
    P(f"  均价序列(元/㎡): {[round(x, 1) for x in pv.tolist()]}")
    if len(yrs) < 2:
        P("  样本不足，跳过")
        continue
    full = list(range(int(yrs.min()), int(yrs.max()) + 1))
    gaps = [y for y in full if y not in set(yrs.tolist())]
    dup = len(yrs) != len(set(yrs.tolist()))
    nan_price = int(raw[pcol].isna().sum())
    P(f"  年份跨度 {yrs.min()}~{yrs.max()}（含{yrs.max()-yrs.min()+1}个年点）")
    P(f"  断档缺失年份: {gaps if gaps else '无'}；重复年份: {'有' if dup else '无'}；均价为NaN的行: {nan_price}")
    span = int(yrs.max() - yrs.min())
    cagr = (pv[-1] / pv[0]) ** (1.0 / span) - 1.0
    lr = np.diff(np.log(pv))
    sr = np.diff(pv) / pv[:-1]
    P(f"  首年 {yrs.min()} 均价={pv[0]:.1f}；末年 {yrs.max()} 均价={pv[-1]:.1f} 元/㎡")
    P(f"  累计涨幅 = {(pv[-1]/pv[0]-1)*100:.1f}%")
    P(f"  CAGR(首尾法, span={span}年) = {cagr*100:.2f}%")
    P(f"  年度对数收益: 均值={np.mean(lr)*100:.2f}%  波动(ddof=1)={np.std(lr,ddof=1)*100:.2f}%  "
      f"最小={lr.min()*100:.2f}%  最大={lr.max()*100:.2f}%")
    P(f"  年度简单收益: 均值={np.mean(sr)*100:.2f}%")
    P(f"  [口径校验] 对数波动应≈白皮书σ({key}: 黄浦10.97/闵行12.86/金山13.85) -> 实得 {np.std(lr,ddof=1)*100:.2f}%")
    summary[key] = dict(n=len(yrs), ymin=int(yrs.min()), ymax=int(yrs.max()),
                        cagr=float(cagr), lr_mean=float(np.mean(lr)), lr_std=float(np.std(lr, ddof=1)))

P("")
P("=" * 72)
P("汇总（历史估计，仅供披露，不外推30年）")
P("=" * 72)
for k, v in summary.items():
    P(f"  {k}: n={v['n']}({v['ymin']}~{v['ymax']})  CAGR={v['cagr']*100:.2f}%  "
      f"对数收益均值={v['lr_mean']*100:.2f}%  对数波动={v['lr_std']*100:.2f}%")

rep = os.path.join(os.getcwd(), "_district_growth_report.txt")
with open(rep, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print("DONE")
print(rep)
