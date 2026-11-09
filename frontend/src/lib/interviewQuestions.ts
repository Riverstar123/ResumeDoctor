import type { JobContent, ProfileContent, RequirementAssessment } from '../types';

export type InterviewLang = 'zh' | 'en';
export type InterviewCategory =
  | 'internship'
  | 'project'
  | 'skill'
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

const EXPERIENCE_LABEL: Record<string, string> = {
  internship: '实习',
  employment: '工作经历',
  volunteer: '志愿经历',
};

const ENGLISH_SKILLS = new Set([
  'python',
  'sql',
  'excel',
  'r',
  'matlab',
  'tableau',
  'power bi',
  'vba',
  'spss',
  'stata',
  'wind',
  'bloomberg',
  'docker',
  'java',
  'javascript',
]);

const COMPANY_PATTERN =
  /(?:在|于)([一-鿿A-Za-z0-9（）()·]{2,30}?(?:证券|银行|基金|投行|信托|保险|咨询|资本|资产|会计|研究院|研究所|集团)[一-鿿A-Za-z0-9（）()·]{0,8})/;

function attribute(fact: Fact, name: string): string | null {
  return fact.attributes?.find((item) => item.name === name)?.value ?? null;
}

function month(value: string | null): string {
  if (!value) return '';
  const [year, raw] = value.split('-');
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? `${year} 年 ${parsed} 月` : value;
}

function period(fact: Fact): string {
  const start = month(fact.start_month);
  const end = month(fact.end_month);
  return [start, end].filter(Boolean).join('至');
}

function periodEn(fact: Fact): string {
  return [fact.start_month, fact.end_month].filter(Boolean).join(' to ');
}

function companyOf(fact: Fact, evidence: Map<string, string>): string | null {
  for (const id of fact.evidence_ids ?? []) {
    const quote = evidence.get(id);
    if (!quote) continue;
    const match = COMPANY_PATTERN.exec(quote);
    if (match) return match[1];
  }
  return null;
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

function isEnglishSkill(label: string): boolean {
  return ENGLISH_SKILLS.has(label.trim().toLowerCase());
}

export function buildInterviewQuestions(
  profile: ProfileContent,
  job?: JobContent,
  assessments?: RequirementAssessment[],
): Record<InterviewLang, InterviewQuestion[]> {
  const zh: InterviewQuestion[] = [];
  const en: InterviewQuestion[] = [];
  const facts = profile.facts ?? [];
  const evidence = new Map((profile.evidence ?? []).map((item) => [item.id, item.quote]));
  const requirements = new Map((job?.requirements ?? []).map((item) => [item.id, item]));

  for (const fact of facts) {
    if (fact.polarity === 'negative') continue;
    if (fact.kind === 'experience') {
      const domain = attribute(fact, 'experience_domain') ?? fact.label;
      const type = attribute(fact, 'experience_type') ?? 'internship';
      const typeLabel = EXPERIENCE_LABEL[type] ?? '经历';
      const company = companyOf(fact, evidence);
      const when = period(fact);
      const where = company ?? domain;
      const context = when ? `${where}（${when}）` : where;
      const enDomain = EN_DOMAIN[domain] ?? '';
      const enType =
        type === 'employment'
          ? 'role'
          : type === 'volunteer'
            ? 'volunteer experience'
            : 'internship';
      const enWhen = periodEn(fact);
      zh.push(
        question(
          'zh',
          'internship',
          `${fact.id}:1`,
          `你在${context}这段${typeLabel}中，最大的收获是什么？`,
          company ? `来自你的经历原文：${company}` : `来自你的${typeLabel}事实：${domain}`,
        ),
        question(
          'zh',
          'internship',
          `${fact.id}:2`,
          `这段${typeLabel}里，你具体负责哪部分工作？能举一个例子吗？`,
          '面试官常用 STAR 追问经历细节',
        ),
        question(
          'zh',
          'internship',
          `${fact.id}:3`,
          `这段经历中，你遇到的最大困难是什么？最后怎么解决的？`,
          '验证真实参与程度和解决问题能力',
        ),
        question(
          'zh',
          'internship',
          `${fact.id}:4`,
          `这段${typeLabel}里，你做的哪件事最有成就感？`,
          '行为面常用成就故事',
        ),
        question(
          'zh',
          'internship',
          `${fact.id}:5`,
          `如果让你重新做一次这段${typeLabel}，你会改进什么？`,
          '考察复盘和反思能力',
        ),
      );
      en.push(
        question(
          'en',
          'internship',
          `${fact.id}:1`,
          `Walk me through your ${enDomain ? `${enDomain} ` : ''}${enType}${enWhen ? ` from ${enWhen}` : ''}.`,
          '基于你的经历事实',
        ),
        question(
          'en',
          'internship',
          `${fact.id}:2`,
          'What was the most valuable thing you learned from that experience?',
          '行为面常用问法',
        ),
        question(
          'en',
          'internship',
          `${fact.id}:3`,
          'What was the biggest challenge, and how did you handle it?',
          '行为面常用问法',
        ),
      );
    }
    if (fact.kind === 'project') {
      const label = fact.label;
      if (isEnglishSkill(label)) {
        zh.push(
          question(
            'zh',
            'project',
            `${fact.id}:1`,
            `你在项目里用 ${label} 做了什么？能举一个具体例子吗？`,
            `来自你的项目事实：${label}`,
          ),
          question(
            'zh',
            'project',
            `${fact.id}:2`,
            `用 ${label} 的过程中遇到过什么问题？你是怎么解决的？`,
            '验证技能使用的真实深度',
          ),
          question(
            'zh',
            'project',
            `${fact.id}:3`,
            `你用 ${label} 得到的结果，最后怎么用了？`,
            '确认结果是否真正落地',
          ),
        );
        en.push(
          question(
            'en',
            'project',
            `${fact.id}:1`,
            `Which project did you use ${label} for, and what did you do?`,
            `来自你的项目事实：${label}`,
          ),
        );
      } else {
        zh.push(
          question(
            'zh',
            'project',
            `${fact.id}:1`,
            `你在「${label}」这个项目里负责什么？最大的收获是什么？`,
            `来自你的项目事实：${label}`,
          ),
          question(
            'zh',
            'project',
            `${fact.id}:2`,
            `这个项目里哪一步最难？你是怎么解决的？`,
            '验证项目参与深度',
          ),
          question(
            'zh',
            'project',
            `${fact.id}:3`,
            `这个项目最后产出了什么？你在其中的具体贡献是什么？`,
            '区分个人贡献与团队成果',
          ),
        );
        en.push(
          question(
            'en',
            'project',
            `${fact.id}:1`,
            'Tell me about a project you worked on and what you were responsible for.',
            `来自你的项目事实：${label}`,
          ),
        );
      }
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
            `你在${institution}读${major}，这段学习经历对申请这个岗位有什么帮助？`,
            `来自你的学历事实：${institution} · ${major}`,
          ),
          question(
            'zh',
            'education',
            `${fact.id}:2`,
            `你在学校学过哪些和这个岗位相关的课程或项目？`,
            '验证专业背景与岗位的相关性',
          ),
        );
        en.push(
          question(
            'en',
            'education',
            `${fact.id}:1`,
            'How does your academic background help you in this role?',
            '学历与岗位关联',
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
          question(
            'zh',
            'availability',
            `${fact.id}:2`,
            `如果实习期间学校临时有安排，你会怎么平衡？`,
            '确认时间承诺的稳定性',
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
    if (assessment.status !== 'met') continue;
    if (requirement.category === 'education' || requirement.category === 'other') continue;
    const quote = requirement.quote.replace(/[。；;，,！!？?]+$/, '');
    if (requirement.category === 'skill') {
      zh.push(
        question(
          'zh',
          'skill',
          assessment.requirement_id,
          `岗位要求「${quote}」，你在哪段经历或项目里实际用过？能具体讲讲吗？`,
          '已满足项也需要能用例子说明',
        ),
      );
      const target = requirement.target?.trim() ?? '';
      en.push(
        question(
          'en',
          'skill',
          assessment.requirement_id,
          isEnglishSkill(target)
            ? `The role requires ${target}. Where have you applied it?`
            : 'The role lists a skill you have demonstrated. Where have you applied it?',
          '已满足技能需要具体例子',
        ),
      );
    } else if (requirement.category === 'experience' || requirement.category === 'project') {
      zh.push(
        question(
          'zh',
          'internship',
          assessment.requirement_id,
          `岗位要求「${quote}」，你在哪段经历里体现过？`,
          '验证经历与岗位要求的对应关系',
        ),
      );
    }
  }

  zh.push(
    question('zh', 'motivation', 'why-role', '你为什么想申请这个岗位？', '动机题高频'),
    question('zh', 'motivation', 'why-field', '为什么选择这个方向？', '动机题高频'),
    question('zh', 'motivation', 'why-you', '你觉得你最适合这个岗位的一点是什么？', '自我认知题'),
    question('zh', 'motivation', 'plan', '你未来三年的职业规划是什么？', '职业规划题'),
    question('zh', 'motivation', 'industry', '你最近关注的行业变化是什么？', '行业理解题'),
    question('zh', 'motivation', 'company', '你为什么想加入这个团队？', '动机题高频'),
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
    question('zh', 'behavior', 'failure', '讲一次失败的经历，你从中学到了什么？', '行为面常用'),
    question('zh', 'behavior', 'priority', '多项任务同时进行时，你怎么安排优先级？', '时间管理题'),
    question('zh', 'behavior', 'initiative', '举一个你主动推动事情完成的例子。', '主动性题'),
    question('zh', 'behavior', 'feedback', '别人批评你的工作时，你会怎么处理？', '反馈与抗压题'),
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
    question(
      'en',
      'motivation',
      'why-you',
      'What makes you a good fit for this role?',
      '英文自我认知题',
    ),
    question(
      'en',
      'behavior',
      'teamwork',
      'Tell me about a time you worked in a team.',
      '英文团队协作题',
    ),
    question(
      'en',
      'behavior',
      'failure',
      'Tell me about a failure and what you learned.',
      '英文行为题',
    ),
    question(
      'en',
      'behavior',
      'priority',
      'How do you prioritize when several tasks are due at once?',
      '英文时间管理题',
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
