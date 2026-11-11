'use strict';

const byId = (id) => document.getElementById(id);
const scenes = [...document.querySelectorAll('.scene')];
const navigation = [...document.querySelectorAll('.top nav a')];
const sample = window.resumeDoctorCase;
const results = window.resumeDoctorResults;
const replay = window.resumeDoctorVersionReplay;
const versionButtons = [...document.querySelectorAll('[data-version]')];
const languageButtons = [...document.querySelectorAll('[data-language]')];
let activePage = 0;
let selectedJob = 0;
let language = 'zh';
let questionIndex = 0;
let feedbackTimer;

if (location.protocol === 'file:') {
  document.querySelectorAll('a[href="/?example=1"]').forEach((link) => {
    link.href = 'https://mf18.show.lingnan.top/?example=1';
  });
}

function go() {
  clearTimeout(feedbackTimer);
  byId('feedback').textContent = '';
  const id = location.hash.slice(1);
  const ordinal = /^\d+$/.test(id) ? Number(id) - 1 : -1;
  const nextPage = scenes[ordinal] ? ordinal : scenes.findIndex((scene) => scene.id === id);
  activePage = Math.max(0, nextPage);
  scenes.forEach((scene, index) => { scene.hidden = index !== activePage; });
  navigation.forEach((link) => {
    if (link.hash === `#${scenes[activePage].dataset.part}`) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  byId('page-label').textContent = `${String(activePage + 1).padStart(2, '0')} / ${String(scenes.length).padStart(2, '0')} · ${scenes[activePage].dataset.label}`;
  byId('progress-line').style.width = `${100 * (activePage + 1) / scenes.length}%`;
  byId('prev').disabled = activePage === 0;
  byId('next').disabled = activePage === scenes.length - 1;
  if (nextPage >= 0) scenes[activePage].querySelector('h1,h2').focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

function turn(offset) {
  const target = scenes[activePage + offset];
  if (target) location.hash = target.id;
}

function makeChoice(text, pressed) {
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = text;
  button.setAttribute('aria-pressed', String(pressed));
  return button;
}

function showEvidence(requirement, index) {
  [...byId('requirement-list').children].forEach((button, number) =>
    button.setAttribute('aria-pressed', String(index === number)),
  );
  byId('evidence-label').textContent = requirement.evidence ? '简历原文' : '当前证据';
  byId('evidence-quote').textContent = requirement.evidence || '这条要求没有可引用的简历证据。';
  byId('evidence-reason').textContent = requirement.reason;
}

function showJob(index) {
  selectedJob = index;
  const result = results.jobs[index];
  [...byId('job-buttons').children].forEach((button, number) =>
    button.setAttribute('aria-pressed', String(index === number)),
  );
  byId('score-value').textContent = result.score;
  byId('score-range').textContent = result.range;
  byId('requirement-list').replaceChildren(...result.requirements.map((requirement, number) => {
    const button = makeChoice(requirement.title, number === 0);
    const state = document.createElement('small');
    state.textContent = requirement.state;
    if (requirement.state !== '已满足') state.className = 'unknown';
    button.append(state);
    button.addEventListener('click', () => showEvidence(requirement, number));
    return button;
  }));
  showEvidence(result.requirements[0], 0);
}

function showVersion(index) {
  const snapshot = replay.states[index];
  const hasEvidence = Boolean(snapshot.evidence);
  versionButtons.forEach((button, number) =>
    button.setAttribute('aria-pressed', String(index === number)),
  );
  byId('version-label').textContent = `已确认档案 · v${snapshot.version}`;
  const status = byId('version-state');
  status.textContent = snapshot.verified ? '已采纳 AI 判断' : hasEvidence ? '待采纳 AI 判断' : '待人工核验';
  status.classList.toggle('unknown', !snapshot.verified);
  byId('version-evidence-label').textContent = hasEvidence ? '新增原文证据' : '当前档案';
  byId('version-evidence').textContent = snapshot.evidence || '已确认的经历里没有 A/B 实验记录。';
  byId('version-reason').textContent = snapshot.verified
    ? '确认档案后，采纳 AI 对「优惠券文案实验」的判断。同一份 JD 重诊时，这条条件计分。'
    : hasEvidence
      ? 'AI 根据随机分组、转化率分析和本人分工给出满足条件的判断。当前只确认了档案，这条条件仍待采纳。'
      : '原文有订单分析经历。A/B 实验还缺少对应的可核对材料。';
}

function showQuestion() {
  const item = replay.questions[language][questionIndex];
  byId('question-text').textContent = item.text;
  byId('question-text').lang = language === 'zh' ? 'zh-CN' : 'en';
  byId('question-source').textContent = item.why;
  languageButtons.forEach((button) =>
    button.setAttribute('aria-pressed', String(button.dataset.language === language)),
  );
}

function announce(message) {
  clearTimeout(feedbackTimer);
  byId('feedback').textContent = message;
  feedbackTimer = setTimeout(() => { byId('feedback').textContent = ''; }, 3200);
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    announce('已复制');
  } catch {
    announce('复制不可用，可选中文字后手动复制。');
  }
}

sample.jobs.forEach((job, index) => {
  const button = makeChoice(job.name, index === 0);
  button.addEventListener('click', () => showJob(index));
  byId('job-buttons').append(button);
});
showJob(0);
byId('intake-evidence').textContent = sample.resume.split('\n').find((line) => line.startsWith('实习：'));
sample.jobs.forEach((job, index) => { byId(`job-text-${index}`).textContent = job.text; });
byId('version-requirement').textContent = replay.requirement;
byId('before-score').textContent = replay.states[0].score.toFixed(1);
byId('supplemented-score').textContent = replay.states[1].score.toFixed(1);
byId('after-score').textContent = replay.states[2].score.toFixed(1);
versionButtons.forEach((button, index) => button.addEventListener('click', () => showVersion(index)));
showVersion(0);
languageButtons.forEach((button) => button.addEventListener('click', () => {
  language = button.dataset.language;
  questionIndex = 0;
  showQuestion();
}));
byId('next-question').addEventListener('click', () => {
  questionIndex = (questionIndex + 1) % replay.questions[language].length;
  showQuestion();
});
showQuestion();
byId('ai-source').textContent = results.ai.source;
byId('ai-fact').textContent = results.ai.fact;
byId('ai-heading').textContent = results.ai.title;
byId('rewrite').value = results.ai.rewrite;
byId('ai-why').textContent = results.ai.why;
byId('reset').addEventListener('click', () => {
  byId('rewrite').value = results.ai.rewrite;
  announce('已恢复原草稿');
});
const copySources = {
  resume: () => sample.resume,
  job: () => sample.jobs[selectedJob].text,
  'job-0': () => sample.jobs[0].text,
  'job-1': () => sample.jobs[1].text,
  rewrite: () => byId('rewrite').value,
  supplement: () => replay.supplement,
};
document.querySelectorAll('[data-copy]').forEach((button) => {
  button.addEventListener('click', () => { void copy(copySources[button.dataset.copy]()); });
});
byId('prev').addEventListener('click', () => turn(-1));
byId('next').addEventListener('click', () => turn(1));
window.addEventListener('hashchange', go);
document.addEventListener('keydown', (event) => {
  if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey ||
      event.target.closest?.('textarea,input,select,[contenteditable]')) return;
  if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
    event.preventDefault();
    turn(event.key === 'ArrowLeft' ? -1 : 1);
  }
  if (event.key.toLowerCase() === 't') location.hash = 'flow';
});
go();
