const scoreClaim =
  /(?:总分|覆盖分|匹配分|匹配度|(?:当前|本次|简历|岗位|综合|自动|规则)(?:的)?(?:评分|得分|分数)|^(?:你的|您的)?(?:评分|得分|分数))\s*(?:为|是|达(?:到)?|[：:])?\s*(?:[0-9]+(?:\.[0-9]+)?|[零〇一二两三四五六七八九十百]+(?:点[零〇一二两三四五六七八九]+)?)(?=\s*(?:分|[%％/／]|[（(]|$))/u;
const separator = /([，,；;。！？!?\n]+|\.(?=\s|$))/u;
const oldScope = '评分仅覆盖规则可自动判断的要求，其余要求保留供人工核对。';

/** Keep the qualitative analysis while leaving the diagnosis score to the scorecard. */
export function reportSummaryForDisplay(summary: string): string {
  const text = summary.replace(oldScope, '');
  const parts = text.split(separator);
  let result = '';
  for (let index = 0; index < parts.length; index += 2) {
    if (!scoreClaim.test(parts[index].trim())) result += parts[index] + (parts[index + 1] ?? '');
  }
  return result === summary ? summary : result.trim().replace(/[，,；;]+$/u, '。');
}
