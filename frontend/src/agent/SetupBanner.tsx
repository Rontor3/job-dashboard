// Setup isn't finished (data/setup-state.md missing or not `status: complete`): offer to finish it with the agent.
// The user is never forced through it; "Not now" hides the banner for this browser session.
import { useEffect, useState } from "react";
import { useAgent } from "./AgentProvider.tsx";
import { fetchSetupState } from "./client.ts";

const HIDE = "agent-setup-banner-hidden";

function hidden(): boolean {
  try {
    return sessionStorage.getItem(HIDE) === "1";
  } catch {
    return false;
  }
}

export default function SetupBanner() {
  const agent = useAgent();
  const [show, setShow] = useState(false);
  useEffect(() => {
    if (hidden()) return;
    fetchSetupState().then((s) => setShow(!s.exists || s.status !== "complete")).catch(() => {});
  }, []);
  if (!show) return null;
  const dismiss = () => {
    try {
      sessionStorage.setItem(HIDE, "1");
    } catch {
      // private mode: just hide it now
    }
    setShow(false);
  };
  return (
    <div className="agent-banner" role="status" data-agent-ui>
      <span>Setup isn't finished: the apply agent works best once it knows your model, profile and résumé.</span>
      <button className="btn btn-primary btn-sm" onClick={() => {
        agent.openTab();
        void agent.ask("Let's finish setting up the app.");
        setShow(false);
      }}>Finish setup with the agent</button>
      <button className="btn btn-quiet btn-sm" onClick={dismiss}>Not now</button>
    </div>
  );
}
