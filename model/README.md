# model/ — 精算模型（可复现）

## 目录

```
model/
├── CL1模型/
│   ├── scripts/               liability_model.py（核心）+ 4 个 run 脚本 + 生命表提取脚本
│   ├── outputs/               全部结果：*.csv（机器可读）+ *.md（人类可读）+ figures/*.png
│   │   └── app_main_slim.csv  前端主查询表（12 行 × 16 列，主表机械裁剪）
│   ├── official_cl1_life_table_2025.csv   官方 CL1 生命表（复现必需）
│   ├── hecm_style_plf_table.csv           HECM 风格 PLF 自制演示表（非 HUD 官方）
│   ├── 国债收益率_月末_200801_202603.csv   CIR 校准与 ρ 估计数据源
│   └── requirements.txt
├── 利率runner/                利率敏感性可移植脚本（BASE 自动探测，任意电脑可跑）
└── notes/                     公式过程/模型实现/生命表接入报告/通俗总结/组长汇报
```

## 环境

- **Python ≥ 3.9**（模型用了 3.9+ 语法；系统自带 Python 3.7 会报错）。
- 依赖：`pip install -r CL1模型/requirements.txt`（numpy、pandas、matplotlib）。

## 复现步骤

在 `CL1模型/` 目录下执行（脚本用相对路径 `outputs/`，CWD 必须是 `CL1模型/`）：

```bash
cd CL1模型
python scripts/run_liability_scenarios.py       # 主表 + LTV 敏感性 + 棘轮对比
python scripts/run_dynamic_ltv_hecm_style.py    # HECM 风格动态 LTV
python scripts/run_liability_enhancements.py    # 夫妻 / 成本流动性 / 危机路径 + 图
python scripts/run_statistical_validation.py    # 五随机种子 + 六规格敏感性
```

产物写回 `outputs/`，随机种子固定（`profile_seed`）故数值可复现，应与仓库内 CSV 逐格一致。

- 生命表如需重新提取：`python scripts/extract_official_life_table_2025.py`（需官方金规〔2025〕21号附件 docx，本仓库不含原文，通常无需重跑）。
- 前端精简表：`python 利率runner/_make_app_slim.py`（从主表裁剪 `outputs/app_main_slim.csv`，不重跑模型）。
- 利率敏感性：`python 利率runner/_cl1_rate_sweep.py` 与 `_cl1_rate_chart.py`（BASE 自动探测，换电脑无需改）。

## 关键口径（详见 `../docs/白皮书_精算模型数据来源与参数.md`）

- P 测度蒙特卡洛；CL1 生命表；两成分正态混合肥尾；CIR 随机利率；两类合同；ES95/H0≤1% 反解。
- 所有表对同一画像用 `profile_seed` 权威种子 + 统一 4000 路径 → 同画像跨表数字一致。
- 免责：研究情景，非商业报价。
