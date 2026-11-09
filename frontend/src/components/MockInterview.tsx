import { useMemo, useState } from 'react';
import {
  buildInterviewQuestions,
  drawQuestions,
  type InterviewCategory,
  type InterviewLang,
  type InterviewQuestion,
} from '../lib/interviewQuestions';
import type { JobContent, ProfileContent, RequirementAssessment } from '../types';

const CATEGORY: Record<InterviewCategory, string> = {
  internship: '实习经历',
  project: '项目',
  skill: '技能',
  gap: '缺口',
  education: '学历',
  availability: '到岗',
  motivation: '动机',
  behavior: '行为',
};

export function MockInterview({
  profile,
  job,
  assessments,
}: {
  profile: ProfileContent;
  job?: JobContent;
  assessments?: RequirementAssessment[];
}) {
  const pools = useMemo(
    () => buildInterviewQuestions(profile, job, assessments),
    [profile, job, assessments],
  );
  const [lang, setLang] = useState<InterviewLang | null>(null);
  const [used, setUsed] = useState<Set<string>>(new Set());
  const [round, setRound] = useState<InterviewQuestion[]>([]);

  const start = (next: InterviewLang) => {
    setLang(next);
    setUsed(new Set());
    setRound(drawQuestions(pools[next], new Set(), 3));
  };
  const nextRound = () => {
    if (!lang) return;
    const seen = new Set(used);
    round.forEach((item) => seen.add(item.id));
    setUsed(seen);
    setRound(drawQuestions(pools[lang], seen, 3));
  };

  return (
    <section className="panel mock-interview" aria-label="模拟面试">
      <div className="section-heading">
        <div>
          <p className="eyebrow">MOCK INTERVIEW</p>
          <h2>模拟面试</h2>
        </div>
        <span className="tag">根据你的简历随机提问</span>
      </div>
      <p className="muted">
        每轮 3 题，不重复；问题来自你的经历、技能和缺口，仅供准备参考，不代表真实面试题。
      </p>
      {!lang ? (
        <div className="interview-actions">
          <button className="button" onClick={() => start('zh')}>
            中文面
          </button>
          <button className="button secondary" onClick={() => start('en')}>
            English
          </button>
        </div>
      ) : (
        <>
          <div className="interview-toolbar">
            <strong>{lang === 'zh' ? '中文面' : 'English'}</strong>
            <span className="hint">
              已抽 {used.size + round.length} / {pools[lang].length}
            </span>
          </div>
          {round.length ? (
            <ol className="interview-list">
              {round.map((item) => (
                <li key={item.id}>
                  <span className="tag">{CATEGORY[item.category]}</span>
                  <p>{item.text}</p>
                  <details>
                    <summary>为什么问这个</summary>
                    <small>{item.why}</small>
                  </details>
                </li>
              ))}
            </ol>
          ) : (
            <p className="hint">这一轮题库已经抽完，可以重新开始。</p>
          )}
          <div className="interview-actions">
            <button
              className="button secondary"
              onClick={nextRound}
              disabled={round.length === 0 || used.size + round.length >= pools[lang].length}
            >
              下一轮
            </button>
            <button className="text-button" onClick={() => start(lang)}>
              重新开始
            </button>
            <button className="text-button" onClick={() => setLang(null)}>
              切换语言
            </button>
          </div>
        </>
      )}
    </section>
  );
}
