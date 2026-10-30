# -*- coding: utf-8 -*-
"""核查《各区县房价.xlsx》中的上海现行 16 区及缺失年份。"""
from pathlib import Path

import pandas as pd

XLSX = Path(__file__).resolve().parent / "各区县房价.xlsx"
CURRENT_DISTRICTS = [
    "黄浦区", "徐汇区", "长宁区", "静安区", "普陀区", "虹口区", "杨浦区", "浦东新区",
    "闵行区", "宝山区", "嘉定区", "金山区", "松江区", "青浦区", "奉贤区", "崇明区",
]

xl = pd.ExcelFile(XLSX)
print("SHEETS:", xl.sheet_names)
df = xl.parse("区县") if "区县" in xl.sheet_names else xl.parse(xl.sheet_names[0])
print("SHAPE:", df.shape)
print("COLUMNS:", list(df.columns))

# 找区域列与日期列
name_col = next((c for c in df.columns if ("区县" in str(c) or "地区" in str(c) or "区域" in str(c))), df.columns[0])
date_col = next((c for c in df.columns if ("日期" in str(c) or "时间" in str(c) or "年" in str(c) or "月" in str(c))), None)
sh = df[df["城市"].astype(str).eq("上海")].copy()
names = sorted(set(str(v) for v in sh[name_col].dropna().unique()))
print(f"\n上海原始口径数={len(names)}: {' / '.join(names)}")
print("排除历史/汇总口径:", " / ".join(sorted(set(names) - set(CURRENT_DISTRICTS))))
print(f"纳入现行区数={len(CURRENT_DISTRICTS)}")
for district in CURRENT_DISTRICTS:
    years = sorted(pd.to_numeric(sh.loc[sh[name_col].eq(district), "年份"], errors="coerce").dropna().astype(int))
    missing = sorted(set(range(min(years), max(years) + 1)) - set(years)) if years else []
    print(f"{district}: {years[0] if years else '-'}-{years[-1] if years else '-'}; n={len(years)}; 缺失={missing or '无'}")
