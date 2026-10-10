import React, { useCallback, useEffect, useRef, useState } from "react";
import { editFilledAnswer, fetchInbox, replyQuestion, reviewAnswer, saveAnswer } from "../api.js";
import { useOptionalAgent } from "../agent/AgentProvider.tsx";

// Everything the agent needs from you, one card at a time. Each answer goes straight back into its memory:
// a blocking question unblocks that application, a confirmed guess becomes a trusted match, a bank answer is
// reused on every future form.
//
// Built to take as few actions as possible: a question with choices saves on one tap and moves on; Back and Next
// (or ← →) walk the deck, and going back shows what you answered so you can change it. Keys: 1–9 pick a choice,
// Enter saves (or confirms a guess), ← → move, Esc leaves a text box so the arrows work again.

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
      options: b.rule ? [] : b.atype === "bool" ? ["Yes", "No"] : b.options || [],
      context: b.asked_by?.length ? `Asked by ${b.asked_by.join(", ")}`
        : "A common form question. None of your applications has asked it yet." })),
  ];
}

const isLong = (item) => /textarea/.test(item.kind || "") || (item.label || "").length > 70;
const typing = (el) => el && (el.tagName === "TEXTAREA" || (el.tagName === "INPUT" && !["checkbox", "radio"].includes(el.type)));

function Choices({ options, value, onPick, disabled }) {
  return (
    <div className="ask-options" role="radiogroup" aria-label="Choices">
      {options.map((o, i) => (
        <button key={o} type="button" role="radio" aria-checked={value === o} className="ask-choice" disabled={disabled}
          onClick={() => onPick(o)}>
          {i < 9 && <kbd aria-hidden="true">{i + 1}</kbd>}<span>{o}</span>
        </button>
      ))}
    </div>
  );
}

function TextAnswer({ item, value, setValue, onSubmit }) {
  const Tag = isLong(item) ? "textarea" : "input";
  return (
    <Tag className="ask-input" aria-label="Your answer" autoFocus value={value} rows={isLong(item) ? 4 : undefined}
      placeholder={Tag === "textarea" ? "Type your answer (⌘ Enter saves)" : "Type your answer and press Enter"}
      onChange={(e) => setValue(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter" && (Tag === "input" || e.metaKey || e.ctrlKey)) { e.preventDefault(); onSubmit(); }
        if (e.key === "Escape") e.currentTarget.blur();
      }} />
  );
}

function Card({ item, saved, onSaved, onBack, onNext, canBack, position }) {
  const [value, setValue] = useState(saved?.value ?? item.guess ?? "");
  const [fixing, setFixing] = useState(item.type !== "guess" || !!saved);
  // A question naming this company ("Why Razorpay?") is answered for this application only by default.
  const companySpecific = !!item.company && (item.label || "").toLowerCase().includes(item.company.toLowerCase());
  const [remember, setRemember] = useState(!companySpecific);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const options = item.options || [];
  const [freeform, setFreeform] = useState(!!saved && options.length > 0 && !options.includes(saved.value));
  const card = useRef(null);
  const agent = useOptionalAgent();
  // Opens the agent's popover on this card with the question already sent; follow-ups ("then answer No") go there too.
  const explain = () => agent?.openPopover(card.current, "What does this mean?");

  const run = (p, note, answer) => {
    setBusy(true);
    setError(null);
    p.then((r) => onSaved(r?.requeued ? "Answered — the application is back in the queue." : note, answer))
      .catch((e) => { setError(String(e.message || e)); setBusy(false); });
  };
  const submit = (raw = value) => {
    const ans = String(raw).trim();
    if (!ans || busy) return;
    if (item.type === "question") run(replyQuestion(item.job_id, item.row_id, ans, remember ? "new" : "once"),
      remember ? "Saved — reused on every future form." : "Saved for this application.", ans);
    else if (item.type === "guess") run(editFilledAnswer(item.row_id, ans, item.matched ? "entry" : "new"),
      "Corrected — the agent won't repeat that.", ans);
    else run(saveAnswer({ entry_id: item.id, answer: ans }), "Saved to memory.", ans);
  };
  const pick = (o) => { setValue(o); submit(o); };             // one tap: save and move on
  const confirmGuess = () => run(reviewAnswer(item.row_id, "correct"), "Confirmed — trusted next time.", item.answer);
  const choosing = options.length > 0 && !freeform;

  const latest = useRef({});
  latest.current = { choosing, options, pick, onBack, onNext, canBack, fixing, confirmGuess, busy };
  useEffect(() => {
    const onKey = (e) => {
      const k = latest.current;
      if (e.metaKey || e.ctrlKey || e.altKey || typing(document.activeElement) || k.busy) return;
      if (document.activeElement?.closest?.("[data-agent-ui], [role=dialog]")) return;
      if (e.key === "ArrowLeft" && k.canBack) { e.preventDefault(); k.onBack(); }
      else if (e.key === "ArrowRight") { e.preventDefault(); k.onNext(); }
      else if (k.choosing && /^[1-9]$/.test(e.key) && k.options[Number(e.key) - 1] !== undefined) {
        e.preventDefault(); k.pick(k.options[Number(e.key) - 1]);
      } else if (e.key === "Enter" && !k.fixing && document.activeElement?.tagName !== "BUTTON") { e.preventDefault(); k.confirmGuess(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <article className="ask" aria-label="Question from the agent" ref={card} data-agent={ANCHOR[item.type](item)}>
      <div className="ask-top">
        <span className="ask-kind">{KIND[item.type]}</span>
        <span className="ask-pos">{position}</span>
      </div>
      {item.company ? <p className="ask-context">{item.company} · {item.title}</p>
        : item.context && <p className="ask-context">{item.context}</p>}
      <h2 className="ask-q">{item.label}</h2>
      {item.hint && <p className="ask-hint">{item.hint}</p>}
      {saved && <p className="ask-saved" role="status">Your answer: <b>{saved.value}</b>. Pick or type another to change it.</p>}

      {item.type === "guess" && !fixing ? (
        <>
          <p className="ask-answer">{item.answer}</p>
          <div className="ask-row">
            <button className="btn btn-primary" disabled={busy} onClick={confirmGuess}>Looks right <kbd aria-hidden="true">↵</kbd></button>
            <button className="btn" disabled={busy} onClick={() => { setValue(item.answer); setFixing(true); }}>Fix it</button>
          </div>
        </>
      ) : choosing ? (
        <Choices options={options} value={saved?.value ?? value} onPick={pick} disabled={busy} />
      ) : (
        <div className="ask-row ask-row-input">
          <TextAnswer item={item} value={value} setValue={setValue} onSubmit={() => submit()} />
          <button className="btn btn-primary" disabled={busy || !value.trim()} onClick={() => submit()}>Save</button>
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
            <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
            Use for every application
          </label>
        )}
      </div>
      {error && <div role="alert" className="alert">{error}</div>}

      <nav className="ask-nav" aria-label="Questions">
        <button className="btn btn-quiet btn-sm" aria-label="Previous question" disabled={!canBack} onClick={onBack}>← Back</button>
        <span className="ask-keys" aria-hidden="true">
          {choosing ? `1–${Math.min(options.length, 9)} choose · ` : ""}← → move{item.type === "guess" && !fixing ? " · ↵ confirm" : ""}
        </span>
        <button className="btn btn-quiet btn-sm" aria-label="Next question" onClick={onNext}>{saved ? "Next →" : "Skip →"}</button>
      </nav>
    </article>
  );
}

function Deck({ items, saved, at, onJump }) {
  return (
    <ol className="deck-list" aria-label="All questions">
      {items.map((x, k) => (
        <li key={x.key}>
          <button className="deck-item" aria-current={k === at ? "step" : undefined} onClick={() => onJump(k)}
            data-state={saved[x.key] ? "done" : k === at ? "now" : "todo"}>
            <span className="deck-mark" aria-hidden="true">{saved[x.key] ? "✓" : k + 1}</span>
            <span className="deck-label">{x.label}</span>
          </button>
        </li>
      ))}
    </ol>
  );
}

export default function Inbox({ onCount, onGoJobs, embedded = false }) {
  const [items, setItems] = useState(null);
  const [at, setAt] = useState(0);
  const [saved, setSaved] = useState({});            // key -> {value, note}: answered this visit, still revisitable
  const [note, setNote] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => fetchInbox().then((b) => { setItems(toItems(b)); setAt(0); setSaved({}); })
    .catch((e) => setError(String(e))), []);
  useEffect(() => { load(); }, [load]);
  const left = items ? items.filter((x) => !saved[x.key]).length : 0;
  useEffect(() => { if (items) onCount?.(left); }, [items, left, onCount]);

  if (error) return <div role="alert" className="alert">{error}</div>;
  if (!items) return null;
  if (!items.length && embedded) {
    return <p className="view-sub needs-none">Nothing needs you. Every application has what it asked for.</p>;
  }
  if (!items.length) {
    return (
      <div className="empty">
        <div className="empty-mark" aria-hidden="true">✓</div>
        <h2>Nothing needs you</h2>
        <p>The agent has everything it asked for. Skip or apply to jobs to teach it what you want.</p>
        <button className="btn btn-primary" onClick={onGoJobs}>Review jobs</button>
      </div>
    );
  }

  const finished = at >= items.length;
  const i = Math.min(at, items.length - 1);
  const item = items[i];
  const nextOpen = (from, done) => {
    for (let s = 1; s <= items.length; s++) {
      const k = (from + s) % items.length;
      if (!done[items[k].key]) return k;
    }
    return items.length;                                // all answered: the summary
  };
  const onSaved = (msg, value) => {
    const done = { ...saved, [item.key]: { value, note: msg } };
    setSaved(done);
    setNote(msg);
    setAt(nextOpen(i, done));
  };
  const blocking = items.filter((x) => x.type === "question" && !saved[x.key]).length;
  const Title = embedded ? "h2" : "h1";

  return (
    <section aria-label="Needs you" className="needs">
      <Title className={embedded ? "section-title" : "view-title"}>
        {finished ? "All answered"
          : blocking ? `${blocking} question${blocking > 1 ? "s" : ""} holding up applications`
          : `${left} thing${left === 1 ? "" : "s"} to teach the agent`}
      </Title>
      <p className="view-sub">{note || "Each answer is remembered, so the agent asks less every time."}</p>
      <div className="progress" aria-hidden="true">
        {items.map((x, k) => <span key={x.key} className={saved[x.key] ? "done" : k === i && !finished ? "now" : ""} />)}
      </div>
      <div className="deck">
        {finished ? (
          <div className="ask ask-finished">
            <h2 className="ask-q">That's everything for now.</h2>
            <p className="ask-context">The agent saved all {items.length} answers and will reuse them on every form.</p>
            <div className="ask-row">
              <button className="btn" onClick={() => setAt(items.length - 1)}>← Review my answers</button>
              <button className="btn btn-primary" onClick={load}>Check for more</button>
            </div>
          </div>
        ) : (
          <Card key={`${item.key}:${saved[item.key]?.value ?? ""}`} item={item} saved={saved[item.key]}
            position={`${i + 1} of ${items.length}`} onSaved={onSaved} canBack={i > 0}
            onBack={() => setAt(i - 1)} onNext={() => setAt(i + 1 < items.length ? i + 1 : left ? 0 : items.length)} />
        )}
        <Deck items={items} saved={saved} at={finished ? -1 : i} onJump={setAt} />
      </div>
    </section>
  );
}
