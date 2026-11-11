'use strict';

// Selected fields transcribed from the live mf18 report for this synthetic case.
{
  const education = '教育：2022年9月至2026年6月，财务管理专业，已取得本科学历。';
  const internship = '实习：2026年3月至2026年6月，虚构公司澄禾零售，经营分析实习生。用 SQL 汇总订单数据，用 Python pandas 清洗订单记录，使用 Excel 数据透视表按门店汇总销售与退货，制作每周经营报表，供运营团队复盘。';
  const bachelor = {
    title: '本科及以上学历',
    state: '已满足',
    evidence: education,
    reason: '明确记录了已经取得的本科学历。',
  };
  const review = (title, reason) => ({
    title,
    state: '待人工核验',
    evidence: internship,
    reason,
  });
  window.resumeDoctorResults = {
    jobs: [
      {
        score: '85.7',
        range: '14.29% 要求权重待人工核验',
        requirements: [
          { title: '能用 SQL 汇总业务数据', state: '已满足', evidence: internship, reason: '原文记录了使用 SQL 汇总订单数据的实际任务。' },
          { title: '能用 Python pandas 清洗数据', state: '已满足', evidence: internship, reason: '原文记录了使用 Python pandas 清洗订单记录的实际任务。' },
          bachelor,
          review('有 A/B 实验实践经验者优先', '这段经历可用于核对，原文描述的是订单分析，没有给出 A/B 实验经历。此项计入总权重，暂不给分。'),
        ],
      },
      {
        score: '57.1',
        range: '42.86% 要求权重待人工核验',
        requirements: [
          { title: '能用 Excel 数据透视表汇总业务数据', state: '已满足', evidence: internship, reason: '原文明确写了用数据透视表按门店汇总销售和退货。' },
          review('有分析上市公司财务报表的实务经验', '原文对应零售经营报表。上市公司财报实务需另外核对，此项计入总权重，暂不给分。'),
          review('有预算编制经验者优先', '原文描述的是经营报表制作。预算编制经验需另外核对，此项计入总权重，暂不给分。'),
          bachelor,
        ],
      },
    ],
    ai: {
      source: '使用 Excel 数据透视表按门店汇总销售与退货，制作每周经营报表，供运营团队复盘。',
      fact: 'DeepSeek 整理为经营分析实习，识别出 SQL、Python pandas、Excel 数据透视表等技能。档案确认前可对照原文修正。',
      title: '财务分析岗位 · 经营分析实习',
      rewrite: '以 Excel 数据透视表按门店、周次两个维度汇总销售额与退货数据，输出各门店销售与退货对比的每周经营报表，供运营团队复盘使用。',
      why: '试着把“按门店、周次两个维度”改为“按门店”，并把“销售额”改为“销售”。原文只写了按门店汇总、每周产出。把可核实的工具、任务和用途留在草稿里。',
    },
  };
}
