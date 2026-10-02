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
export const suggestSkills = (body) =>
  fetch(`/api/resume/suggest-skills`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(json).then((d) => d.skills || []);
export const highlightBullets = (bullets) =>
  fetch(`/api/resume/highlight`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ bullets }),
  }).then(json).then((d) => d.bullets || []);
// Persisted résumé layouts: working copy + named versions.
export const fetchLayouts = () => fetch(`/api/resume/layouts`).then(json);
export const saveWorkingLayout = (blocks) =>
  fetch(`/api/resume/layout`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ blocks }),
  }).then(json);
export const saveVersion = (name, blocks) =>
  fetch(`/api/resume/layouts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, blocks }),
  }).then(json);
export const loadVersion = (name) =>
  fetch(`/api/resume/layouts/${encodeURIComponent(name)}`).then(json).then((d) => d.blocks || []);
export const deleteVersion = (name) =>
  fetch(`/api/resume/layouts/${encodeURIComponent(name)}`, { method: "DELETE" }).then(json);
// A saved version (or the working draft, name "__working__") rendered as an
// inline PDF — job-agnostic, no JD needed.
export const layoutPdfUrl = (name) => `/api/resume/layouts/${encodeURIComponent(name)}/pdf`;
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
const postOrThrow = (url) =>
  fetch(url, { method: "POST" }).then(async (r) => {
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || "request failed");
    return d;
  });
export const promoteHiring = (id) => postOrThrow(`/api/hiring/posts/${id}/promote`);
export const draftHiringEmail = (id) => postOrThrow(`/api/hiring/posts/${id}/email-draft`);

export const launchApplyAgent = (id) =>
  fetch(`/api/jobs/${id}/apply-agent`, { method: "POST" }).then(json);
export const fetchApplyAgentStatus = () => fetch("/api/apply-agent/status").then(json);
export const fetchAgentLog = (id, lines = 80) =>
  fetch(`/api/jobs/${id}/agent-runs/log?lines=${lines}`).then((r) => (r.status === 404 ? null : json(r)));
export const fetchAgentRunHistory = (id) =>
  fetch(`/api/jobs/${id}/agent-runs/latest`).then((r) => (r.status === 404 ? null : json(r)));

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

const jsonBody = (method, body) => ({
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});
export const fetchAnswers = (q = "") =>
  fetch(`/api/answers?q=${encodeURIComponent(q)}`).then(json);          // {answers, unanswered}
export const saveAnswer = (body) => fetch("/api/answers", jsonBody("PUT", body)).then(json);
export const deleteAnswer = (entryId) =>
  fetch(`/api/answers?entry_id=${encodeURIComponent(entryId)}`, { method: "DELETE" }).then(json);
export const fetchQbankEntries = (search = "") =>
  fetch(`/api/qbank/entries?search=${encodeURIComponent(search)}`).then(json).then((d) => d.entries || []);
export const fetchAnswerApps = (qkey) =>
  fetch(`/api/answers/applications?qkey=${encodeURIComponent(qkey)}`).then(json).then((d) => d.applications || []);
export const fetchJobQuestions = (id) =>
  fetch(`/api/jobs/${id}/questions`).then(json).then((d) => d.questions || []);
export const fetchOpenCounts = () => fetch("/api/questions/open-counts").then(json);
export const replyQuestion = (jobId, rowId, answer, save_as = "once", entry_id = null) =>
  fetch(`/api/jobs/${jobId}/questions/${rowId}/reply`, jsonBody("POST", { answer, save_as, entry_id })).then(json);
export const fetchAgentSettings = () => fetch("/api/agent-settings").then(json);
export const saveAgentSettings = (body) =>
  fetch("/api/agent-settings", jsonBody("PUT", typeof body === "number" ? { answer_confidence_min: body } : body)).then(json);
export const fetchIngredients = () => fetch("/api/ingredients").then(json);

export const fetchRetrievalStats = () => fetch("/api/retrieval/stats").then(json);
export const fetchRetrievalRecent = (limit = 30) =>
  fetch(`/api/retrieval/recent?limit=${limit}`).then(json).then((d) => d.recent || []);
export const fetchAnswersUsed = (id) =>
  fetch(`/api/jobs/${id}/answers-used`).then(json).then((d) => d.answers || []);
export const reviewAnswer = (rowId, verdict, entry_id = null) =>
  fetch(`/api/application-qa/${rowId}/review`, jsonBody("POST", { verdict, entry_id })).then(json);
