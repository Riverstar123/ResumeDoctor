import { useEffect, useMemo, useRef, useState } from 'react';
import {
  buildInterviewQuestions,
  drawQuestions,
  remainingQuestions,
  type InterviewCategory,
  type InterviewLang,
  type InterviewQuestion,
} from '../lib/interviewQuestions';
import type { JobContent, ProfileContent, RequirementAssessment } from '../types';

const CATEGORY: Record<InterviewCategory, string> = {
  experience: '经历',
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
  const dialogRef = useRef<HTMLDialogElement>(null);
  const resumeRef = useRef<HTMLButtonElement>(null);
  const questionRef = useRef<HTMLHeadingElement>(null);
  const current = round[index];
  const remaining = lang ? remainingQuestions(pools[lang], used) : [];
  const exhausted = remaining.length === 0;

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open) {
      if (!dialog.open) dialog.showModal();
      questionRef.current?.focus();
    } else if (dialog.open) {
      dialog.close();
      resumeRef.current?.focus();
    }
  }, [open, index]);

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
    const base = exhausted ? new Set<string>() : used;
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
        每轮最多 3 题，逐题练习。问题结合你的经历、技能和岗位要求，仅供面试准备参考。
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
            <button ref={resumeRef} className="button" onClick={nextRound}>
              {exhausted ? '重新开始' : '再来一轮'}
            </button>
          )}
          {finished && exhausted && <span className="hint">题库已抽完，重新开始会再次随机</span>}
          {!finished && !open && (
            <button ref={resumeRef} className="button" onClick={() => setOpen(true)}>
              继续本轮
            </button>
          )}
          <button className="text-button" onClick={reset}>
            切换语言
          </button>
        </div>
      )}
      <dialog
        ref={dialogRef}
        className="interview-modal"
        aria-label="模拟面试问题"
        onCancel={(event) => {
          event.preventDefault();
          setOpen(false);
        }}
      >
        {current && (
          <>
            <div className="interview-modal-head">
              <span className="eyebrow">
                第 {index + 1} / {round.length} 题
              </span>
              <button className="button secondary small" onClick={() => setOpen(false)}>
                关闭
              </button>
            </div>
            <span className="tag">{CATEGORY[current.category]}</span>
            <h2 className="interview-question" ref={questionRef} tabIndex={-1} lang={current.lang}>
              {current.text}
            </h2>
            <details className="interview-why">
              <summary>为什么问这个</summary>
              <small>{current.why}</small>
            </details>
            <button className="button interview-next" onClick={next}>
              {index < round.length - 1 ? '下一题' : '完成本轮'}
            </button>
          </>
        )}
      </dialog>
    </section>
  );
}
