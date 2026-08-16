// Service worker: the only place allowed to fetch the local dashboard
// cross-origin (content scripts can't in MV3). Content script asks; we fetch.
const PROFILE_URL = "http://localhost:8000/api/application-profile";

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || msg.type !== "RUFLO_GET_PROFILE") return;
  fetch(PROFILE_URL, { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
    .then((profile) => sendResponse({ ok: true, profile }))
    .catch((err) => sendResponse({ ok: false, error: String(err && err.message || err) }));
  return true; // keep the message channel open for the async response
});
