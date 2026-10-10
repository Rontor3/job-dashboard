// What the agent asks the human for, in the thread. Each widget does its part straight against FastAPI (the value,
// the file, the Confirm), then tells the agent only the outcome.
import { useEffect, useState } from "react";
import { useAgent } from "./AgentProvider.tsx";
import {
  cancelAction, confirmAction, fetchConfirmation, putSecret, secretsPresent, uploadResume, type Confirmation,
} from "./client.ts";

export function SecretWidget({ keyName, reason }: { keyName: string; reason: string }) {
  const { ask } = useAgent();
  const [value, setValue] = useState("");
  const [state, setState] = useState<"idle" | "busy" | "set" | string>("idle");
  useEffect(() => {
    secretsPresent().then((s) => { if (s.secrets[keyName]) setState("set"); }).catch(() => {});
  }, [keyName]);
  const save = async () => {
    if (!value.trim()) return;
    setState("busy");
    try {
      await putSecret(keyName, value.trim());
      setValue("");
      setState("set");
      await ask(`[I set ${keyName}]`);
    } catch (e) {
      setState(`Couldn't save: ${(e as Error).message}`);
    }
  };
  return (
    <form className="agent-widget" data-agent-ui onSubmit={(e) => { e.preventDefault(); void save(); }}>
      <div className="agent-widget-title">{keyName}</div>
      {reason && <p className="agent-widget-why">{reason}</p>}
      {state === "set" ? <p className="agent-widget-done">✓ Set. The agent can see that it's set, never the value.</p> : (
        <>
          <input type="password" autoComplete="off" aria-label={`Value for ${keyName}`} value={value}
            onChange={(e) => setValue(e.target.value)} placeholder="Paste the value" />
          <button className="btn btn-primary" disabled={!value.trim() || state === "busy"}>Save</button>
          <p className="agent-widget-why">Goes straight to your .env file. It never enters the chat.</p>
        </>
      )}
      {state.startsWith("Couldn't") && <p role="alert">{state}</p>}
    </form>
  );
}

export function UploadWidget({ reason }: { reason: string }) {
  const { ask } = useAgent();
  const [state, setState] = useState<"idle" | "busy" | "done" | string>("idle");
  const pick = async (file: File | undefined) => {
    if (!file) return;
    setState("busy");
    try {
      await uploadResume(file);
      setState("done");
      await ask("[I uploaded my résumé]");
    } catch (e) {
      setState(`Couldn't upload: ${(e as Error).message}`);
    }
  };
  return (
    <div className="agent-widget" data-agent-ui>
      <div className="agent-widget-title">Your résumé (PDF)</div>
      {reason && <p className="agent-widget-why">{reason}</p>}
      {state === "done" ? <p className="agent-widget-done">✓ Uploaded.</p> : (
        <input type="file" accept="application/pdf" aria-label="Résumé PDF" disabled={state === "busy"}
          onChange={(e) => void pick(e.target.files?.[0])} />
      )}
      {state.startsWith("Couldn't") && <p role="alert">{state}</p>}
    </div>
  );
}

export function ConfirmWidget({ confirmation }: { confirmation: Confirmation }) {
  const { ask, sessions } = useAgent();
  const session = sessions.active ?? "";
  const [status, setStatus] = useState<Confirmation["status"]>(confirmation.status);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (session) fetchConfirmation(session, confirmation.id).then((c) => c && setStatus(c.status)).catch(() => {});
  }, [session, confirmation.id]);

  const decide = async (yes: boolean) => {
    setBusy(true);
    setError(null);
    try {
      if (yes) {
        const r = await confirmAction(session, confirmation);
        setStatus("used");
        await ask(r.status < 400 ? `Confirmed: ${confirmation.summary}. It's done.`
          : `Confirmed: ${confirmation.summary}, but it failed (${r.status}): ${r.detail}`);
      } else {
        await cancelAction(confirmation.id);
        setStatus("cancelled");
        await ask(`Cancelled: ${confirmation.summary}`);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="agent-widget agent-confirm" data-agent-ui>
      <div className="agent-widget-title">{confirmation.summary}</div>
      <code className="agent-widget-why">{confirmation.method} {confirmation.path}</code>
      {status === "pending" ? (
        <div className="agent-widget-actions">
          <button className="btn btn-primary" disabled={busy} onClick={() => void decide(true)}>Confirm</button>
          <button className="btn" disabled={busy} onClick={() => void decide(false)}>Cancel</button>
        </div>
      ) : <p className="agent-widget-done">{status === "cancelled" ? "Cancelled." : "Confirmed."}</p>}
      {error && <p role="alert">{error}</p>}
    </div>
  );
}
