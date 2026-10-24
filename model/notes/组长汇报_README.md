# 负债端模型阶段汇报说明

这份文件夹汇总了目前负债端模型的最终有效成果，全部基于官方《中国人身保险业经验生命表（2025）》养老类业务表男女表（CL1），不再使用前期 synthetic 平替生命表作为主结果。

## 1. 建议组长优先阅读顺序

建议按下面顺序看：

1. `负债端当前工作通俗总结.md`
   - 用最通俗的方式解释我们现在做了什么、模型在算什么、结果怎么理解。

2. `负债端三项提升分析报告.md`
   - 展示最近新增的三个提升：夫妻双生命、成本/折价敏感性、房价危机场景与棘轮触发图。

3. `outputs/liability_scenario_summary_official_cl1_2025.md`
   - 官方 CL1 表下的主情景结果表。

4. `outputs/liability_ltv_sensitivity_official_cl1_2025.md`
   - LTV = 40%、50%、60% 的敏感性分析。

5. `outputs/liability_dynamic_ltv_hecm_style_official_cl1_2025.md`
   - 借鉴美国 HECM 的年龄-利率动态 LTV / PLF 分析。

6. `outputs/liability_ratchet_comparison_official_cl1_2025.md`
   - 单向棘轮机制开启 vs 关闭对比。

7. `outputs/liability_joint_life_official_cl1_2025.md`
   - 夫妻双生命最后生存者模型结果。

## 2. 当前负债端模型做了什么

目前模型已经完成以下工作：

- 接入官方第四套生命表 CL1 男女表。
- 建立单生命负债端蒙特卡洛模型。
- 支持夫妻双生命最后生存者清算。
- 模拟房价波动、利率变化、养老金债务累积。
- 计算担保不足损失 `shortfall` 和继承人剩余权益 `bequest`。
- 引入单向棘轮机制，控制房价下跌时的提款风险。
- 区分名义月领金额和实际平均月提款。
- 完成 LTV、成本率、流动性折价、棘轮机制、房价危机场景等敏感性分析。
- 新增 HECM 风格动态 LTV：按年龄和预期利率查 PLF，再作为授信比例接入模型。

## 3. 最核心结论

### 3.1 官方 CL1 表下的主结果

在当前双重约束下：

```text
P95(shortfall) / 房产初始价值 <= 1%
提款截断概率 <= 5%
```

主结果为：

- 最稳健场景：黄浦老破小 / 男性 / 基准死亡率，月领金额约 5187 元。
- 约束最强场景：金山老破小 / 女性 / 长寿压力情景，月领金额约 568 元。
- 固定月领 8000 元在多数非核心房产场景下不可持续，更适合作为压力测试。

### 3.2 LTV 敏感性

LTV 越高，老人可领取金额越高，但机构风险也更大。

平均反解名义月领金额：

| LTV | 平均月领金额 |
| ---: | ---: |
| 40% | 1,922 元 |
| 50% | 2,353 元 |
| 60% | 2,845 元 |

### 3.3 单向棘轮机制

### 3.3 HECM 风格动态 LTV

固定 LTV 已升级为更细的动态 LTV 分析。借鉴美国 HECM 的 Principal Limit Factor 逻辑，授信比例随年龄和预期利率变化。

动态 LTV 结果显示：

| 年龄 | 平均名义月领 |
| ---: | ---: |
| 62 | 957 元 |
| 65 | 1,222 元 |
| 70 | 1,807 元 |
| 75 | 2,758 元 |
| 80 | 4,222 元 |
| 85 | 6,756 元 |
| 90 | 11,103 元 |

预期利率越高，月领金额越低：

| 预期利率 | 平均名义月领 |
| ---: | ---: |
| 3% | 5,153 元 |
| 5% | 3,876 元 |
| 6% | 3,324 元 |

注意：当前 `hecm_style_plf_table.csv` 是 HECM 风格可替换参考表，应表述为“借鉴 HECM 动态授信思想”，不要写成完全复刻 HUD 官方逐点 PLF 表。

### 3.4 单向棘轮机制

关闭动态棘轮后，平均名义月领金额提高约 853 元/月。

但棘轮关闭会提高机构尾部风险，尤其是闵行改善型这种高波动房产。因此棘轮机制应被解释为：

```text
牺牲部分现金流连续性，换取机构风险控制的审慎风控机制。
```

### 3.5 夫妻双生命模型

夫妻双生命最后生存者模型更贴近真实以房养老家庭场景。

结果显示：

```text
夫妻双生命会拉长负债期限，使月领金额平均下降约 15.23%。
```

这说明单生命模型可能低估现实业务中的长寿负债压力。

### 3.6 房价危机场景

模型构造了闵行改善型房产第 10 年下跌 30% 的压力情景。

对应图：

```text
outputs/figures/house_crisis_ratchet_trigger.png
```

结论：

- 第 10 年房价暴跌后，棘轮额度立即下调。
- 约第 15.83 年，棘轮开启下第一次提款被截断。
- 第 30 年，棘轮开启债务余额约 313 万元，棘轮关闭约 373 万元。

这张图能直观说明棘轮机制为什么能控制机构风险。

## 4. 文件夹结构说明

```text
负债端最终结果汇总_官方CL1_2025
│
├─ official_cl1_life_table_2025.csv
├─ official_cl1_life_table_2025.xlsx
│
├─ 负债端当前工作通俗总结.md
├─ 负债端三项提升分析报告.md
├─ 负债端关键改进与敏感性分析报告.md
├─ 第四套生命表接入与负债端重跑报告.md
├─ 负债端模型公式过程与结果整理.md
├─ 负债端模型实现说明.md
│
├─ outputs
│  ├─ liability_scenario_summary_official_cl1_2025.md
│  ├─ liability_scenario_comparison_official_cl1_2025.csv
│  ├─ liability_ltv_sensitivity_official_cl1_2025.md
│  ├─ liability_ltv_sensitivity_official_cl1_2025.csv
│  ├─ liability_dynamic_ltv_hecm_style_official_cl1_2025.md
│  ├─ liability_dynamic_ltv_hecm_style_official_cl1_2025.csv
│  ├─ liability_ratchet_comparison_official_cl1_2025.md
│  ├─ liability_ratchet_comparison_official_cl1_2025.csv
│  ├─ liability_joint_life_official_cl1_2025.md
│  ├─ liability_joint_life_official_cl1_2025.csv
│  ├─ liability_cost_liquidity_sensitivity_official_cl1_2025.md
│  ├─ liability_cost_liquidity_sensitivity_official_cl1_2025.csv
│  ├─ liability_house_crisis_ratchet_path.md
│  ├─ liability_house_crisis_ratchet_path.csv
│  └─ figures
│     └─ house_crisis_ratchet_trigger.png
│
└─ scripts
   ├─ extract_official_life_table_2025.py
   ├─ liability_model.py
   ├─ run_liability_scenarios.py
   ├─ run_dynamic_ltv_hecm_style.py
   └─ run_liability_enhancements.py
```

## 5. 可以直接给组长说的简短版本

我们已经把负债端模型从前期 synthetic 表切换到官方第四套生命表 CL1，并完成了主情景、固定 LTV 敏感性、HECM 风格动态 LTV、棘轮机制对比、夫妻双生命、成本/折价敏感性和房价危机场景分析。模型现在不只计算老人名义上每月能领多少钱，还同时衡量实际平均提款、提款截断概率和机构端 shortfall 风险。结果显示，核心区高价值房产养老金承载能力最强，远郊低价值房产约束最强；动态 LTV 下年龄越高月领金额越高、预期利率越高月领金额越低；夫妻双生命会显著拉长负债期限，使月领金额平均下降约 15.23%；单向棘轮机制能压制机构风险，但会牺牲部分现金流连续性。
