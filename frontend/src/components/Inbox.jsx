import React, { useCallback, useEffect, useRef, useState } from "react";
import { editFilledAnswer, fetchInbox, replyQuestion, reviewAnswer, saveAnswer } from "../api.js";
import { useOptionalAgent } from "../agent/AgentProvider.tsx";

// Everything the agent needs from you, one card at a time. Each answer goes straight back into its memory:
// a blocking question unblocks that application, a confirmed guess becomes a trusted match, a bank answer is
// reused on every future form.
// What each card is, for the agent (docs/agent/system.md lists these anchor kinds).
const ANCHOR = {
  question: (i) => `question:${i.job_id}:${i.row_id}`,
  guess: (i) => `answer:${i.row_id}`,
  bank: (i) => `qbank:${i.id}`,
};

const KIND = {
  question: "Holding up an application",
  guess: "Check the agent's answer",
  bank: "Answer once, reused everywhere",
};

function toItems(box) {
  return [
    ...(box.questions || []).map((q) => ({ ...q, type: "question", key: `q${q.row_id}` })),
    ...(box.guesses || []).map((g) => ({ ...g, type: "guess", key: `g${g.row_id}` })),
    // A rule entry ("companies where the answer is Yes") takes a list, never a bare Yes/No.
    ...(box.bank || []).map((b) => ({ ...b, type: "bank", key: `b${b.id}`, label: b.question, hint: b.rule_help,
      options: b.atype === "bool" && !b.rule ? ["Yes", "No"] : [],
      context: b.asked_by?.length ? `Asked by ${b.asked_by.join(", ")}`
        : "A common form question. None of your applications has asked it yet." })),
  ];
}

const isLong = (item) => /textarea/.test(item.kind || "") || (item.label || "").length > 70;

function AnswerInput({ item, value, setValue, onSubmit, freeform }) {
  if (item.options?.length && !freeform) {
    return (
      <div className="ask-options" role="radiogroup" aria-label="Choices">
        {item.options.map((o) => (
          <button key={o} type="button" className="chip" aria-pressed={value === o} onClick={() => setValue(o)}>{o}</button>
        ))}
      </div>
    );
  }
  const Tag = isLong(item) ? "textarea" : "input";
  return (
    <Tag className="ask-input" aria-label="Your answer" autoFocus value={value} rows={isLong(item) ? 5 : undefined}
      placeholder="Type your answer" onChange={(e) => setValue(e.target.value)}
      onKeyDown={(e) => { if (e.key === "Enter" && (Tag === "input" || e.metaKey)) onSubmit(); }} />
  );
}

function Card({ item, onDone, onSkip }) {
  const [value, setValue] = useState(item.guess || "");
  const [fixing, setFixing] = useState(item.type !== "guess");
  // A question naming this company ("Why Razorpay?") is answered for this application only by default.
  const companySpecific = !!item.company && (item.label || "").toLowerCase().includes(item.company.toLowerCase());
  const [remember, setRemember] = useState(!companySpecific);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [freeform, setFreeform] = useState(false);
  const card = useRef(null);
  const agent = useOptionalAgent();
  // Opens the agent's popover on this card with the question already sent; follow-ups ("then answer No") go there too.
  const explain = () => agent?.openPopover(card.current, "What does this mean?");
  const explainLink = agent && <button className="linkish" onClick={explain}>What does this mean?</button>;
  const helpers = (
    <div className="ask-help">
      {explainLink}
      {item.options?.length > 0 && (
        <button className="linkish" onClick={() => { setFreeform((f) => !f); setValue(""); }}>
          {freeform ? "Pick from the choices" : "Type my own answer"}
        </button>
      )}
    </div>
  );

  const run = (p, note) => {
    setBusy(true);
    setError(null);
    p.then((r) => onDone(r?.requeued ? "Answered — the application is back in the queue." : note))
      .catch((e) => { setError(String(e.message || e)); setBusy(false); });
  };
  const submit = () => {
    const ans = value.trim();
    if (!ans || busy) return;
    if (item.type === "question") run(replyQuestion(item.job_id, item.row_id, ans, remember ? "new" : "once"),
      remember ? "Saved — reused on every future form." : "Saved for this application.");
    else if (item.type === "guess") run(editFilledAnswer(item.row_id, ans, item.matched ? "entry" : "new"),
      "Corrected — the agent won't repeat that.");
    else run(saveAnswer({ entry_id: item.id, answer: ans }), "Saved to memory.");
  };

  return (
    <article className="ask" aria-label="Question from the agent" ref={card} data-agent={ANCHOR[item.type](item)}>
      <span className="ask-kind">{KIND[item.type]}</span>
      {item.company ? <p className="ask-context">{item.company} · {item.title}</p>
        : item.context && <p className="ask-context">{item.context}</p>}
      <h2 className="ask-q">{item.label}</h2>
      {item.hint && <p className="ask-hint">{item.hint}</p>}
      {item.type === "guess" && !fixing ? (
        <>
          <p className="ask-answer">{item.answer}</p>
          {explainLink && <div className="ask-help">{explainLink}</div>}
          <div className="ask-foot">
            <button className="btn btn-primary" disabled={busy}
              onClick={() => run(reviewAnswer(item.row_id, "correct"), "Confirmed — trusted next time.")}>Looks right</button>
            <button className="btn" disabled={busy} onClick={() => { setValue(item.answer); setFixing(true); }}>Fix it</button>
            <span className="spacer" />
            <button className="btn btn-quiet" onClick={onSkip}>Later</button>
          </div>
        </>
      ) : (
        <>
          <AnswerInput item={item} value={value} setValue={setValue} onSubmit={submit} freeform={freeform} />
          {helpers}
          <div className="ask-foot">
            <button className="btn btn-primary" disabled={busy || !value.trim()} onClick={submit}>Save</button>
            {item.type === "question" && (
              <label className="remember">
                <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
                Use for every application
              </label>
            )}
            <span className="spacer" />
            <button className="btn btn-quiet" onClick={onSkip}>Later</button>
          </div>
        </>
      )}
      {error && <div role="alert" className="alert">{error}</div>}
    </article>
  );
}

export default function Inbox({ onCount, onGoJobs }) {
  const [items, setItems] = useState(null);
  const [at, setAt] = useState(0);
  const [note, setNote] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => fetchInbox().then((b) => { setItems(toItems(b)); setAt(0); })
    .catch((e) => setError(String(e))), []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (items) onCount?.(items.length); }, [items, onCount]);

  if (error) return <div role="alert" className="alert">{error}</div>;
  if (!items) return null;
  if (!items.length) {
    return (
      <div className="empty">
        <div className="empty-mark" aria-hidden="true">✓</div>
        <h2>Nothing needs you</h2>
        <p>{note || "The agent has everything it asked for. Skip or apply to jobs to teach it what you want."}</p>
        <button className="btn btn-primary" onClick={onGoJobs}>Review jobs</button>
      </div>
    );
  }
  const i = Math.min(at, items.length - 1);
  const item = items[i];
  const done = (msg) => { setNote(msg); setItems((xs) => xs.filter((x) => x.key !== item.key)); };
  const skip = () => setAt((i + 1) % items.length);
  const blocking = items.filter((x) => x.type === "question").length;

  return (
    <section aria-label="Needs you">
      <h1 className="view-title">{blocking ? `${blocking} question${blocking > 1 ? "s" : ""} holding up applications`
        : `${items.length} thing${items.length > 1 ? "s" : ""} to teach the agent`}</h1>
      <p className="view-sub">{note || "Each answer is remembered, so the agent asks less every time."}</p>
      <div className="progress" aria-hidden="true">
        {items.map((x, k) => <span key={x.key} className={k === i ? "now" : k < i ? "done" : ""} />)}
      </div>
      <Card key={item.key} item={item} onDone={done} onSkip={skip} />
    </section>
  );
}
