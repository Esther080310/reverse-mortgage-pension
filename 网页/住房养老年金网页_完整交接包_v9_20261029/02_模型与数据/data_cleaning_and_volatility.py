import pandas as pd
import numpy as np
import os
import logging

# 配置日志（符合用户规范）
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def clean_and_calculate_volatility(input_dir: str, output_dir: str) -> None:
    """
    清洗全国70城房价数据，提取上海市数据，并计算各户型的年化波动率。
    注意（2026-10 起）：CSMAR 70城为行政平滑指数，仅作平滑基准对照；
    σ_H 主来源已改为马克数据网 gotohui 上海区级年度均价（见
    calculate_district_sigma_from_markdata 与白皮书σ章节）。
    
    Args:
        input_dir (str): 原始数据所在目录
        output_dir (str): 清洗后数据保存目录
    """
    try:
        # 1. 读取原始数据
        logger.info("正在读取原始房价面板数据...")
        df = pd.read_csv(os.path.join(input_dir, 'CME_MResidSalesPriceIndices.csv'))
        df_classify = pd.read_csv(os.path.join(input_dir, 'CME_MResidSalesClassifyPI.csv'))

        # 2. 清洗主表（整体市场）
        # 筛选条件：上海市 且 环比数据(Datasign='A')
        logger.info("正在清洗上海市整体二手住宅数据...")
        sh_df = df[(df['Cityname'] == '上海市') & (df['Datasign'] == 'A')].copy()
        sh_df['Monthly'] = pd.to_datetime(sh_df['Monthly'])
        sh_df = sh_df.sort_values('Monthly')
        sh_df['Nsecondresid'] = pd.to_numeric(sh_df['Nsecondresid'], errors='coerce')
        
        # 计算月度收益率 (指数100.4代表收益率0.004)
        sh_df['monthly_return'] = (sh_df['Nsecondresid'] - 100) / 100

        # 3. 清洗分类表（分户型市场）
        logger.info("正在清洗上海市分户型二手住宅数据...")
        sh_class_df = df_classify[(df_classify['Cityname'] == '上海市') & (df_classify['Datasign'] == 'A')].copy()
        sh_class_df['Monthly'] = pd.to_datetime(sh_class_df['Monthly'])
        sh_class_df = sh_class_df.sort_values('Monthly')
        
        # 批量处理三个户型的收益率
        size_columns = {
            'Secondresid90': '<=90平米(老破小)',
            'Secondresid90144': '90-144平米(改善型)',
            'Secondresid144': '>144平米(大平层)'
        }
        
        for col in size_columns.keys():
            sh_class_df[col] = pd.to_numeric(sh_class_df[col], errors='coerce')
            sh_class_df[f'{col}_return'] = (sh_class_df[col] - 100) / 100

        # 4. 保存清洗后的专属数据集
        logger.info("正在导出上海市专属数据集...")
        os.makedirs(output_dir, exist_ok=True)
        sh_df.to_csv(os.path.join(output_dir, 'Shanghai_MResidSalesPriceIndices.csv'), index=False, encoding='utf-8-sig')
        sh_class_df.to_csv(os.path.join(output_dir, 'Shanghai_MResidSalesClassifyPI.csv'), index=False, encoding='utf-8-sig')

        # 5. 计算并输出核心参数：年化波动率 (sigma)
        # 逻辑：年化波动率 = 月度收益率样本标准差 * sqrt(12)
        min_date = sh_df['Monthly'].min().strftime('%Y-%m')
        max_date = sh_df['Monthly'].max().strftime('%Y-%m')
        
        print("\n" + "="*50)
        print(f"【上海市二手住宅波动率测算报告】")
        print(f"数据区间: {min_date} 至 {max_date}")
        print("-" * 50)
        
        vol_overall = sh_df['monthly_return'].std() * np.sqrt(12)
        print(f"整体市场年化波动率 (Sigma): {vol_overall:.2%}")
        
        for col, desc in size_columns.items():
            vol = sh_class_df[f'{col}_return'].std() * np.sqrt(12)
            print(f"{desc} 年化波动率: {vol:.2%}")
        print("="*50 + "\n")
        
        # 6. σ_H 主来源（2026-10 起）：马克数据网 gotohui 区级年度均价
        logger.info("正在计算马克数据网区级σ（σ_H 主来源）...")
        dist_sigma = calculate_district_sigma_from_markdata(os.path.join(input_dir, "马克网"))
        print("【σ_H 主来源：马克数据网区级年度 2011-2020（完整无缺失）】")
        for k, v in dist_sigma.items():
            print(f"  {k}区 年化σ(实测) = {v:.2%}（模型采用值=四舍五入，见白皮书）")
        print("="*50 + "\n")
        
        logger.info("数据清洗与波动率测算完成！")

    except Exception as e:
        logger.error(f"处理过程中发生错误: {str(e)}")

def calculate_district_sigma_from_markdata(markdata_dir: str) -> dict:
    """计算上海现行 16 区年化对数收益波动率。

    个别区存在缺年，使用 log(P_t/P_t-1) / 年份间隔进行年化，避免把跨年
    变化误当成一年收益。卢湾、闸北和“市区”汇总口径不进入现行 16 区。
    """
    path = os.path.join(markdata_dir, "各区县房价.xlsx")
    dd = pd.read_excel(path, sheet_name="区县")
    dd.columns = [str(c).strip() for c in dd.columns]
    pcol = [c for c in dd.columns if "均价" in c][0]
    dd["年份"] = pd.to_numeric(dd["年份"], errors="coerce")
    dd[pcol] = pd.to_numeric(dd[pcol], errors="coerce")
    shd = dd[dd["城市"].astype(str) == "上海"].dropna(subset=["年份", pcol])
    districts = ["黄浦区", "徐汇区", "长宁区", "静安区", "普陀区", "虹口区", "杨浦区", "浦东新区", "闵行区", "宝山区", "嘉定区", "金山区", "松江区", "青浦区", "奉贤区", "崇明区"]
    result = {}
    for dist in districts:
        sub = shd[shd["区县"].astype(str) == dist].sort_values("年份")
        years = sub["年份"].values.astype(float)
        prices = sub[pcol].values.astype(float)
        lr = np.diff(np.log(prices)) / np.diff(years)
        result[dist.removesuffix("区")] = float(np.std(lr, ddof=1))
    return result


if __name__ == "__main__":
    # 定义输入输出路径
    base_path = r'd:\软件工具\WPS\241912900\WPS云盘\科创\挑战杯、互联网加\以房养老信托\以房养老大创\房价数据和建模'
    clean_and_calculate_volatility(input_dir=base_path, output_dir=base_path)
