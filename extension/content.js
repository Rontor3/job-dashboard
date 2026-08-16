// Ruflo Auto-fill content script.
// Injects a floating button; on click, fills the CURRENT page's form fields
// from the local dashboard profile. It NEVER submits, and never touches file
// inputs, passwords, checkboxes, or radios (consent stays yours).
(function () {
  if (window.__rufloInjected) return;
  window.__rufloInjected = true;

  // --- field label -> profile key rules (order matters: specific first) ---
  const RULES = [
    { re: /e-?mail/, key: "email" },
    { re: /(phone|mobile|contact\s*(no|number)|whats\s?app|\btel\b)/, key: "phone" },
    { re: /linked-?in/, key: "linkedin_url" },
    { re: /git-?hub/, key: "github_url" },
    { re: /(portfolio|personal\s*website|website|blog\s*url)/, key: "portfolio_url" },
    { re: /(first\s*name|given\s*name|\bfname\b)/, key: "__first" },
    { re: /(last\s*name|surname|family\s*name|\blname\b)/, key: "__last" },
    { re: /(full\s*name|your\s*name|candidate\s*name|applicant\s*name|^\s*name\s*$|\bname\b)/, key: "full_name" },
    { re: /notice\s*period/, key: "notice_period" },
    { re: /(current\s*(ctc|salary|compensation)|present\s*salary)/, key: "current_ctc" },
    { re: /(expected\s*(ctc|salary|compensation)|salary\s*expectation|desired\s*salary)/, key: "salary_expectation" },
    { re: /(total\s*experience|years?\s*of\s*experience|work\s*experience|relevant\s*experience|^\s*experience\s*$|experience.*years)/, key: "years_experience" },
    { re: /(current\s*(location|city)|^\s*location\s*$|^\s*city\s*$|based\s*(in|at))/, key: "location" },
    { re: /(willing\s*to\s*relocat|open\s*to\s*relocat|relocat)/, key: "willing_to_relocate" },
    { re: /(work\s*authoriz|authoriz(ed|ation)\s*to\s*work|right\s*to\s*work|visa|sponsorship)/, key: "work_authorization" },
    { re: /(reason\s*for\s*(change|leaving|job\s*change)|why.*(looking|change|move))/, key: "reason_for_change" },
  ];

  // Guard: things that look like "name" but aren't the candidate's name.
  const NAME_EXCLUDE = /(company|employer|college|university|institut|school|organi[sz]|father|mother|parent|guardian|spouse|user\s*name|login|file|account\s*holder|bank|referr|reference|project|team|manager|recruiter|emergency)/;

  const SKIP_INPUT_TYPES = new Set([
    "password", "file", "hidden", "submit", "button", "image", "reset",
    "checkbox", "radio", "range", "color", "date", "datetime-local",
    "month", "week", "time",
  ]);

  function labelText(el) {
    const parts = [];
    if (el.id) {
      const l = document.querySelector('label[for="' + (window.CSS && CSS.escape ? CSS.escape(el.id) : el.id) + '"]');
      if (l) parts.push(l.textContent);
    }
    const wrap = el.closest("label");
    if (wrap) parts.push(wrap.textContent);
    const al = el.getAttribute("aria-label");
    if (al) parts.push(al);
    const lb = el.getAttribute("aria-labelledby");
    if (lb) lb.split(/\s+/).forEach((id) => { const n = document.getElementById(id); if (n) parts.push(n.textContent); });
    if (el.placeholder) parts.push(el.placeholder);
    if (el.name) parts.push(el.name);
    if (el.id) parts.push(el.id);
    return parts.join(" ").toLowerCase().replace(/\s+/g, " ").trim();
  }

  function valueFor(key, p) {
    if (key === "__first") return String(p.full_name || "").trim().split(/\s+/)[0] || "";
    if (key === "__last") { const t = String(p.full_name || "").trim().split(/\s+/); return t.slice(1).join(" "); }
    const v = p[key];
    if (v === null || v === undefined) return "";
    if (typeof v === "boolean") return v ? "Yes" : "No";
    return String(v);
  }

  function isVisible(el) {
    const s = getComputedStyle(el);
    if (s.display === "none" || s.visibility === "hidden" || s.opacity === "0") return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }

  function setNativeValue(el, value) {
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype
      : el instanceof HTMLSelectElement ? HTMLSelectElement.prototype
        : HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, "value");
    if (desc && desc.set) desc.set.call(el, value); else el.value = value;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function fillSelect(el, want) {
    const target = want.toLowerCase();
    for (const opt of el.options) {
      const t = (opt.textContent || "").toLowerCase().trim();
      const v = (opt.value || "").toLowerCase().trim();
      if (t === target || v === target || (target.length > 1 && (t.includes(target) || target.includes(t) && t))) {
        setNativeValue(el, opt.value);
        return true;
      }
    }
    return false;
  }

  function matchKey(label) {
    for (const rule of RULES) {
      if (rule.re.test(label)) {
        if ((rule.key === "full_name" || rule.key === "__first" || rule.key === "__last") && NAME_EXCLUDE.test(label)) continue;
        return rule.key;
      }
    }
    return null;
  }

  function autofill(profile) {
    const fields = document.querySelectorAll("input, textarea, select");
    let filled = 0, candidates = 0;
    fields.forEach((el) => {
      if (el.disabled || el.readOnly) return;
      const tag = el.tagName.toLowerCase();
      if (tag === "input") {
        const type = (el.type || "text").toLowerCase();
        if (SKIP_INPUT_TYPES.has(type)) return;
      }
      if (!isVisible(el)) return;
      const label = labelText(el);
      if (!label) return;
      const key = matchKey(label);
      if (!key) return;
      candidates++;
      const want = valueFor(key, profile);
      if (!want) return;

      if (tag === "select") {
        if (el.value && el.selectedIndex > 0) return; // already chosen
        if (fillSelect(el, want)) { flag(el); filled++; }
        return;
      }
      // text-like input / textarea
      if (el.value && el.value.trim()) return; // never overwrite existing
      const type = (el.type || "text").toLowerCase();
      if (type === "number" && !/^\d+(\.\d+)?$/.test(want)) return; // don't stuff "22 LPA" into a number box
      setNativeValue(el, want);
      flag(el);
      filled++;
    });
    return { filled, candidates };
  }

  function flag(el) {
    el.classList.add("ruflo-filled");
    setTimeout(() => { el.style.outlineColor = "transparent"; }, 2500);
  }

  // --- UI ---
  function toast(html, ms) {
    let t = document.getElementById("ruflo-toast");
    if (t) t.remove();
    t = document.createElement("div");
    t.id = "ruflo-toast";
    t.innerHTML = html;
    document.body.appendChild(t);
    if (ms) setTimeout(() => { if (t) t.remove(); }, ms);
  }

  function run(btn) {
    btn.disabled = true;
    chrome.runtime.sendMessage({ type: "RUFLO_GET_PROFILE" }, (resp) => {
      btn.disabled = false;
      if (chrome.runtime.lastError || !resp) {
        toast("⚠️ Extension couldn't reach the page. Reload and try again.", 6000);
        return;
      }
      if (!resp.ok) {
        toast("⚠️ Can't reach your dashboard at <b>localhost:8000</b>.<br>Start it, then click ⚡ again.", 8000);
        return;
      }
      const { filled, candidates } = autofill(resp.profile);
      if (filled === 0) {
        toast(candidates ? "No empty fields matched — they may already be filled." : "No matching fields found on this page.", 6000);
      } else {
        toast("⚡ Filled <b>" + filled + "</b> field" + (filled === 1 ? "" : "s") +
          ". Review, attach your résumé, then submit yourself.<br><small>Skipped uploads, passwords &amp; consent boxes on purpose.</small>", 9000);
      }
    });
  }

  function mount() {
    if (document.getElementById("ruflo-fab")) return;
    const btn = document.createElement("button");
    btn.id = "ruflo-fab";
    btn.type = "button";
    btn.textContent = "⚡";
    btn.title = "Auto-fill this form from your Ruflo profile (never submits)";
    btn.addEventListener("click", () => run(btn));
    document.body.appendChild(btn);
  }

  if (document.body) mount();
  else document.addEventListener("DOMContentLoaded", mount);
})();
