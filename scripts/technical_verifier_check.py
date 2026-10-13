"""How reliable is the local fact-checker? Plant known false claims into technical answers and see whether it flags them, and
whether it wrongly flags the clean originals.

  PYTHONPATH=src python3 scripts/technical_verifier_check.py <clean_answers.json>

clean_answers.json: [{"id","question","answer"}]. Writes data/reports/technical_verifier_check.md."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import longform_metrics as L                                    # noqa: E402
from career_agent.longform.technical import verify              # noqa: E402

# (answer id, the planted false sentence, why it is false)
PLANTED = [
    ("t01", "Bagging trains its models sequentially, each one correcting the errors of the previous one.", "that is boosting; bagging trains in parallel"),
    ("t01", "Boosting trains its models in parallel on independent bootstrapped samples.", "that is bagging; boosting is sequential"),
    ("t02", "The output is produced from the queries and keys alone; the values are not used.", "values are weighted by the attention scores"),
    ("t02", "Attention cannot be parallelised across the sequence, which is why transformers train more slowly than RNNs.", "the opposite: attention parallelises, RNNs cannot"),
    ("t03", "Gradient boosted trees handle class imbalance automatically, so no weights or tuning are needed.", "they do not; weights/sampling/metric choice are needed"),
    ("t04", "High bias means the model overfits, while high variance means it underfits.", "reversed: high bias underfits, high variance overfits"),
    ("t04", "Adding more training data always reduces bias.", "more data reduces variance, not bias (an underfit model stays underfit)"),
    ("t05", "Mean imputation never changes a variable's variance or its correlations with other variables.", "it shrinks variance and attenuates correlations"),
    ("t06", "Threads in the same process have separate memory spaces, so they must use inter-process communication to share data.", "threads share their process's memory"),
    ("t06", "Processes share their parent's memory space by default, whereas threads do not.", "reversed"),
]


def words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", s.lower())}


def main(path: str) -> None:
    clean = {r["id"]: r for r in json.load(open(path))}
    judge = L.local_judge()
    judge("ready")
    lines = ["# Local fact-checker: planted-error test", "", "Model: gemma4:26b at temperature 0. A planted false sentence is appended to a clean answer; "
             "'caught' = the reviewer marks a claim incorrect that overlaps the planted sentence (40%+ shared words).", "",
             "## Clean answers (should NOT be flagged)", "", "| Answer | flagged incorrect? | claims it flagged |", "|---|---|---|"]
    fp = 0
    for cid, r in clean.items():
        v = verify(r["question"], r["answer"], judge)
        flagged = bool(v["wrong"]) or v.get("unreadable")
        fp += bool(v["wrong"])
        lines.append(f"| {cid} {r['question'][:55]} | {'YES' if v['wrong'] else 'no'}{' (unreadable)' if v.get('unreadable') else ''} | {'; '.join(c.get('claim', '')[:90] for c in v['wrong']) or ''} |")
        print(cid, "clean flagged:", [c.get("claim", "")[:70] for c in v["wrong"]], flush=True)
    lines += ["", "## Planted errors (should be caught)", "", "| Answer | planted false claim | why false | caught | any flag |", "|---|---|---|---|---|"]
    caught = anyflag = 0
    for cid, false, why in PLANTED:
        r = clean[cid]
        v = verify(r["question"], r["answer"] + " " + false, judge)
        hit = any(len(words(c.get("claim", "")) & words(false)) / max(1, len(words(false))) >= 0.4 for c in v["wrong"])
        caught += hit
        anyflag += bool(v["wrong"])
        lines.append(f"| {cid} | {false[:80]} | {why[:50]} | {'YES' if hit else 'no'} | {'yes' if v['wrong'] else 'no'} |")
        print(cid, "caught" if hit else "MISSED", "|", false[:60], flush=True)
    lines += ["", f"**Caught {caught} of {len(PLANTED)} planted errors ({caught / len(PLANTED):.0%}); any flag {anyflag} of {len(PLANTED)}.  "
              f"False alarms on clean answers: {fp} of {len(clean)}.**"]
    out = ROOT / "data" / "reports" / "technical_verifier_check.md"
    out.write_text("\n".join(lines))
    print(f"\ncaught {caught}/{len(PLANTED)}  any-flag {anyflag}/{len(PLANTED)}  false alarms {fp}/{len(clean)}\n{out}")


if __name__ == "__main__":
    main(sys.argv[1])
