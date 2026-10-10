import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  editFilledAnswer, fetchInbox, interpretAnswer, replyQuestion, reviewAnswer, saveAnswer, saveFacts, snoozeInbox,
} from "../api.js";
import { useOptionalAgent } from "../agent/AgentProvider.tsx";

// Only what the agents can't find or work out themselves, one card at a time, as few actions as possible:
//  - a tap on a choice answers and moves on; typed answers are read by the model, so "ML engineer, why didn't you get
//    this from LinkedIn?" becomes the answer "ML Engineer" plus a request the agent handles, and a sentence that
//    answers other questions too fills them as well;
//  - Back / Next (← →) walk the deck and every answer stays editable until you press Submit, which saves them all,
//    puts what you skipped away for a month and hands your requests to the agent.
// Keys: 1–9 pick a choice, Enter saves a typed answer (or confirms a guess), ← → move, Esc leaves a text box.

const ANCHOR = {             // what each card is, for the agent (docs/agent/system.md lists these anchor kinds)
  question: (i) => `question:${i.job_id}:${i.row_id}`,
  guess: (i) => `answer:${i.row_id}`,
  bank: (i) => `qbank:${i.id}`,
};
const KIND = { question: "Holding up an application", guess: "Check the agent's answer", bank: "Most forms ask this" };

function toItems(box) {
  return [
    ...(box.questions || []).map((q) => ({ ...q, type: "question", key: `q${q.row_id}` })),
    ...(box.guesses || []).map((g) => ({ ...g, type: "guess", key: `g${g.row_id}` })),
    // A rule entry ("companies where the answer is Yes") takes a list, never a bare Yes/No.
    ...(box.bank || []).map((b) => ({ ...b, type: "bank", key: `b${b.id}`, label: b.question, hint: b.rule_help,
      options: b.rule ? [] : b.atype === "bool" ? ["Yes", "No"] : b.options || [],
      kindLabel: b.why ? "Some of your jobs ask this" : null,
      context: b.asked_by?.length ? `Asked by ${b.asked_by.join(", ")}` : b.why || "Nearly every application form asks this." })),
  ];
}

const isLong = (item) => /textarea/.test(item.kind || "") || (item.label || "").length > 70;
const typing = (el) => el && (el.tagName === "TEXTAREA" || (el.tagName === "INPUT" && !["checkbox", "radio"].includes(el.type)));

/** Save one staged answer the way its kind is saved. */
function commit(item, s) {
  if (item.type === "question") return replyQuestion(item.job_id, item.row_id, s.value, s.remember ? "new" : "once");
  if (item.type === "guess") return s.confirm ? reviewAnswer(item.row_id, "correct") : editFilledAnswer(item.row_id, s.value, item.matched ? "entry" : "new");
  if (item.fact) return saveFacts({ [item.fact]: s.value });          // a must-have kept on the profile row
  return saveAnswer({ entry_id: item.id, answer: s.value });
}

function Choices({ options, value, onPick }) {
  return (
    <div className="ask-options" role="radiogroup" aria-label="Choices">
      {options.map((o, i) => (
        <button key={o} type="button" role="radio" aria-checked={value === o} className="ask-choice" onClick={() => onPick(o)}>
          {i < 9 && <kbd aria-hidden="true">{i + 1}</kbd>}<span>{o}</span>
        </button>
      ))}
    </div>
  );
}

function Card({ item, staged, onStage, onBack, onNext, canBack, position }) {
  const [value, setValue] = useState(staged?.raw ?? staged?.value ?? item.guess ?? "");
  const [fixing, setFixing] = useState(item.type !== "guess" || (!!staged && !staged.confirm));
  // A question naming this company ("Why Razorpay?") is answered for this application only by default.
  const companySpecific = !!item.company && (item.label || "").toLowerCase().includes(item.company.toLowerCase());
  const [remember, setRemember] = useState(staged?.remember ?? !companySpecific);
  const [reading, setReading] = useState(false);
  const [error, setError] = useState(null);
  const options = item.options || [];
  const [freeform, setFreeform] = useState(!!staged?.value && options.length > 0 && !options.includes(staged.value));
  const card = useRef(null);
  const agent = useOptionalAgent();
  const explain = () => agent?.openPopover(card.current, "What does this mean?");

  const pick = (o) => onStage({ value: o, remember });                        // one tap: staged, on to the next
  const confirmGuess = () => onStage({ value: item.answer, confirm: true });
  const submitText = async () => {
    const text = value.trim();
    if (!text || reading) return;
    setReading(true);
    setError(null);
    try {                                                                   // the model reads it like a person would
      const r = await interpretAnswer(item.label, text, item.type === "bank" ? item.id : undefined, options.length ? options : undefined);
      if (r.answer == null && r.request) { setError("That reads like a question for the agent, so it'll go to the agent when you submit. What's the answer itself?"); }
      onStage({ value: r.answer ?? (r.request ? null : text), raw: text, also: r.also || {}, request: r.request || null, remember },
        r.answer == null && r.request);
    } catch {
      onStage({ value: text, raw: text, remember });
    } finally {
      setReading(false);
    }
  };
  const choosing = options.length > 0 && !freeform && (item.type !== "guess" || fixing);

  const latest = useRef({});
  latest.current = { choosing, options, pick, onBack, onNext, canBack, fixing, confirmGuess, type: item.type };
  useEffect(() => {
    const onKey = (e) => {
      const k = latest.current;
      if (e.metaKey || e.ctrlKey || e.altKey || typing(document.activeElement)) return;
      if (document.activeElement?.closest?.("[data-agent-ui], [role=dialog]")) return;
      if (e.key === "ArrowLeft" && k.canBack) { e.preventDefault(); k.onBack(); }
      else if (e.key === "ArrowRight") { e.preventDefault(); k.onNext(); }
      else if (k.choosing && /^[1-9]$/.test(e.key) && k.options[Number(e.key) - 1] !== undefined) { e.preventDefault(); k.pick(k.options[Number(e.key) - 1]); }
      else if (e.key === "Enter" && k.type === "guess" && !k.fixing && document.activeElement?.tagName !== "BUTTON") { e.preventDefault(); k.confirmGuess(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const Tag = isLong(item) ? "textarea" : "input";
  return (
    <article className="ask" aria-label="Question from the agent" ref={card} data-agent={ANCHOR[item.type](item)}>
      <div className="ask-top">
        <span className="ask-kind">{item.kindLabel || KIND[item.type]}</span>
        <span className="ask-pos">{position}</span>
      </div>
      {item.company ? <p className="ask-context">{item.company} · {item.title}</p> : item.context && <p className="ask-context">{item.context}</p>}
      <h2 className="ask-q">{item.label}</h2>
      {item.hint && <p className="ask-hint">{item.hint}</p>}
      {staged?.value && (
        <p className="ask-saved" role="status">
          Answer: <b>{staged.confirm ? "the agent's guess" : staged.value}</b>
          {Object.keys(staged.also || {}).length > 0 && <> · also fills {Object.keys(staged.also).length} more</>}
          {staged.request && <> · a request goes to the agent</>}
        </p>
      )}

      {item.type === "guess" && !fixing ? (
        <>
          <p className="ask-answer">{item.answer}</p>
          <div className="ask-row">
            <button className="btn btn-primary" onClick={confirmGuess}>Looks right <kbd aria-hidden="true">↵</kbd></button>
            <button className="btn" onClick={() => { setValue(item.answer); setFixing(true); }}>Fix it</button>
          </div>
        </>
      ) : choosing ? (
        <Choices options={options} value={staged?.value} onPick={pick} />
      ) : (
        <div className="ask-row ask-row-input">
          <Tag className="ask-input" aria-label="Your answer" autoFocus value={value} rows={Tag === "textarea" ? 4 : undefined}
            placeholder="Answer in your own words. The agent tidies it up." onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (Tag === "input" || e.metaKey || e.ctrlKey)) { e.preventDefault(); submitText(); }
              if (e.key === "Escape") e.currentTarget.blur();
            }} />
          <button className="btn btn-primary" disabled={reading || !value.trim()} onClick={submitText}>{reading ? "Reading…" : "OK"}</button>
        </div>
      )}

      <div className="ask-help">
        {agent && <button className="linkish" onClick={explain}>What does this mean?</button>}
        {options.length > 0 && (item.type !== "guess" || fixing) && (
          <button className="linkish" onClick={() => { setFreeform((f) => !f); setValue(""); }}>
            {freeform ? "Pick from the choices" : "Type my own answer"}
          </button>
        )}
        {item.type === "question" && (
          <label className="remember">
            <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /> Use for every application
          </label>
        )}
      </div>
      {error && <div role="status" className="ask-note">{error}</div>}

      <nav className="ask-nav" aria-label="Questions">
        <button className="btn btn-quiet btn-sm" aria-label="Previous question" disabled={!canBack} onClick={onBack}>← Back</button>
        <span className="ask-keys" aria-hidden="true">{choosing ? `1–${Math.min(options.length, 9)} choose · ` : ""}← → move</span>
        <button className="btn btn-quiet btn-sm" aria-label="Next question" onClick={onNext}>{staged?.value ? "Next →" : "Skip →"}</button>
      </nav>
    </article>
  );
}

function Deck({ items, staged, at, onJump }) {
  return (
    <ol className="deck-list" aria-label="All questions">
      {items.map((x, k) => (
        <li key={x.key}>
          <button className="deck-item" aria-current={k === at ? "step" : undefined} onClick={() => onJump(k)}
            data-state={staged[x.key]?.value ? "done" : k === at ? "now" : "todo"}>
            <span className="deck-mark" aria-hidden="true">{staged[x.key]?.value ? "✓" : k + 1}</span>
            <span className="deck-label">{x.label}</span>
          </button>
        </li>
      ))}
    </ol>
  );
}

export default function Inbox({ onCount, onGoJobs, onSubmitted, embedded = false }) {
  const agent = useOptionalAgent();
  const [items, setItems] = useState(null);
  const [at, setAt] = useState(0);
  const [staged, setStaged] = useState({});          // key -> {value, raw?, also?, request?, remember?, confirm?}
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => fetchInbox().then((b) => { setItems(toItems(b)); setAt(0); setStaged({}); })
    .catch((e) => setError(String(e))), []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (items) onCount?.(items.length); }, [items, onCount]);

  if (error) return <div role="alert" className="alert">{error}</div>;
  if (!items) return null;
  if (!items.length) {
    if (embedded) return <p className="view-sub needs-none">{note || "Nothing needs you. The agents have what they need for every application in the queue."}</p>;
    return (
      <div className="empty">
        <div className="empty-mark" aria-hidden="true">✓</div>
        <h2>Nothing needs you</h2>
        <p>{note || "The agent has everything it asked for. Skip or apply to jobs to teach it what you want."}</p>
        <button className="btn btn-primary" onClick={onGoJobs}>Review jobs</button>
      </div>
    );
  }

  const answered = items.filter((x) => staged[x.key]?.value);
  const reviewing = at >= items.length;
  const i = Math.min(at, items.length - 1);
  const item = items[i];
  const nextOpen = (from, s) => {
    for (let d = 1; d <= items.length; d++) {
      const k = from + d;
      if (k >= items.length) return items.length;                          // the end: review and submit
      if (!s[items[k].key]?.value) return k;
    }
    return items.length;
  };
  const stage = (v, stay = false) => {
    const s = { ...staged, [item.key]: { ...staged[item.key], ...v } };
    setStaged(s);
    if (!stay) setAt(nextOpen(i, s));
  };

  const submit = async () => {
    setBusy(true);
    const failed = [];
    const requests = [];
    const also = {};
    for (const x of items) {
      const s = staged[x.key];
      if (s?.request) requests.push(`${x.label}: ${s.request}`);
      if (!s?.value) continue;
      Object.assign(also, s.also || {});
      try { await commit(x, s); } catch (e) { failed.push(`${x.label} (${e.message || e})`); }
    }
    if (Object.keys(also).length) await saveFacts(also).catch(() => failed.push("the extra answers"));
    const skipped = items.filter((x) => !staged[x.key]?.value && x.type !== "question").map((x) => x.key);
    if (skipped.length) await snoozeInbox(skipped).catch(() => {});
    if (requests.length && agent) {
      void agent.ask(`While answering my Inbox questions I also asked:\n${requests.map((r) => `- ${r}`).join("\n")}\nPlease handle these.`);
    }
    const saved = answered.length + Object.keys(also).length;
    setNote(failed.length ? `Saved ${saved - failed.length}; couldn't save ${failed.join(", ")}.`
      : `Saved ${saved} answer${saved === 1 ? "" : "s"}${skipped.length ? `; ${skipped.length} skipped won't come back for a month` : ""}`
        + `${requests.length ? `; the agent is on your ${requests.length} request${requests.length === 1 ? "" : "s"}` : ""}.`);
    setBusy(false);
    onSubmitted?.();
    await load();
  };

  const blocking = items.filter((x) => x.type === "question").length;
  const Title = embedded ? "h2" : "h1";
  const submitBtn = (
    <button className="btn btn-primary" disabled={busy || (!answered.length && !items.length)} onClick={submit}>
      {busy ? "Saving…" : answered.length ? `Submit ${answered.length} answer${answered.length === 1 ? "" : "s"}` : "Skip these for now"}
    </button>
  );

  return (
    <section aria-label="Needs you" className="needs">
      <div className="needs-head">
        <div>
          <Title className={embedded ? "section-title" : "view-title"}>
            {blocking ? `${blocking} question${blocking > 1 ? "s" : ""} holding up applications`
              : `${items.length} question${items.length === 1 ? "" : "s"} the agents couldn't answer`}
          </Title>
          <p className="view-sub">{note || "Answer what you can, skip the rest, then submit. Nothing is saved until you do."}</p>
        </div>
        {submitBtn}
      </div>
      <div className="progress" aria-hidden="true">
        {items.map((x, k) => <span key={x.key} className={staged[x.key]?.value ? "done" : k === i && !reviewing ? "now" : ""} />)}
      </div>
      <div className="deck">
        {reviewing ? (
          <div className="ask ask-finished">
            <h2 className="ask-q">{answered.length ? `Ready to save ${answered.length} answer${answered.length === 1 ? "" : "s"}` : "Nothing answered yet"}</h2>
            <ul className="review-list">
              {items.map((x, k) => (
                <li key={x.key}>
                  <button className="linkish" onClick={() => setAt(k)}>{x.label}</button>
                  <span>{staged[x.key]?.confirm ? "agent's guess ✓" : staged[x.key]?.value || (x.type === "question" ? "unanswered" : "skipped")}</span>
                </li>
              ))}
            </ul>
            <div className="ask-row">
              <button className="btn" onClick={() => setAt(items.length - 1)}>← Back</button>
              {submitBtn}
            </div>
          </div>
        ) : (
          <Card key={item.key} item={item} staged={staged[item.key]} position={`${i + 1} of ${items.length}`} onStage={stage}
            canBack={i > 0} onBack={() => setAt(i - 1)} onNext={() => setAt(i + 1)} />
        )}
        <Deck items={items} staged={staged} at={reviewing ? -1 : i} onJump={setAt} />
      </div>
    </section>
  );
}
