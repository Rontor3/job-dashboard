async function json(resp) {
  if (resp.status === 409) return { alreadyRunning: true };
  if (!resp.ok) throw new Error(`${resp.status} ${await resp.text()}`);
  return resp.json();
}

export function fetchJobs(params = {}) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== null && v !== undefined && v !== "")
  );
  return fetch(`/api/jobs?${qs}`).then(json);
}
export const fetchJob = (id) => fetch(`/api/jobs/${id}`).then(json);
export const patchStatus = (id, status) =>
  fetch(`/api/jobs/${id}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  }).then(json);
export const fetchDuplicates = () => fetch("/api/duplicates").then(json);
export const fetchStats = () => fetch("/api/stats").then(json);
export const startRefresh = () => fetch("/api/refresh", { method: "POST" }).then(json);
export const refreshStatus = () => fetch("/api/refresh/status").then(json);

export const fetchSegments = () => fetch("/api/resume/segments").then(json);
export const suggestResume = (id) =>
  fetch(`/api/jobs/${id}/resume/suggest`, { method: "POST" }).then(json);
export const generateResume = (id, blockIds, acceptedRephrasings) =>
  fetch(`/api/jobs/${id}/resume/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ block_ids: blockIds, accepted_rephrasings: acceptedRephrasings }),
  }).then(json);
export const fetchResumes = (id) => fetch(`/api/jobs/${id}/resumes`).then(json);
