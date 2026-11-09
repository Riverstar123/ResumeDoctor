import type { JobContent, ProfileContent, RequirementAssessment } from '../types';

export type InterviewLang = 'zh' | 'en';
export type InterviewCategory =
  | 'internship'
  | 'project'
  | 'skill'
  | 'gap'
  | 'education'
  | 'availability'
  | 'motivation'
  | 'behavior';

export type InterviewQuestion = {
  id: string;
  lang: InterviewLang;
  category: InterviewCategory;
  text: string;
  why: string;
};

type Fact = ProfileContent['facts'][number];

const EN_DOMAIN: Record<string, string> = {
  行业研究: 'research',
  数据分析: 'data analysis',
  投资: 'investment',
  投行: 'investment banking',
  审计: 'audit',
  咨询: 'consulting',
  量化: 'quantitative research',
};

function attribute(fact: Fact, name: string): string | null {
  return fact.attributes?.find((item) => item.name === name)?.value ?? null;
}

function period(fact: Fact): string {
  if (!fact.start_month && !fact.end_month) return '';
  const start = fact.start_month?.replace('-', ' 年 ') ?? '';
  const end = fact.end_month?.replace('-', ' 年 ') ?? '';
  return [start, end].filter(Boolean).join(' – ');
}

function periodEn(fact: Fact): string {
  if (!fact.start_month && !fact.end_month) return '';
  return [fact.start_month, fact.end_month].filter(Boolean).join(' to ');
}

function question(
  lang: InterviewLang,
  category: InterviewCategory,
  id: string,
  text: string,
  why: string,
): InterviewQuestion {
  return { id: `${lang}:${category}:${id}`, lang, category, text, why };
}

export function buildInterviewQuestions(
  profile: ProfileContent,
  job?: JobContent,
  assessments?: RequirementAssessment[],
): Record<InterviewLang, InterviewQuestion[]> {
  const zh: InterviewQuestion[] = [];
  const en: InterviewQuestion[] = [];
  const facts = profile.facts ?? [];
  const requirements = new Map((job?.requirements ?? []).map((item) => [item.id, item]));

  for (const fact of facts) {
    if (fact.kind === 'experience') {
      const domain = attribute(fact, 'experience_domain') ?? fact.label;
      const type = attribute(fact, 'experience_type');
      const when = period(fact);
      const where = when ? `${when}的${domain}` : domain;
      const enDomain = EN_DOMAIN[domain] ?? '';
      const enWhen = periodEn(fact);
      zh.push(
        question(
          'zh',
          'internship',
          `${fact.id}:1`,
          `你在${where}${type === 'internship' ? '实习' : '经历'}中，具体负责哪部分工作？`,
          `来自你的经历事实：${domain}${when ? `（${when}）` : ''}`,
        ),
        question(
          'zh',
          'internship',
          `${fact.id}:2`,
          `这段${domain}经历中，你遇到的最大挑战是什么？最后怎么解决的？`,
          '面试官常用 STAR 追问经历细节',
        ),
        question(
          'zh',
          'internship',
          `${fact.id}:3`,
          `这段经历里，你做过的事情对这个岗位有什么帮助？`,
          '验证经历与目标岗位的关联',
        ),
      );
      en.push(
        question(
          'en',
          'internship',
          `${fact.id}:1`,
          `Walk me through your ${enDomain ? `${enDomain} ` : ''}internship${enWhen ? ` from ${enWhen}` : ''}.`,
          '基于你的实习事实',
        ),
        question(
          'en',
          'internship',
          `${fact.id}:2`,
          'What was the biggest challenge in that role, and how did you handle it?',
          '行为面常用问法',
        ),
      );
    }
    if (fact.kind === 'project') {
      const skill = fact.label;
      zh.push(
        question(
          'zh',
          'project',
          `${fact.id}:1`,
          `你在项目里用 ${skill} 处理了什么数据？能举一个具体例子吗？`,
          `来自你的项目事实：${skill}`,
        ),
        question(
          'zh',
          'project',
          `${fact.id}:2`,
          `用 ${skill} 完成的工作中，哪一步最花时间？为什么？`,
          '验证技能是否真正使用过',
        ),
      );
      en.push(
        question(
          'en',
          'project',
          `${fact.id}:1`,
          `Which project did you use ${skill} for, and what did you do?`,
          `来自你的项目事实：${skill}`,
        ),
      );
    }
    if (fact.kind === 'education') {
      const institution = attribute(fact, 'institution');
      const major = attribute(fact, 'major') ?? fact.label;
      if (institution) {
        zh.push(
          question(
            'zh',
            'education',
            `${fact.id}:1`,
            fact.completed === false
              ? `你目前在${institution}读${major}，预计什么时候毕业？`
              : `你在${institution}的${major}背景，对申请这个岗位有什么帮助？`,
            `来自你的学历事实：${institution} · ${major}`,
          ),
        );
        en.push(
          question(
            'en',
            'education',
            `${fact.id}:1`,
            `You studied ${major} at ${institution}. How does it help you in this role?`,
            `来自你的学历事实：${institution} · ${major}`,
          ),
        );
      }
    }
    if (fact.kind === 'availability') {
      const days = attribute(fact, 'availability_days');
      const months = attribute(fact, 'availability_months');
      if (days || months) {
        const parts = [days && `每周 ${days} 天`, months && `实习 ${months} 个月`].filter(Boolean);
        zh.push(
          question(
            'zh',
            'availability',
            `${fact.id}:1`,
            `你${parts.join('、')}的安排能保证吗？如果课程冲突怎么处理？`,
            '确认到岗承诺是否可靠',
          ),
        );
        en.push(
          question(
            'en',
            'availability',
            `${fact.id}:1`,
            'Can you commit to the schedule you described? How would you handle course conflicts?',
            '确认到岗承诺是否可靠',
          ),
        );
      }
    }
  }

  const seen = new Set<string>();
  for (const assessment of assessments ?? []) {
    const requirement = requirements.get(assessment.requirement_id);
    if (!requirement || assessment.counted_in_score === false) continue;
    if (seen.has(assessment.requirement_id)) continue;
    seen.add(assessment.requirement_id);
    if (assessment.status === 'met') {
      zh.push(
        question(
          'zh',
          'skill',
          assessment.requirement_id,
          `岗位要求「${requirement.quote}」，你在哪段经历里体现过？能具体讲讲吗？`,
          '已满足项也需要能用例子说明',
        ),
      );
    } else if (assessment.status === 'unknown') {
      zh.push(
        question(
          'zh',
          'gap',
          assessment.requirement_id,
          `岗位要求「${requirement.quote}」，你的简历里没有明确写，是没接触过，还是没写？`,
          assessment.reason || '该项缺少可核验证据',
        ),
      );
      en.push(
        question(
          'en',
          'gap',
          assessment.requirement_id,
          'The role lists a requirement your resume does not clearly cover. Have you used it, or did you leave it out?',
          '对应你简历中的一项缺口',
        ),
      );
    }
  }

  zh.push(
    question('zh', 'motivation', 'why-role', '你为什么想申请这个岗位？', '动机题高频'),
    question('zh', 'motivation', 'why-finance', '为什么选择金融行业？', '动机题高频'),
    question(
      'zh',
      'behavior',
      'pressure',
      '举例说明你如何在时间紧张的情况下按时完成任务。',
      '行为面常用 STAR',
    ),
    question(
      'zh',
      'behavior',
      'conflict',
      '和团队成员意见不一致时，你会怎么处理？',
      '团队协作题高频',
    ),
  );
  en.push(
    question('en', 'motivation', 'intro', 'Please introduce yourself briefly.', '英文面必问'),
    question('en', 'motivation', 'why-role', 'Why are you interested in this role?', '英文动机题'),
    question(
      'en',
      'behavior',
      'challenge',
      'Describe a challenge you faced and how you handled it.',
      '英文行为题',
    ),
    question(
      'en',
      'behavior',
      'pressure',
      'Tell me about a time you worked under pressure.',
      '英文行为题',
    ),
    question(
      'en',
      'motivation',
      'future',
      'Where do you see yourself in three years?',
      '英文职业规划题',
    ),
  );

  return { zh, en };
}

export function drawQuestions(
  pool: InterviewQuestion[],
  used: Set<string>,
  size = 3,
): InterviewQuestion[] {
  const available = pool.filter((item) => !used.has(item.id));
  const picked: InterviewQuestion[] = [];
  const categories = new Set<InterviewCategory>();
  for (const item of shuffle(available)) {
    if (picked.length >= size) break;
    if (categories.has(item.category)) continue;
    categories.add(item.category);
    picked.push(item);
  }
  for (const item of shuffle(available)) {
    if (picked.length >= size) break;
    if (picked.includes(item)) continue;
    picked.push(item);
  }
  return picked;
}

function shuffle<T>(items: T[]): T[] {
  const copy = [...items];
  for (let index = copy.length - 1; index > 0; index -= 1) {
    const swap = Math.floor(Math.random() * (index + 1));
    [copy[index], copy[swap]] = [copy[swap], copy[index]];
  }
  return copy;
}
