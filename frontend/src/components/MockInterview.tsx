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
  const [index, setIndex] = useState(0);
  const [open, setOpen] = useState(false);
  const [finished, setFinished] = useState(false);

  const reset = () => {
    setLang(null);
    setRound([]);
    setIndex(0);
    setOpen(false);
    setFinished(false);
  };

  const start = (next: InterviewLang) => {
    setLang(next);
    setUsed(new Set());
    setRound(drawQuestions(pools[next], new Set(), 3));
    setIndex(0);
    setOpen(true);
    setFinished(false);
  };

  const nextRound = () => {
    if (!lang) return;
    const seen = new Set(used);
    round.forEach((item) => seen.add(item.id));
    const restart = pools[lang].every((item) => seen.has(item.id));
    const base = restart ? new Set<string>() : seen;
    setUsed(base);
    setRound(drawQuestions(pools[lang], base, 3));
    setIndex(0);
    setOpen(true);
    setFinished(false);
  };

  const next = () => {
    if (index < round.length - 1) {
      setIndex(index + 1);
      return;
    }
    const seen = new Set(used);
    round.forEach((item) => seen.add(item.id));
    setUsed(seen);
    setOpen(false);
    setFinished(true);
  };

  const current = round[index];
  const exhausted = lang ? used.size + round.length >= pools[lang].length : true;

  return (
    <section className="panel mock-interview" id="mock-interview" aria-label="模拟面试">
      <div className="section-heading">
        <div>
          <p className="eyebrow">MOCK INTERVIEW</p>
          <h2>模拟面试</h2>
        </div>
        <span className="tag">根据你的简历随机提问</span>
      </div>
      <p className="muted">
        每轮 3 题，逐题弹出；问题来自你的实习、项目、技能和岗位要求，仅供准备参考。
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
        <div className="interview-actions">
          {finished && (
            <button className="button" onClick={nextRound}>
              {exhausted ? '重新开始' : '再来一轮'}
            </button>
          )}
          {finished && exhausted && <span className="hint">题库已抽完，重新开始会再次随机</span>}
          {!finished && !open && (
            <button className="button" onClick={() => setOpen(true)}>
              继续本轮
            </button>
          )}
          <button className="text-button" onClick={reset}>
            切换语言
          </button>
        </div>
      )}
      {open && current && (
        <div
          className="interview-overlay"
          role="dialog"
          aria-modal="true"
          aria-label="模拟面试问题"
        >
          <div className="interview-modal">
            <div className="interview-modal-head">
              <span className="eyebrow">
                第 {index + 1} / {round.length} 题
              </span>
              <button className="text-button" onClick={reset}>
                关闭
              </button>
            </div>
            <span className="tag">{CATEGORY[current.category]}</span>
            <p className="interview-question">{current.text}</p>
            <details className="interview-why">
              <summary>为什么问这个</summary>
              <small>{current.why}</small>
            </details>
            <button className="button interview-next" onClick={next}>
              {index < round.length - 1 ? '下一题' : '完成本轮'}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
