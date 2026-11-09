import type { ReactNode } from 'react';
import { IconCheck, IconScale, IconShield, IconSpark } from './Icons';

// First screen before the session starts. The consent panel is passed in as
// `children` so the privacy copy and its logic stay in Shell. Everything else
// here is illustration: decorative parts are aria-hidden and use clearly
// labelled sample values, never real profile or score data.
export function Landing({ children }: { children: ReactNode }) {
  return (
    <>
      <div className="consent-layout">
        <div className="hero-copy">
          <p className="hero-badge">
            <span className="hero-badge-chip">
              <IconSpark />
              有据可循
            </span>
            AI 提取事实 · 规则计算分数
          </p>
          <h1 className="hero-title">
            让你的经历，
            <br />
            <span className="gradient-text">更接近理想岗位。</span>
          </h1>
          <p className="lead">
            从一份简历或一段对话开始。逐项核对经历与岗位要求，找到有依据的修改方向。
          </p>
          <ol className="intro-steps">
            <li>
              <em>01</em>
              <strong>整理真实经历</strong>
              <span>上传简历，或用对话整理</span>
            </li>
            <li>
              <em>02</em>
              <strong>确认目标岗位</strong>
              <span>添加 1–5 个岗位 JD</span>
            </li>
            <li>
              <em>03</em>
              <strong>获得行动建议</strong>
              <span>证据、差距与改写方向</span>
            </li>
          </ol>
          <ul className="hero-facts">
            <li>1–5 个岗位独立评分</li>
            <li>逐条要求对照原文证据</li>
            <li>匿名使用，资料可随时删除</li>
          </ul>
        </div>
        <div className="hero-stage">
          <div className="stage-glow" aria-hidden="true" />
          <div className="stage-orbit" aria-hidden="true" />
          <div className="preview-card" aria-hidden="true">
            <span className="preview-scan" />
            <div className="preview-head">
              岗位匹配
              <em>示例</em>
            </div>
            <div className="preview-body">
              <div className="preview-ring">
                <b>
                  <small>示例分</small>
                </b>
              </div>
              <ul className="preview-reqs">
                <li className="is-met">
                  SQL 分析
                  <i />
                </li>
                <li className="is-partial">
                  数据可视化
                  <i />
                </li>
                <li className="is-unknown">
                  A/B 实验
                  <i />
                </li>
              </ul>
            </div>
          </div>
          {children}
          <div className="float-chip chip-evidence" aria-hidden="true">
            <span className="chip-icon">
              <IconCheck />
            </span>
            <span>
              找到原文证据
              <small>项目经历 · 第 2 条</small>
            </span>
          </div>
          <div className="float-chip chip-score" aria-hidden="true">
            <span className="chip-icon">
              <IconScale />
            </span>
            <span>
              规则计算分数
              <small>报告不会改动分数</small>
            </span>
          </div>
        </div>
      </div>
      <section className="feature-band" aria-labelledby="feature-title">
        <div className="feature-head">
          <p className="eyebrow">How it works</p>
          <h2 id="feature-title">
            不是泛泛点评，
            <br />
            <span className="gradient-text">而是逐条有据的诊断</span>
          </h2>
          <p>每个判断都能追溯到你提供的原文；缺少证据会如实标注，而不会被当作不具备。</p>
        </div>
        <div className="feature-grid">
          <article className="feature-card wide">
            <div className="feature-visual" aria-hidden="true">
              <div className="fv-evidence">
                <div className="fv-col">
                  <span className="fv-pill is-met">要求 · SQL 分析</span>
                  <span className="fv-pill is-partial">要求 · 数据可视化</span>
                  <span className="fv-pill is-unknown">要求 · A/B 实验</span>
                </div>
                <div className="fv-wires">
                  <i />
                  <i />
                  <i />
                </div>
                <div className="fv-col">
                  <span className="fv-pill is-met">项目经历原文</span>
                  <span className="fv-pill is-partial">实习经历原文</span>
                  <span className="fv-pill is-unknown">待补充证据</span>
                </div>
              </div>
            </div>
            <h3>每条要求，都对照原文证据</h3>
            <p>逐条比对岗位要求与你的经历原文。找不到证据时标记为待补充：缺少证据不等于不具备。</p>
          </article>
          <article className="feature-card">
            <div className="feature-visual" aria-hidden="true">
              <div className="fv-bars">
                <span>
                  <em>岗位 A</em>
                </span>
                <span>
                  <em>岗位 B</em>
                </span>
                <span>
                  <em>岗位 C</em>
                </span>
              </div>
            </div>
            <h3>多个岗位，各自独立评分</h3>
            <p>一次可对照 1–5 个目标岗位，每个岗位单独计算，互不影响。</p>
          </article>
          <article className="feature-card">
            <div className="feature-visual" aria-hidden="true">
              <div className="fv-split">
                <span className="fv-node ai">
                  <IconSpark />
                  AI 提取
                </span>
                <span className="fv-link" />
                <span className="fv-node rule">
                  <IconScale />
                  规则计分
                </span>
              </div>
            </div>
            <h3>AI 提取，规则定分</h3>
            <p>AI 负责提取事实和生成建议；分数由确定性规则计算，报告不会改动分数。</p>
          </article>
          <article className="feature-card wide">
            <div className="feature-visual" aria-hidden="true">
              <div className="fv-shield">
                <span className="fv-shield-core">
                  <IconShield />
                </span>
                <span className="fv-pill">匿名会话</span>
                <span className="fv-pill">随时删除</span>
                <span className="fv-pill">敏感信息不计分</span>
              </div>
            </div>
            <h3>你的资料，始终由你掌握</h3>
            <p>
              无需注册，匿名会话 7
              天有效，可随时删除本会话全部资料；性别、年龄、籍贯、照片等信息不参与评分。
            </p>
          </article>
        </div>
      </section>
    </>
  );
}
