// Thin client for the UseCaseForge API. Every error surfaces as ApiError(message, status).

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
  } catch {
    throw new ApiError("Can't reach the server. Check your connection and try again.", 0);
  }
  let body = null;
  try {
    body = await response.json();
  } catch {
    /* non-JSON error page */
  }
  if (!response.ok) {
    const detail = body && (typeof body.detail === "string" ? body.detail : body.detail?.[0]?.msg);
    throw new ApiError(detail || `Request failed (${response.status}).`, response.status);
  }
  return body;
}

export const api = {
  status: () => request("/api/status"),
  createRun: (payload) => request("/api/runs", { method: "POST", body: JSON.stringify(payload) }),
  getRun: (id) => request(`/api/runs/${encodeURIComponent(id)}`),
};
