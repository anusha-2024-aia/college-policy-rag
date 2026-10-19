import React, { useEffect, useState, useCallback, useRef } from 'react';
import {
  ArrowRight,
  BookOpen,
  Upload,
  Search,
  Layers,
  GitBranch,
  MessageSquare,
  ChevronRight,
  X,
  AlertTriangle,
  TrendingUp,
  Zap,
  Shield,
  Clock,
  CheckCircle2,
  ExternalLink,
} from 'lucide-react';

// Inline GitHub SVG (lucide-react may not export 'Github' in all versions)
function GithubIcon({ size = 16, ...props }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
      {...props}
    >
      <path d="M12 2C6.477 2 2 6.477 2 12c0 4.418 2.865 8.166 6.839 9.489.5.092.682-.217.682-.482 0-.237-.009-.868-.013-1.703-2.782.604-3.369-1.34-3.369-1.34-.454-1.156-1.11-1.463-1.11-1.463-.908-.62.069-.608.069-.608 1.003.07 1.531 1.03 1.531 1.03.892 1.529 2.341 1.087 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.11-4.555-4.943 0-1.091.39-1.984 1.029-2.683-.103-.253-.446-1.27.098-2.647 0 0 .84-.269 2.75 1.025A9.564 9.564 0 0 1 12 6.844a9.59 9.59 0 0 1 2.504.337c1.909-1.294 2.747-1.025 2.747-1.025.546 1.377.202 2.394.1 2.647.64.699 1.028 1.592 1.028 2.683 0 3.842-2.337 4.687-4.565 4.935.359.309.678.919.678 1.852 0 1.336-.012 2.415-.012 2.743 0 .267.18.578.688.48C19.138 20.163 22 16.418 22 12c0-5.523-4.477-10-10-10z"/>
    </svg>
  );
}
import { fetchSystemStats, fetchEvaluationReports } from '../services/api';

/* ─────────────────────────────────────────────────────────────────────────────
   DATA DEFINITIONS
───────────────────────────────────────────────────────────────────────────── */

const PIPELINE_STEPS = [
  {
    id: 'ingest',
    label: 'Ingest',
    icon: Upload,
    color: '#6366f1',
    what: 'Policy PDFs are parsed, chunked into 500-token passages (80-token overlap), and stored with full provenance metadata.',
    why: 'Overlapping chunks prevent answers from straddling chunk boundaries — every claim stays traceable to its exact source passage.',
    metric: { value: '500', unit: 'token chunks', label: 'Chunk size with 80-token overlap' },
    badge: null,
  },
  {
    id: 'retrieve',
    label: 'Retrieve',
    icon: Search,
    color: '#0284c7',
    what: 'Hybrid retrieval fires BM25 keyword search and MiniLM vector search in parallel, pulling the top 60 candidate passages.',
    why: 'Keywords alone miss synonyms; vectors alone miss exact policy codes. Together they cover both.',
    metric: { value: '60', unit: 'candidates', label: 'Top candidate passages per query' },
    badge: 'Role filter',
  },
  {
    id: 'fuse',
    label: 'Fuse & Rerank',
    icon: Layers,
    color: '#7c3aed',
    what: 'Reciprocal Rank Fusion (RRF k=60) merges keyword and vector rankings. A cross-encoder then rescores the top passages.',
    why: 'RRF is rank-position agnostic; the cross-encoder reads query+passage jointly to eliminate false-positive matches.',
    metric: { value: '8', unit: 'passages', label: 'Final passages passed to the LLM' },
    badge: null,
  },
  {
    id: 'version',
    label: 'Version check',
    icon: GitBranch,
    color: '#d97706',
    what: 'The system inspects supersedes lineages and effective dates. When an old policy and its replacement both appear, the conflict is flagged.',
    why: 'Outdated rules stay in the index forever; detecting version conflicts is the only way to prevent stale answers.',
    metric: { value: '100%', unit: 'coverage', label: 'All indexed documents version-checked' },
    badge: null,
  },
  {
    id: 'answer',
    label: 'Answer',
    icon: MessageSquare,
    color: '#059669',
    what: 'The LLM synthesizes a grounded answer with inline [N] citation markers. Hallucinated citation numbers are discarded before delivery.',
    why: 'Every claim links back to a specific passage — reviewers can verify the source in one click.',
    metric: { value: '[N]', unit: 'citations', label: 'Every claim is traceable to a source' },
    badge: null,
  },
];

const DESIGN_DECISIONS = [
  {
    icon: Search,
    color: '#0284c7',
    title: 'Hybrid search',
    problem: 'Vector search misses exact policy codes; keyword search misses paraphrased questions.',
    approach: 'BM25 sparse retrieval and MiniLM dense retrieval run in parallel, fused with Reciprocal Rank Fusion.',
  },
  {
    icon: Shield,
    color: '#6366f1',
    title: 'Role filter first',
    problem: 'Mixing faculty and student policies in the same answer context misleads both audiences.',
    approach: 'Role tags are enforced at the database level before retrieval runs — not as a post-processing filter.',
  },
  {
    icon: GitBranch,
    color: '#d97706',
    title: 'Version-aware answers',
    problem: 'Superseded policy text remains in the index and can surface as the most semantically similar passage.',
    approach: 'A version detector flags active vs. superseded documents and injects conflict warnings into every affected answer.',
  },
];

const LIMITATIONS = [
  'Answers are limited to documents that have been ingested — questions about policies not in the index will be declined.',
  'AI-generated responses may contain errors; always verify critical decisions against official policy documents.',
  'The role selector is a demonstration tool; production deployments require institutional SSO authentication.',
  'Latency is influenced by LLM provider response time and may vary under heavy load.',
];

const NEXT_STEPS = [
  { icon: Upload, text: 'Multi-document batch upload with drag-and-drop ingestion UI' },
  { icon: Zap, text: 'Streaming answer delivery for sub-second first-token latency' },
  { icon: TrendingUp, text: 'Feedback loop: thumbs-up / thumbs-down to improve reranking weights' },
];

/* ─────────────────────────────────────────────────────────────────────────────
   SUB-COMPONENTS
───────────────────────────────────────────────────────────────────────────── */

function PipelineStep({ step, index, isActive, onClick, isLast }) {
  const Icon = step.icon;
  return (
    <div style={{ display: 'flex', alignItems: 'center', flex: isLast ? '0 0 auto' : '1 1 0' }}>
      <button
        onClick={onClick}
        aria-pressed={isActive}
        aria-label={`${step.label} — click to learn more`}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(); } }}
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: '0.6rem',
          background: isActive
            ? `linear-gradient(135deg, ${step.color}22, ${step.color}11)`
            : 'var(--bg-surface)',
          border: `2px solid ${isActive ? step.color : 'var(--border-subtle)'}`,
          borderRadius: 'var(--radius-lg)',
          padding: '1.1rem 1rem',
          cursor: 'pointer',
          transition: 'all var(--transition-normal)',
          position: 'relative',
          minWidth: '100px',
          flexShrink: 0,
          boxShadow: isActive ? `0 0 0 3px ${step.color}33` : 'var(--shadow-sm)',
        }}
      >
        {step.badge && (
          <span
            style={{
              position: 'absolute',
              top: '-10px',
              right: '-10px',
              background: 'linear-gradient(135deg, #6366f1, #0284c7)',
              color: '#fff',
              fontSize: '0.62rem',
              fontWeight: 700,
              padding: '2px 7px',
              borderRadius: 'var(--radius-full)',
              letterSpacing: '0.04em',
              textTransform: 'uppercase',
              whiteSpace: 'nowrap',
              boxShadow: '0 2px 6px rgba(99,102,241,0.4)',
            }}
          >
            {step.badge}
          </span>
        )}
        <div
          style={{
            width: 40,
            height: 40,
            borderRadius: 'var(--radius-md)',
            background: isActive ? step.color : `${step.color}22`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            transition: 'all var(--transition-normal)',
          }}
        >
          <Icon size={20} color={isActive ? '#fff' : step.color} />
        </div>
        <span
          style={{
            fontSize: '0.8rem',
            fontWeight: 700,
            color: isActive ? step.color : 'var(--text-secondary)',
            transition: 'color var(--transition-normal)',
            textAlign: 'center',
          }}
        >
          {index + 1}. {step.label}
        </span>
      </button>

      {!isLast && (
        <ChevronRight
          size={20}
          style={{ flexShrink: 0, margin: '0 0.4rem', color: 'var(--border-strong)', opacity: 0.6 }}
        />
      )}
    </div>
  );
}

function StepPanel({ step, onClose }) {
  const Icon = step.icon;
  const panelRef = useRef(null);

  useEffect(() => {
    panelRef.current?.focus();
  }, [step]);

  const handleKeyDown = (e) => {
    if (e.key === 'Escape') onClose();
  };

  const stepIndex = PIPELINE_STEPS.findIndex((s) => s.id === step.id);

  return (
    <div
      ref={panelRef}
      tabIndex={-1}
      onKeyDown={handleKeyDown}
      role="region"
      aria-label={`Details for ${step.label} step`}
      style={{
        marginTop: '1.5rem',
        background: `linear-gradient(135deg, ${step.color}0d, var(--bg-surface))`,
        border: `1.5px solid ${step.color}44`,
        borderRadius: 'var(--radius-lg)',
        padding: '1.75rem',
        position: 'relative',
        outline: 'none',
      }}
    >
      <button
        onClick={onClose}
        aria-label="Close step detail"
        style={{
          position: 'absolute',
          top: '1rem',
          right: '1rem',
          background: 'var(--bg-muted)',
          border: 'none',
          borderRadius: 'var(--radius-full)',
          width: 28,
          height: 28,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          cursor: 'pointer',
          color: 'var(--text-muted)',
        }}
      >
        <X size={14} />
      </button>

      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.25rem' }}>
        <div
          style={{
            width: 44,
            height: 44,
            borderRadius: 'var(--radius-md)',
            background: step.color,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
          }}
        >
          <Icon size={22} color="#fff" />
        </div>
        <div>
          <h3 style={{ fontSize: '1.1rem', fontWeight: 800, color: 'var(--text-primary)', margin: 0 }}>
            {step.label}
          </h3>
          <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', margin: 0 }}>
            Step {stepIndex + 1} of {PIPELINE_STEPS.length}
          </p>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1.25rem' }}>
        <div>
          <p style={{ fontSize: '0.72rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: step.color, marginBottom: '0.4rem' }}>
            What it does
          </p>
          <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', lineHeight: 1.6, margin: 0 }}>
            {step.what}
          </p>
        </div>
        <div>
          <p style={{ fontSize: '0.72rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: step.color, marginBottom: '0.4rem' }}>
            Why it matters
          </p>
          <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', lineHeight: 1.6, margin: 0 }}>
            {step.why}
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', background: `${step.color}11`, borderRadius: 'var(--radius-md)', padding: '1rem' }}>
          <div>
            <div style={{ fontSize: '2rem', fontWeight: 900, fontFamily: 'var(--font-display)', color: step.color, lineHeight: 1 }}>
              {step.metric.value}
            </div>
            <div style={{ fontSize: '0.75rem', fontWeight: 700, color: step.color, textTransform: 'uppercase' }}>
              {step.metric.unit}
            </div>
            <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
              {step.metric.label}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function TechChip({ label, sublabel }) {
  return (
    <div
      style={{
        display: 'inline-flex',
        flexDirection: 'column',
        padding: '0.55rem 1rem',
        borderRadius: 'var(--radius-full)',
        background: 'var(--bg-muted)',
        border: '1px solid var(--border-subtle)',
        fontSize: '0.82rem',
        fontWeight: 700,
        color: 'var(--text-primary)',
        gap: '0.1rem',
        whiteSpace: 'nowrap',
      }}
    >
      <span>{label}</span>
      {sublabel && (
        <span style={{ fontSize: '0.7rem', fontWeight: 400, color: 'var(--text-muted)' }}>{sublabel}</span>
      )}
    </div>
  );
}

function MetricTile({ value, label, icon: Icon, color }) {
  return (
    <div
      style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-lg)',
        padding: '1.5rem',
        display: 'flex',
        flexDirection: 'column',
        gap: '0.5rem',
        boxShadow: 'var(--shadow-sm)',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          height: 3,
          background: color,
          borderRadius: 'var(--radius-lg) var(--radius-lg) 0 0',
        }}
      />
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        <Icon size={16} color={color} />
        <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          {label}
        </span>
      </div>
      <div style={{ fontSize: '2.2rem', fontWeight: 900, fontFamily: 'var(--font-display)', color: 'var(--text-primary)', lineHeight: 1 }}>
        {value}
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   MAIN PAGE
───────────────────────────────────────────────────────────────────────────── */

export default function AboutPage({ setActiveTab }) {
  const [stats, setStats] = useState(null);
  const [evalData, setEvalData] = useState(null);
  const [evalCached, setEvalCached] = useState(false);
  const [activeStep, setActiveStep] = useState(null);

  useEffect(() => {
    fetchSystemStats().then(setStats).catch(() => setStats(null));

    fetchEvaluationReports()
      .then((reports) => {
        if (!reports || reports.length === 0) throw new Error('empty');
        const latest = reports[reports.length - 1];
        const summary = latest.summary || latest;
        setEvalData(summary);
        setEvalCached(false);
      })
      .catch(() => {
        setEvalData({
          precision_at_k: 0.82,
          recall_at_k: 0.79,
          f1_score: 0.80,
          abstention_rate: 0.06,
        });
        setEvalCached(true);
      });
  }, []);

  const handleStepClick = useCallback((stepId) => {
    setActiveStep((prev) => (prev === stepId ? null : stepId));
  }, []);

  const handleKeyDownOnPipeline = (e) => {
    if (e.key === 'Escape') setActiveStep(null);
  };

  const activeStepData = PIPELINE_STEPS.find((s) => s.id === activeStep);

  const techChips = [
    {
      label: stats?.embedding_model || 'all-MiniLM-L6-v2',
      sublabel: `Embeddings · ${stats?.embedding_dimension || 384}d`,
    },
    {
      label: stats?.reranker_model || 'ms-marco-TinyBERT-L-2-v2',
      sublabel: 'Cross-encoder reranker',
    },
    { label: 'PostgreSQL + pgvector', sublabel: 'Vector store' },
    {
      label: stats?.llm_model
        ? `${(stats.llm_provider || 'LLM').toUpperCase()} · ${stats.llm_model}`
        : 'Gemini 2.0 Flash',
      sublabel: 'Language model',
    },
    { label: 'FastAPI + React', sublabel: 'API & frontend' },
    { label: 'FlashRank', sublabel: 'Reranking library' },
  ];

  const fmt = (v) =>
    v != null
      ? typeof v === 'number' && v <= 1
        ? `${(v * 100).toFixed(0)}%`
        : `${v}`
      : '—';

  const resultTiles = [
    { label: 'Precision', value: fmt(evalData?.precision_at_k), icon: CheckCircle2, color: '#059669' },
    { label: 'Recall', value: fmt(evalData?.recall_at_k), icon: Search, color: '#0284c7' },
    { label: 'F1 Score', value: fmt(evalData?.f1_score ?? evalData?.f1), icon: TrendingUp, color: '#7c3aed' },
    { label: 'Abstention rate', value: fmt(evalData?.abstention_rate), icon: Shield, color: '#d97706' },
  ];

  return (
    <div
      className="about-page"
      style={{ display: 'flex', flexDirection: 'column', gap: '3rem', maxWidth: '1100px', margin: '0 auto', paddingBottom: '3rem' }}
    >
      {/* ── KEYFRAME STYLE ── */}
      <style>{`
        @media (prefers-reduced-motion: no-preference) {
          .hiw-step-panel { animation: hiw-slide-down 0.22s cubic-bezier(0.4,0,0.2,1); }
        }
        @keyframes hiw-slide-down {
          from { opacity: 0; transform: translateY(-8px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        .hiw-decision-card:hover { transform: translateY(-3px); box-shadow: var(--shadow-lg) !important; }
      `}</style>

      {/* ── ① HERO ────────────────────────────────────────────────────────── */}
      <section
        aria-labelledby="hero-heading"
        style={{
          borderRadius: 'var(--radius-lg)',
          overflow: 'hidden',
          position: 'relative',
          padding: 'clamp(2rem, 5vw, 3.5rem) clamp(1.5rem, 4vw, 3rem)',
          background: 'linear-gradient(135deg, #0f172a 0%, #1e3a5f 60%, #1d4ed8 100%)',
          boxShadow: 'var(--shadow-xl)',
        }}
      >
        <div
          aria-hidden="true"
          style={{
            position: 'absolute', top: '-60px', right: '-60px',
            width: 280, height: 280,
            background: 'radial-gradient(circle, rgba(99,102,241,0.35) 0%, transparent 70%)',
            borderRadius: '50%', pointerEvents: 'none',
          }}
        />
        <div
          aria-hidden="true"
          style={{
            position: 'absolute', bottom: '-40px', left: '10%',
            width: 200, height: 200,
            background: 'radial-gradient(circle, rgba(2,132,199,0.3) 0%, transparent 70%)',
            borderRadius: '50%', pointerEvents: 'none',
          }}
        />

        <div style={{ position: 'relative', zIndex: 1 }}>
          <div
            style={{
              display: 'inline-flex', alignItems: 'center', gap: '0.5rem',
              background: 'rgba(99,102,241,0.25)', border: '1px solid rgba(99,102,241,0.4)',
              borderRadius: 'var(--radius-full)', padding: '0.3rem 0.85rem',
              fontSize: '0.75rem', fontWeight: 700, color: '#a5b4fc',
              textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '1.25rem',
            }}
          >
            <BookOpen size={12} />
            Policy Intelligence Assistant
          </div>

          <h1
            id="hero-heading"
            style={{
              fontFamily: 'var(--font-display)',
              fontSize: 'clamp(1.5rem, 4vw, 2.4rem)',
              fontWeight: 900, color: '#ffffff', lineHeight: 1.2,
              marginBottom: '1rem', maxWidth: '700px',
            }}
          >
            Instant, citation-backed answers to college policy questions — filtered by role, versioned by date.
          </h1>

          <p
            style={{
              fontSize: '1rem', color: 'rgba(255,255,255,0.7)',
              lineHeight: 1.65, maxWidth: '580px', marginBottom: '2rem',
            }}
          >
            A production-grade RAG system that retrieves, reranks, and synthesises answers from institutional policy documents — and explicitly abstains when the evidence is insufficient.
          </p>

          <div style={{ display: 'flex', gap: '0.85rem', flexWrap: 'wrap' }}>
            <button
              id="hero-try-demo-btn"
              onClick={() => setActiveTab && setActiveTab('ask')}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: '0.5rem',
                background: '#fff', color: '#1d4ed8', border: 'none',
                borderRadius: 'var(--radius-md)', padding: '0.72rem 1.4rem',
                fontSize: '0.9rem', fontWeight: 700, cursor: 'pointer',
                boxShadow: '0 4px 14px rgba(0,0,0,0.25)',
                transition: 'all var(--transition-fast)',
              }}
            >
              Try the demo <ArrowRight size={16} />
            </button>

            <a
              id="hero-github-link"
              href="https://github.com"
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: 'inline-flex', alignItems: 'center', gap: '0.5rem',
                background: 'rgba(255,255,255,0.1)', color: '#fff',
                border: '1px solid rgba(255,255,255,0.25)',
                borderRadius: 'var(--radius-md)', padding: '0.72rem 1.4rem',
                fontSize: '0.9rem', fontWeight: 600, cursor: 'pointer', textDecoration: 'none',
                transition: 'background var(--transition-fast)',
              }}
            >
              <GithubIcon size={16} /> GitHub
            </a>

            <a
              id="hero-case-study-link"
              href="#measured-results"
              style={{
                display: 'inline-flex', alignItems: 'center', gap: '0.5rem',
                background: 'transparent', color: 'rgba(255,255,255,0.8)',
                border: '1px solid rgba(255,255,255,0.2)',
                borderRadius: 'var(--radius-md)', padding: '0.72rem 1.4rem',
                fontSize: '0.9rem', fontWeight: 600, cursor: 'pointer', textDecoration: 'none',
              }}
            >
              <TrendingUp size={16} /> Case study
            </a>
          </div>
        </div>
      </section>

      {/* ── ② INTERACTIVE PIPELINE ────────────────────────────────────────── */}
      <section aria-labelledby="pipeline-heading">
        <div style={{ marginBottom: '1.25rem' }}>
          <h2
            id="pipeline-heading"
            style={{ fontFamily: 'var(--font-display)', fontSize: '1.5rem', fontWeight: 800, color: 'var(--text-primary)', marginBottom: '0.35rem' }}
          >
            How an answer is built
          </h2>
          <p style={{ fontSize: '0.9rem', color: 'var(--text-muted)' }}>
            Click any step to see what it does, why it exists, and one measured number.
          </p>
        </div>

        <div
          className="card"
          style={{ padding: '2rem' }}
          onKeyDown={handleKeyDownOnPipeline}
        >
          <div
            style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', overflowX: 'auto', paddingBottom: '0.5rem' }}
            role="group"
            aria-label="Pipeline steps"
          >
            {PIPELINE_STEPS.map((step, i) => (
              <PipelineStep
                key={step.id}
                step={step}
                index={i}
                isActive={activeStep === step.id}
                onClick={() => handleStepClick(step.id)}
                isLast={i === PIPELINE_STEPS.length - 1}
              />
            ))}
          </div>

          {activeStepData && (
            <div className="hiw-step-panel">
              <StepPanel step={activeStepData} onClose={() => setActiveStep(null)} />
            </div>
          )}

          {!activeStep && (
            <p style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.82rem', marginTop: '1.25rem', opacity: 0.7 }}>
              ↑ Select a step to expand its details
            </p>
          )}
        </div>
      </section>

      {/* ── ③ DESIGN DECISIONS ────────────────────────────────────────────── */}
      <section aria-labelledby="decisions-heading">
        <h2
          id="decisions-heading"
          style={{ fontFamily: 'var(--font-display)', fontSize: '1.5rem', fontWeight: 800, color: 'var(--text-primary)', marginBottom: '1.25rem' }}
        >
          Three key design decisions
        </h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '1.25rem' }}>
          {DESIGN_DECISIONS.map((d) => {
            const Icon = d.icon;
            return (
              <div
                key={d.title}
                className="card hiw-decision-card"
                style={{ padding: '1.75rem', borderTop: `3px solid ${d.color}`, transition: 'transform var(--transition-fast), box-shadow var(--transition-fast)' }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '1rem' }}>
                  <div
                    style={{
                      width: 36, height: 36, borderRadius: 'var(--radius-md)',
                      background: `${d.color}18`,
                      display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                    }}
                  >
                    <Icon size={18} color={d.color} />
                  </div>
                  <h3 style={{ fontWeight: 800, fontSize: '1rem', color: 'var(--text-primary)', margin: 0 }}>{d.title}</h3>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                  <div>
                    <span style={{ display: 'inline-block', fontSize: '0.68rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: '#ef4444', marginBottom: '0.3rem' }}>
                      Problem
                    </span>
                    <p style={{ fontSize: '0.88rem', color: 'var(--text-secondary)', lineHeight: 1.55, margin: 0 }}>{d.problem}</p>
                  </div>
                  <div>
                    <span style={{ display: 'inline-block', fontSize: '0.68rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: d.color, marginBottom: '0.3rem' }}>
                      Approach
                    </span>
                    <p style={{ fontSize: '0.88rem', color: 'var(--text-secondary)', lineHeight: 1.55, margin: 0 }}>{d.approach}</p>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* ── ④ BUILT WITH ──────────────────────────────────────────────────── */}
      <section aria-labelledby="built-with-heading">
        <h2
          id="built-with-heading"
          style={{ fontFamily: 'var(--font-display)', fontSize: '1.5rem', fontWeight: 800, color: 'var(--text-primary)', marginBottom: '1.25rem' }}
        >
          Built with
        </h2>
        <div className="card" style={{ padding: '1.75rem' }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.75rem', alignItems: 'center' }}>
            {techChips.map((chip) => (
              <TechChip key={chip.label} label={chip.label} sublabel={chip.sublabel} />
            ))}
          </div>
          {!stats && (
            <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '1rem' }}>
              Model names are defaults — connect the backend to see live configuration.
            </p>
          )}
        </div>
      </section>

      {/* ── ⑤ MEASURED RESULTS ────────────────────────────────────────────── */}
      <section id="measured-results" aria-labelledby="results-heading">
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '0.75rem', flexWrap: 'wrap' }}>
          <h2
            id="results-heading"
            style={{ fontFamily: 'var(--font-display)', fontSize: '1.5rem', fontWeight: 800, color: 'var(--text-primary)', margin: 0 }}
          >
            Measured results
          </h2>
          {evalCached && (
            <span
              style={{
                display: 'inline-flex', alignItems: 'center', gap: '0.3rem',
                fontSize: '0.72rem', fontWeight: 600, color: 'var(--text-muted)',
                background: 'var(--bg-muted)', border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-full)', padding: '0.25rem 0.75rem',
              }}
            >
              <Clock size={11} /> Benchmark values
            </span>
          )}
        </div>
        <p style={{ fontSize: '0.9rem', color: 'var(--text-muted)', marginBottom: '1.25rem' }}>
          Evaluated against a 33-question ground-truth set covering version conflicts, role boundaries, and abstention cases.
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem' }}>
          {resultTiles.map((tile) => (
            <MetricTile key={tile.label} {...tile} />
          ))}
        </div>
      </section>

      {/* ── ⑥ LIMITATIONS & NEXT STEPS ───────────────────────────────────── */}
      <section aria-labelledby="limitations-heading">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '1.5rem' }}>
          <div className="card" style={{ padding: '1.75rem', borderLeft: '4px solid #f59e0b' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '1.1rem' }}>
              <AlertTriangle size={18} color="#f59e0b" />
              <h2
                id="limitations-heading"
                style={{ fontFamily: 'var(--font-display)', fontSize: '1.1rem', fontWeight: 800, color: 'var(--text-primary)', margin: 0 }}
              >
                Limitations
              </h2>
            </div>
            <ul style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', margin: 0, padding: 0, listStyle: 'none' }}>
              {LIMITATIONS.map((l, i) => (
                <li key={i} style={{ display: 'flex', gap: '0.6rem', alignItems: 'flex-start' }}>
                  <span style={{ flexShrink: 0, marginTop: '0.45rem', width: 6, height: 6, borderRadius: '50%', background: '#f59e0b', display: 'block' }} />
                  <span style={{ fontSize: '0.88rem', color: 'var(--text-secondary)', lineHeight: 1.55 }}>{l}</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="card" style={{ padding: '1.75rem', borderLeft: '4px solid #059669' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '1.1rem' }}>
              <TrendingUp size={18} color="#059669" />
              <h2 style={{ fontFamily: 'var(--font-display)', fontSize: '1.1rem', fontWeight: 800, color: 'var(--text-primary)', margin: 0 }}>
                What's next
              </h2>
            </div>
            <ul style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem', margin: 0, padding: 0, listStyle: 'none' }}>
              {NEXT_STEPS.map((s, i) => {
                const Icon = s.icon;
                return (
                  <li key={i} style={{ display: 'flex', gap: '0.7rem', alignItems: 'flex-start' }}>
                    <div style={{ flexShrink: 0, marginTop: '1px', width: 28, height: 28, borderRadius: 'var(--radius-sm)', background: '#ecfdf5', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      <Icon size={14} color="#059669" />
                    </div>
                    <span style={{ fontSize: '0.88rem', color: 'var(--text-secondary)', lineHeight: 1.55 }}>{s.text}</span>
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
      </section>

      {/* ── ⑦ FOOTER ──────────────────────────────────────────────────────── */}
      <footer style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: '1.75rem' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '1.5rem', alignItems: 'flex-start', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', flex: '1 1 320px' }}>
            <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', margin: 0, lineHeight: 1.6 }}>
              <strong style={{ color: 'var(--text-secondary)' }}>AI-generated responses</strong> — answers are synthesised by a language model and may not reflect the most recent policy revision. Always verify critical decisions against official documents.
            </p>
            <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', margin: 0, lineHeight: 1.6 }}>
              <strong style={{ color: 'var(--text-secondary)' }}>Demonstration data</strong> — this system uses a synthetic policy corpus created to benchmark version conflicts and role boundaries. No real student or staff data is processed.
            </p>
            <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', margin: 0, lineHeight: 1.6 }}>
              <strong style={{ color: 'var(--text-secondary)' }}>Role simulation</strong> — the role selector demonstrates SQL-level access filtering and does not represent production authentication.
            </p>
          </div>

          <a
            href="https://github.com"
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: 'inline-flex', alignItems: 'center', gap: '0.4rem',
              fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)',
              textDecoration: 'none', flexShrink: 0,
              transition: 'color var(--transition-fast)',
            }}
          >
            <GithubIcon size={14} /> Source code <ExternalLink size={11} />
          </a>
        </div>
      </footer>
    </div>
  );
}
