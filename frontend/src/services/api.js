/**
 * API Service Layer for Document RAG Frontend.
 * Communicates with FastAPI backend with structured error handling and timeout safeguards.
 */

const RAW_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';
// In development, if no explicit base URL is configured, use /api proxy or direct localhost
export const API_BASE_URL = RAW_BASE_URL.replace(/\/+$/, '');

class APIError extends Error {
  constructor(message, status = null, details = null) {
    super(message);
    this.name = 'APIError';
    this.status = status;
    this.details = details;
  }
}

export class ConnectionError extends APIError {
  constructor(message = 'Unable to connect to the Document RAG backend service.') {
    super(message, 0);
    this.name = 'ConnectionError';
  }
}

export class ValidationError extends APIError {
  constructor(message = 'Request validation failed.') {
    super(message, 422);
    this.name = 'ValidationError';
  }
}

export class RateLimitError extends APIError {
  constructor(message = 'Provider rate limit exceeded. Please retry shortly.') {
    super(message, 429);
    this.name = 'RateLimitError';
  }
}

export class ServiceUnavailableError extends APIError {
  constructor(message = 'LLM or database service is temporarily unavailable.') {
    super(message, 503);
    this.name = 'ServiceUnavailableError';
  }
}

export class GatewayTimeoutError extends APIError {
  constructor(message = 'Backend timed out while synthesizing the answer.') {
    super(message, 504);
    this.name = 'GatewayTimeoutError';
  }
}

async function request(endpoint, options = {}, timeoutMs = 45000) {
  const url = `${API_BASE_URL}${endpoint}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
      headers: {
        ...(options.headers || {}),
      },
    });

    clearTimeout(timer);

    if (response.ok) {
      return await response.json();
    }

    // Parse backend JSON error if available
    let errorDetail = '';
    try {
      const errJson = await response.json();
      errorDetail = errJson.detail || JSON.stringify(errJson);
    } catch {
      errorDetail = response.statusText;
    }

    switch (response.status) {
      case 422:
        throw new ValidationError(`Validation Error: ${errorDetail}`);
      case 429:
        throw new RateLimitError(`Rate Limit: ${errorDetail}`);
      case 503:
        throw new ServiceUnavailableError(`Service Unavailable: ${errorDetail}`);
      case 504:
        throw new GatewayTimeoutError(`Gateway Timeout: ${errorDetail}`);
      default:
        throw new APIError(`HTTP Error ${response.status}: ${errorDetail}`, response.status, errorDetail);
    }
  } catch (err) {
    clearTimeout(timer);
    if (err instanceof APIError) {
      throw err;
    }
    if (err.name === 'AbortError') {
      throw new GatewayTimeoutError(`Request timed out after ${timeoutMs / 1000} seconds.`);
    }
    throw new ConnectionError(
      `Network connection failed. Verify that the FastAPI backend is running at ${API_BASE_URL || 'http://127.0.0.1:8000'}.`
    );
  }
}

export async function checkBackendHealth() {
  return await request('/health', { method: 'GET' }, 5000);
}

export async function fetchSystemStats() {
  return await request('/system/stats', { method: 'GET' }, 10000);
}

export async function fetchDocuments(role = null) {
  const query = role ? `?role=${encodeURIComponent(role)}` : '';
  return await request(`/documents${query}`, { method: 'GET' }, 15000);
}

export async function inspectPdfDocument(file) {
  const formData = new FormData();
  formData.append('file', file);

  const url = `${API_BASE_URL}/documents/inspect`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20000);

  try {
    const response = await fetch(url, {
      method: 'POST',
      body: formData,
      signal: controller.signal,
    });
    clearTimeout(timer);

    if (!response.ok) {
      const errJson = await response.json().catch(() => ({}));
      throw new APIError(errJson.detail || 'Failed to inspect PDF', response.status);
    }
    return await response.json();
  } catch (err) {
    clearTimeout(timer);
    if (err instanceof APIError) throw err;
    throw new ConnectionError(`Failed to upload PDF for inspection: ${err.message}`);
  }
}

export async function fetchEvaluationReports() {
  return await request('/evaluations/reports', { method: 'GET' }, 10000);
}

export async function fetchEvaluationReportDetail(filename) {
  return await request(`/evaluations/reports/${encodeURIComponent(filename)}`, { method: 'GET' }, 15000);
}

export async function submitQuestion({
  question,
  role = 'student',
  top_k = 20,
  top_n = 5,
  version_aware = true,
  include_diagnostics = false,
  semantic_retrieval = null,
}) {
  const payload = {
    question,
    role,
    top_k,
    top_n,
    version_aware,
    include_diagnostics,
  };
  if (semantic_retrieval !== null) {
    payload.semantic_retrieval = semantic_retrieval;
  }

  return await request('/ask', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  }, 60000);
}
