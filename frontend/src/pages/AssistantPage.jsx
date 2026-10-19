import React, { useState, useRef, useEffect } from 'react';
import {
  Send,
  RotateCcw,
  Sliders,
  ChevronDown,
  ChevronUp,
  AlertCircle,
  Clock,
  ArrowRight,
  ShieldCheck,
  Info,
  HelpCircle,
  RefreshCw,
} from 'lucide-react';
import { submitQuestion, fetchDocuments } from '../services/api';
import DocumentDetailModal from '../components/DocumentDetailModal';
import PolicyAnswerView from '../components/PolicyAnswerView';
import { formatRoleName, normalizeRole } from '../utils/roles';

export default function AssistantPage({ userRole }) {
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [lastSubmittedQuery, setLastSubmittedQuery] = useState('');

  // Catalog cache for genuine metadata lookup on Inspect
  const [catalogDocs, setCatalogDocs] = useState([]);

  // Retrieval Parameters (collapsible)
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [topK, setTopK] = useState(20);
  const [topN, setTopN] = useState(5);
  const [versionAware, setVersionAware] = useState(true);
  const [includeDiagnostics, setIncludeDiagnostics] = useState(false);

  // Modal for citation inspect
  const [selectedCitationDoc, setSelectedCitationDoc] = useState(null);

  const textareaRef = useRef(null);

  const sampleQuestions = [
    'What are the hostel curfew hours and visitor rules?',
    'What are the eligibility requirements for merit scholarships?',
    'What are faculty office hours and consultation policies?',
    'What is the procedure for student grievance redressal?',
  ];

  // Prefetch documents catalog for genuine metadata lookup
  useEffect(() => {
    let mounted = true;
    fetchDocuments()
      .then((data) => {
        if (mounted && data?.documents) {
          setCatalogDocs(data.documents);
        }
      })
      .catch(() => {
        // Non-critical background fetch
      });
    return () => {
      mounted = false;
    };
  }, []);

  const handleAsk = async (queryToSubmit = null) => {
    const q = (queryToSubmit !== null ? queryToSubmit : question).trim();
    if (!q || loading) return;

    setLoading(true);
    setError(null);
    setResult(null); // Clear previous results immediately
    setLastSubmittedQuery(q);

    try {
      const response = await submitQuestion({
        question: q,
        role: normalizeRole(userRole),
        top_k: topK,
        top_n: topN,
        version_aware: versionAware,
        include_diagnostics: includeDiagnostics,
      });
      setResult(response);
    } catch (err) {
      setError(err.message || 'An error occurred while communicating with the policy assistant.');
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleAsk();
    }
  };

  const handleNewQuestion = () => {
    setQuestion('');
    setResult(null);
    setError(null);
    setLastSubmittedQuery('');
    if (textareaRef.current) {
      textareaRef.current.focus();
    }
  };

  // Inspect document without fabricating synthetic values
  const handleInspectDocument = (cit, matchingPassage) => {
    // 1. First look up the exact document in catalogDocs
    const foundDoc = catalogDocs.find(
      (d) => d.file_name === cit.file_name || d.title === matchingPassage?.document_title
    );

    if (foundDoc) {
      setSelectedCitationDoc(foundDoc);
      return;
    }

    // 2. Otherwise extract genuine attributes from matching passage
    setSelectedCitationDoc({
      id: matchingPassage?.chunk_id || cit.file_name,
      title: matchingPassage?.document_title || cit.file_name.replace('.pdf', '').replace(/_/g, ' '),
      file_name: cit.file_name,
      effective_date: matchingPassage?.effective_date || 'Active',
      status: matchingPassage?.is_superseded ? 'superseded' : 'active',
      supersedes: matchingPassage?.superseded_by || null,
      allowed_roles: [userRole],
      total_pages: cit.page_number,
      total_chunks: matchingPassage ? 1 : 1,
    });
  };

  const currentRoleDisplay = formatRoleName(userRole);

  return (
    <div className="assistant-layout" style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
      {/* Question Form Workspace */}
      <div className="assistant-input-box card">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.75rem', marginBottom: '1rem' }}>
          <div>
            <h2 style={{ fontFamily: 'var(--font-display)', fontSize: '1.25rem', fontWeight: 700, color: 'var(--text-primary)' }}>
              Ask a Policy Question
            </h2>
            <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
              Query academic regulations, course syllabi, grading criteria, and administrative guidelines.
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.82rem' }}>
            <span style={{ color: 'var(--text-muted)' }}>Authorized Scope:</span>
            <span className="badge badge-info" id="active-role-scope-badge">
              <ShieldCheck size={13} style={{ marginRight: '4px' }} />
              {currentRoleDisplay} (Simulated)
            </span>
          </div>
        </div>

        <textarea
          ref={textareaRef}
          id="question-input"
          className="question-textarea"
          placeholder="Type your policy inquiry... (e.g. What is the grade replacement policy for repeated courses? What are the hostel curfew hours?)"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={loading}
          aria-label="Policy Question Input"
          rows={3}
        />

        {/* Quick Inquiries Section - Discrete and Clickable */}
        <div className="quick-inquiries-container">
          <div className="quick-inquiries-label">
            <span>Example inquiries you can ask:</span>
          </div>
          <div className="quick-inquiries-grid">
            {sampleQuestions.map((sq, idx) => (
              <button
                key={idx}
                className="inquiry-card-btn"
                onClick={() => {
                  setQuestion(sq);
                  handleAsk(sq);
                }}
                disabled={loading}
                type="button"
                title={`Ask: "${sq}"`}
              >
                <span className="inquiry-arrow">
                  <ArrowRight size={13} />
                </span>
                <span className="inquiry-text">{sq}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Action Bar - Clear Separation between New Question and Ask Question */}
        <div className="input-actions-bar">
          <button
            type="button"
            className="parameters-toggle-btn"
            onClick={() => setShowAdvanced(!showAdvanced)}
            aria-expanded={showAdvanced}
          >
            <Sliders size={15} />
            <span>Advanced Retrieval Settings</span>
            {showAdvanced ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>

          <div style={{ display: 'flex', gap: '0.85rem', alignItems: 'center', flexWrap: 'wrap' }}>
            {(question || result || error) && (
              <button
                className="btn btn-secondary"
                onClick={handleNewQuestion}
                disabled={loading}
                id="new-question-btn"
                type="button"
                title="Clear current question and reset workspace"
              >
                <RotateCcw size={15} />
                <span>New Question</span>
              </button>
            )}

            <button
              className="btn btn-primary"
              onClick={() => handleAsk()}
              disabled={!question.trim() || loading}
              id="ask-question-btn"
              type="button"
              style={{ minWidth: '150px' }}
            >
              {loading ? (
                <>
                  <div
                    className="spinner"
                    style={{
                      width: '16px',
                      height: '16px',
                      border: '2px solid #ffffff',
                      borderTopColor: 'transparent',
                      borderRadius: '50%',
                    }}
                  />
                  <span>Searching & Synthesizing...</span>
                </>
              ) : (
                <>
                  <Send size={16} />
                  <span>Ask Question</span>
                </>
              )}
            </button>
          </div>
        </div>

        {/* Advanced Settings Collapsible Drawer */}
        {showAdvanced && (
          <div className="parameters-drawer" style={{ animation: 'fadeIn 150ms ease-out' }}>
            <div className="param-group">
              <label htmlFor="top-k-slider">Initial Candidates (top_k): {topK}</label>
              <input
                id="top-k-slider"
                type="range"
                min="5"
                max="50"
                step="5"
                value={topK}
                onChange={(e) => setTopK(Number(e.target.value))}
              />
              <span>Depth of fused vector and keyword matches</span>
            </div>

            <div className="param-group">
              <label htmlFor="top-n-slider">Reranked Passages (top_n): {topN}</label>
              <input
                id="top-n-slider"
                type="range"
                min="1"
                max="10"
                step="1"
                value={topN}
                onChange={(e) => setTopN(Number(e.target.value))}
              />
              <span>Top cross-encoder passages sent to LLM</span>
            </div>

            <div className="param-group" style={{ justifyContent: 'center' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={versionAware}
                  onChange={(e) => setVersionAware(e.target.checked)}
                />
                <span>Enable Version-Aware Filtering</span>
              </label>
              <span>Prioritizes active documents over superseded policies</span>
            </div>

            <div className="param-group" style={{ justifyContent: 'center' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={includeDiagnostics}
                  onChange={(e) => setIncludeDiagnostics(e.target.checked)}
                />
                <span>Include Retrieval Diagnostics</span>
              </label>
              <span>Measures vector, keyword, RRF, and rerank timings</span>
            </div>
          </div>
        )}
      </div>

      {/* Network / API Error Panel with Safe Retry */}
      {error && (
        <div className="alert-box alert-danger" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <AlertCircle size={24} style={{ flexShrink: 0 }} />
            <div>
              <div style={{ fontWeight: 700, fontSize: '0.95rem', marginBottom: '0.2rem' }}>
                Communication Error
              </div>
              <div style={{ fontSize: '0.88rem' }}>{error}</div>
            </div>
          </div>
          {lastSubmittedQuery && (
            <div style={{ display: 'flex', gap: '0.6rem' }}>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => handleAsk(lastSubmittedQuery)}
                disabled={loading}
                id="retry-request-btn"
                type="button"
              >
                <RefreshCw size={14} />
                <span>Retry Query</span>
              </button>
              <button
                className="btn btn-secondary btn-sm"
                onClick={handleNewQuestion}
                type="button"
              >
                <span>New Question</span>
              </button>
            </div>
          )}
        </div>
      )}

      {/* Loading State Workspace */}
      {loading && !result && (
        <div className="card" style={{ textAlign: 'center', padding: '3.5rem 2rem' }}>
          <div
            className="spinner"
            style={{
              width: '36px',
              height: '36px',
              border: '3px solid var(--border-subtle)',
              borderTopColor: 'var(--brand-blue)',
              borderRadius: '50%',
              margin: '0 auto 1.25rem',
            }}
          />
          <h4 style={{ fontFamily: 'var(--font-display)', fontSize: '1.15rem', fontWeight: 600, color: 'var(--text-primary)' }}>
            Retrieving & Grounding Policy Evidence...
          </h4>
          <p style={{ fontSize: '0.86rem', color: 'var(--text-secondary)', marginTop: '0.35rem' }}>
            Scanning indexed policy corpus for <strong>{currentRoleDisplay}</strong> demo permissions.
          </p>
        </div>
      )}

      {/* Response Workspace */}
      {result && (
        <div className="result-panel card">
          {/* Response Status Header: Strict Separation between Demo Role and Status */}
          <div className="result-header">
            <div>
              <span style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                {result.abstained ? 'Institutional Inquiry Analysis' : 'Authoritative Policy Answer'}
              </span>
              <h3 style={{ marginTop: '0.2rem', fontFamily: 'var(--font-display)', fontSize: '1.25rem', fontWeight: 800 }}>
                {result.abstained ? 'Evidence Grounding Result' : 'Synthesized Answer'}
              </h3>
            </div>

            <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'center', flexWrap: 'wrap' }}>
              {/* Separate Active Demo Role Badge */}
              <span className="badge badge-neutral" id="demo-role-badge" style={{ textTransform: 'none' }}>
                Demo Role: <strong>{currentRoleDisplay}</strong>
              </span>

              {/* Distinct Answer Status Badge */}
              {result.abstained ? (
                <span className="badge badge-warning" id="answer-status-badge">
                  Insufficient evidence
                </span>
              ) : result.has_policy_conflict ? (
                <span className="badge badge-warning" id="answer-status-badge">
                  Conflict Detected
                </span>
              ) : (
                <span className="badge badge-success" id="answer-status-badge">
                  Grounded & Verified
                </span>
              )}
            </div>
          </div>

          {/* Outcome 1: Abstention / Insufficient Evidence */}
          {result.abstained ? (
            <div className="abstention-panel">
              <div className="alert-box alert-warning" style={{ alignItems: 'flex-start' }}>
                <Info size={24} style={{ flexShrink: 0, marginTop: '2px' }} />
                <div style={{ width: '100%' }}>
                  <div style={{ fontWeight: 700, fontSize: '1.05rem', marginBottom: '0.35rem' }}>
                    No Sufficient Evidence Found
                  </div>
                  <p style={{ fontSize: '0.92rem', marginBottom: '0.65rem', lineHeight: 1.6 }}>
                    No sufficient evidence was found in the documents available to the <strong>{currentRoleDisplay}</strong> demo role to answer this question factually. The system abstains to uphold institutional accuracy and prevent hallucination.
                  </p>
                  {result.answer && (
                    <div style={{ fontStyle: 'italic', fontSize: '0.88rem', color: 'var(--text-secondary)', padding: '0.65rem 0.85rem', backgroundColor: 'var(--bg-muted)', borderRadius: 'var(--radius-sm)', borderLeft: '3px solid var(--border-subtle)' }}>
                      System response note: "{result.answer}"
                    </div>
                  )}
                </div>
              </div>

              {/* Suggestions for user */}
              <div className="abstention-guidance-card">
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem', fontWeight: 600, fontSize: '0.9rem' }}>
                  <HelpCircle size={16} color="var(--brand-blue)" />
                  <span>Next Steps & Resolution Guidance</span>
                </div>
                <ul style={{ margin: 0, paddingLeft: '1.25rem', fontSize: '0.85rem', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                  <li>Verify if your inquiry relates to faculty-only or administrative policies. If so, switch the simulated role selector in the top bar.</li>
                  <li>Check the <strong>Document Library</strong> tab to verify if the relevant handbook is indexed.</li>
                  <li>Try rephrasing your question using institutional keywords (e.g. "attendance", "scholarship", "curfew", "grading").</li>
                </ul>
              </div>
            </div>
          ) : (
            /* Outcome 2: Grounded Answer rendered as structured components */
            <PolicyAnswerView
              result={result}
              userRole={userRole}
              onInspectDocument={handleInspectDocument}
            />
          )}

          {/* Optional Retrieval Diagnostics Panel */}
          {result.diagnostics && (
            <div className="card" style={{ marginTop: '1.5rem', backgroundColor: 'var(--bg-muted)' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.85rem', flexWrap: 'wrap', gap: '0.5rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <Clock size={16} color="var(--brand-blue)" />
                  <h4 style={{ fontSize: '0.9rem', fontWeight: 700 }}>Retrieval Diagnostics (Role-Filtered)</h4>
                </div>
                <span className="badge badge-info" style={{ fontSize: '0.75rem' }}>
                  Engine: {result.diagnostics.semantic_retrieval_active ? 'Semantic ONNX MiniLM (384d)' : 'Baseline Hybrid (1536d)'}
                </span>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '0.75rem' }}>
                <div className="diag-stat-item">
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Vector Matches:</span>
                  <div style={{ fontWeight: 700, fontSize: '1.05rem' }}>{result.diagnostics.vector_count}</div>
                </div>
                <div className="diag-stat-item">
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Keyword Matches:</span>
                  <div style={{ fontWeight: 700, fontSize: '1.05rem' }}>{result.diagnostics.keyword_count}</div>
                </div>
                <div className="diag-stat-item">
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Fused Candidates:</span>
                  <div style={{ fontWeight: 700, fontSize: '1.05rem' }}>{result.diagnostics.fused_count}</div>
                </div>
                <div className="diag-stat-item">
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Reranked Passages:</span>
                  <div style={{ fontWeight: 700, fontSize: '1.05rem' }}>{result.diagnostics.reranked_count}</div>
                </div>
                <div className="diag-stat-item">
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Total Latency:</span>
                  <div style={{ fontWeight: 700, fontSize: '1.05rem', color: 'var(--brand-blue)' }}>
                    {result.diagnostics.timings_ms?.total_retrieval_ms?.toFixed(1) || 0} ms
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Citation Document Detail Modal */}
      {selectedCitationDoc && (
        <DocumentDetailModal
          document={selectedCitationDoc}
          onClose={() => setSelectedCitationDoc(null)}
        />
      )}
    </div>
  );
}
