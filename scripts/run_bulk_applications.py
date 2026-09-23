"""Run career agent on all URLs in data/job_urls_collected.json.

Logs each outcome to data/bulk_run_log.json.
Problems (non-submit stops) written to data/bulk_problems.md.
"""
from __future__ import annotations
import argparse, json, select, subprocess, sys, time, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from career_agent.reliability.rate_limiter import RateLimiter, map_outcome

URLS_FILE  = Path(__file__).parent.parent / "data" / "job_urls_collected.json"
LOG_FILE   = Path(__file__).parent.parent / "data" / "bulk_run_log.json"
PROB_FILE  = Path(__file__).parent.parent / "data" / "bulk_problems.md"

AGENT_CMD  = [sys.executable, "-m", "career_agent.apply"]
AGENT_ENV_EXTRA = {"PYTHONPATH": "src", "CAREER_AGENT_LIVEVIEW_DEBUG": "1"}
CDP_URL    = "http://localhost:9222"
RESUME_PDF = "data/resumes/resume.pdf"


def run_one(url: str, idx: int) -> dict:
    cmd = AGENT_CMD + [
        "--url", url,
        "--cdp-url", CDP_URL,
        "--resume-pdf", RESUME_PDF,
    ]
    env = {**__import__("os").environ, **AGENT_ENV_EXTRA}
    start = time.time()
    print(f"\n{'='*60}", flush=True)
    print(f"[{idx}] {url[:80]}", flush=True)
    lines: list[str] = []
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
        cwd=str(Path(__file__).parent.parent))
    deadline = start + 900
    try:
        while True:
            if time.time() > deadline:
                proc.kill()
                break
            ready, _, _ = select.select([proc.stdout], [], [], 5.0)
            if ready:
                try:
                    line = proc.stdout.readline()
                except Exception:
                    break
                if not line:
                    if proc.poll() is not None:
                        break
                    continue
                line = line.rstrip()
                lines.append(line)
                print(f"  | {line}", flush=True)
            elif proc.poll() is not None:
                break
    finally:
        proc.wait()
    elapsed = round(time.time() - start, 1)
    out = "\n".join(lines)
    # parse stopped_reason from last dict line
    stopped = "unknown"
    filled = 0
    for line in reversed(out.splitlines()):
        if "'stopped_reason'" in line or '"stopped_reason"' in line:
            import re
            m = re.search(r"stopped_reason['\"]:\s*['\"]([^'\"]+)", line)
            if m:
                stopped = m.group(1)
            mf = re.search(r"filled=(\d+)", line)
            if mf:
                filled = int(mf.group(1))
            break
    rec = {
        "idx": idx,
        "url": url,
        "stopped_reason": stopped,
        "filled": filled,
        "elapsed_s": elapsed,
        "timestamp": datetime.datetime.now().isoformat(),
        "stdout_tail": out[-1500:],
    }
    print(f"  stopped={stopped}  filled={filled}  {elapsed}s")
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pace", default="medium", choices=["fast", "medium", "slow"],
                    help="Gap between runs: fast=30-90s, medium=2-5m, slow=8-15m")
    ap.add_argument("--urls-file", default=str(URLS_FILE))
    args, _ = ap.parse_known_args()

    urls_data = json.loads(Path(args.urls_file).read_text())
    rl = RateLimiter(pace=args.pace)

    # Resume: load existing log so already-completed jobs are skipped
    log: list[dict] = []
    if LOG_FILE.exists():
        try:
            log = json.loads(LOG_FILE.read_text())
        except Exception:
            log = []
    done_urls = {r["url"] for r in log}
    if done_urls:
        print(f"[resume] skipping {len(done_urls)} already-logged jobs")

    problems: list[dict] = [r for r in log if r["stopped_reason"] not in ("reached_submit_dry_run", "submitted")]

    if not done_urls:
        PROB_FILE.write_text("# Bulk run problems\n\n")

    queue = [(i, job["url"]) for i, job in enumerate(urls_data, 1) if job["url"] not in done_urls]
    deferred: list[tuple[int, str]] = []

    def _run(i, url):
        try:
            return run_one(url, i)
        except subprocess.TimeoutExpired:
            print("  TIMEOUT")
            return {"idx": i, "url": url, "stopped_reason": "timeout",
                    "filled": 0, "elapsed_s": 900, "stdout_tail": ""}
        except Exception as e:
            print(f"  EXCEPTION: {e}")
            return {"idx": i, "url": url, "stopped_reason": f"exception:{e}",
                    "filled": 0, "elapsed_s": 0, "stdout_tail": ""}

    def _record_and_log(rec):
        log.append(rec)
        LOG_FILE.write_text(json.dumps(log, indent=2))
        if rec["stopped_reason"] not in ("reached_submit_dry_run", "submitted"):
            problems.append(rec)
            with PROB_FILE.open("a") as f:
                f.write(f"## [{rec['idx']}] {rec['url'][:80]}\n")
                f.write(f"- reason: `{rec['stopped_reason']}`\n")
                f.write(f"- filled: {rec['filled']}  elapsed: {rec['elapsed_s']}s\n")
                if rec.get("stdout_tail"):
                    tail = "\n".join(rec["stdout_tail"].splitlines()[-10:])
                    f.write(f"```\n{tail}\n```\n\n")

    # --- Main queue ---
    for i, url in queue:
        domain = rl.domain_key(url)
        decision = rl.check(domain)
        if decision != "ok":
            print(f"  [rate-limiter] {decision} → deferring {url[:60]}")
            deferred.append((i, url))
            continue
        rec = _run(i, url)
        rl.record(domain, map_outcome(rec["stopped_reason"]))
        _record_and_log(rec)
        rl.wait_pace(domain)

    # --- One retry pass for deferred jobs ---
    if deferred:
        print(f"\n[rate-limiter] retrying {len(deferred)} deferred jobs…")
    for i, url in deferred:
        domain = rl.domain_key(url)
        decision = rl.check(domain)
        if decision == "ok":
            rec = _run(i, url)
            rl.record(domain, map_outcome(rec["stopped_reason"]))
            _record_and_log(rec)
            rl.wait_pace(domain)
        else:
            print(f"  [rate-limiter] still {decision} — skipping {url[:60]}")
            rec = {"idx": i, "url": url, "stopped_reason": "skipped_rate_limit",
                   "filled": 0, "elapsed_s": 0, "stdout_tail": ""}
            _record_and_log(rec)

    # Summary
    summary_lines = ["\n## Summary",
                     f"Total: {len(log)}",
                     f"Reached submit: {sum(1 for r in log if r['stopped_reason'] in ('reached_submit_dry_run','submitted'))}",
                     f"Problems: {len(problems)}"]
    with PROB_FILE.open("a") as f:
        f.write("\n".join(summary_lines))

    print("\n" + "="*60)
    print(f"Done. {len(log)} runs. Problems: {len(problems)}")
    print(f"Log → {LOG_FILE}")
    print(f"Problems → {PROB_FILE}")


if __name__ == "__main__":
    main()
