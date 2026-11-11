// The same synthetic case is used by the presentation and the HTTP workbench.
// A regression test compares this data with public/showcase/case-data.js.
export const showcaseCase = {
  resume: `林予安｜求职演示合成简历
教育：2022年9月至2026年6月，财务管理专业，已取得本科学历。
实习：2026年3月至2026年6月，虚构公司澄禾零售，经营分析实习生。用 SQL 汇总订单数据，用 Python pandas 清洗订单记录，使用 Excel 数据透视表按门店汇总销售与退货，制作每周经营报表，供运营团队复盘。
课程项目：2025年9月至2025年12月，使用 Python pandas 处理零售订单样本，计算复购率并撰写课程报告。`,
  jobs: [
    {
      name: '经营数据分析',
      text: `岗位：经营数据分析实习生（虚构岗位）
要求：本科及以上学历。
能用 SQL 汇总业务数据。
能用 Python pandas 清洗数据。
有 A/B 实验实践经验者优先。`,
    },
    {
      name: '财务分析',
      text: `岗位：财务分析实习生（虚构岗位）
要求：本科及以上学历。
能用 Excel 数据透视表汇总业务数据。
有分析上市公司财务报表的实务经验。
有预算编制经验者优先。`,
    },
  ],
};
