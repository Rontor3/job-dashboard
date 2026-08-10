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
export const fetchTracker = () => fetch("/api/tracker").then(json);
export const fetchDuplicates = () => fetch("/api/duplicates").then(json);
export const fetchStats = () => fetch("/api/stats").then(json);
export const startRefresh = () => fetch("/api/refresh", { method: "POST" }).then(json);
export const refreshStatus = () => fetch("/api/refresh/status").then(json);

export const fetchSegments = () =>
  fetch("/api/resume/segments").then(json).then((d) => d.segments || []);
export const suggestResume = (id) =>
  fetch(`/api/jobs/${id}/resume/suggest`, { method: "POST" }).then(json);
export const generateResume = (id, blockIds, acceptedRephrasings, layout) => {
  const body = {
    block_ids: blockIds || [],
    accepted_rephrasings: acceptedRephrasings || [],
  };
  if (layout) body.layout = layout;
  return fetch(`/api/jobs/${id}/resume/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(json);
};
export const regenerateBlock = (id, body) =>
  fetch(`/api/jobs/${id}/resume/regenerate-block`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(json);
export const generateBullets = (body) =>
  fetch(`/api/resume/bullets`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(json).then((d) => d.bullets || []);
export const fetchResumes = (id) => fetch(`/api/jobs/${id}/resumes`).then(json);

export const draftCoverLetter = (id) =>
  fetch(`/api/jobs/${id}/cover-letter/draft`, { method: "POST" }).then(json);
export const generateCoverLetter = (id, body) =>
  fetch(`/api/jobs/${id}/cover-letter/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body }),
  }).then(json);
export const fetchCoverLetters = (id) =>
  fetch(`/api/jobs/${id}/cover-letters`).then(json).then((d) => d.cover_letters || []);

export const gatherCompanyResources = (id) =>
  fetch(`/api/jobs/${id}/company-research`, { method: "POST" })
    .then(json)
    .then((d) => d.resources || []);
export const fetchCompanyResources = (id) =>
  fetch(`/api/jobs/${id}/company-resources`)
    .then(json)
    .then((d) => d.resources || []);
export const selectCompanyResources = (id, sourceUrls) =>
  fetch(`/api/jobs/${id}/company-resources/select`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_urls: sourceUrls }),
  })
    .then(json)
    .then((d) => d.resources || []);

export const fetchApplicationProfile = () =>
  fetch(`/api/application-profile`).then(json);
export const saveApplicationProfile = (fields) =>
  fetch(`/api/application-profile`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  }).then(json);
export const fetchApplicationPackage = (id) =>
  fetch(`/api/jobs/${id}/application-package`).then(json);
export const saveApplication = (id, body) =>
  fetch(`/api/jobs/${id}/application`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(json);
export const fetchApplication = (id) => fetch(`/api/jobs/${id}/application`).then(json);

export const hiringPosts = () =>
  fetch("/api/hiring/posts").then((r) => r.json());
export const refreshHiring = () =>
  fetch("/api/hiring/refresh", { method: "POST" }).then(async (r) => {
    if (!r.ok) throw new Error((await r.json()).detail || "refresh failed");
    return r.json();
  });
export const dismissHiring = (id) =>
  fetch(`/api/hiring/posts/${id}/dismiss`, { method: "POST" }).then((r) => r.json());

export const savedBlocks = () =>
  fetch("/api/resume/blocks").then((r) => r.json());
export const saveBlock = (body) =>
  fetch("/api/resume/blocks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => r.json());
export const deleteSavedBlock = (id) =>
  fetch(`/api/resume/blocks/${id}`, { method: "DELETE" }).then((r) => r.json());
