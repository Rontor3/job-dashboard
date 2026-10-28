#!/usr/bin/env python3
"""Regenerate scripts/branch-viewer.html from the current git state.

Interactive branch graph + pipeline overview for this repo (self-contained
HTML, no dependencies). Re-run after committing/branching to refresh:

    python3 scripts/branch_flow.py
"""
import datetime
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
WINDOW = 300  # commits shown in the graph window
SEP = "\x09"  # ref-field separator
FS = "\x01"   # commit-field separator


def run(*args: str) -> str:
    r = subprocess.run(["git", *args], capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def parse_refs():
    fmt = (f"%(refname){SEP}%(objectname){SEP}%(objectname:short){SEP}"
           f"%(committerdate:unix){SEP}%(authorname){SEP}%(upstream:short){SEP}"
           f"%(contents:subject)")
    out = run("for-each-ref", f"--format={fmt}", "refs/heads", "refs/remotes")
    branches = []
    for line in out.strip().splitlines():
        name, tip, short, ts, author, up, subj = line.split(SEP)
        if name == "refs/remotes/origin/HEAD":
            continue
        kind = "local" if name.startswith("refs/heads/") else "remote"
        branches.append({
            "ref": name.replace("refs/heads/", "").replace("refs/remotes/", ""),
            "tip": tip,
            "short": short,
            "ts": int(ts),
            "author": author,
            "upstream": up or None,
            "subject": subj,
            "kind": kind,
        })
    return branches


def worktree_branches():
    out = run("worktree", "list", "--porcelain")
    path = None
    wts = {}
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line.startswith("branch ") and path:
            wts[line[len("branch refs/heads/"):]] = path
    return wts


def ahead_behind(base: str, ref: str):
    out = run("rev-list", "--left-right", "--count", f"{base}...{ref}")
    behind, ahead = out.split()[:2]
    return int(behind), int(ahead)


def main():
    base = "main"
    if run("rev-parse", "--verify", "-q", base).strip() == "":
        base = "origin/main"

    branches = parse_refs()
    wts = worktree_branches()

    for b in branches:
        behind, ahead = ahead_behind(base, b["ref"])
        b["behind"], b["ahead"] = behind, ahead
        if b["kind"] == "local":
            b["worktree"] = wts.get(b["ref"])
        else:
            b["worktree"] = None
        b["hist"] = run("rev-list", b["ref"], f"-{WINDOW}").split()

    out = run("log", "--all", f"--max-count={WINDOW}", "--topo-order",
              f"--format=%H{FS}%P{FS}%at{FS}%an{FS}%s")
    commits = []
    for line in out.strip().splitlines():
        h, parents, ts, author, subject = line.split(FS)
        commits.append({"h": h, "sh": h[:7], "p": parents.split(),
                        "t": int(ts), "a": author, "s": subject})

    heads = {}
    for b in branches:
        heads.setdefault(b["tip"], []).append(b["ref"])

    try:
        origin_head = run("symbolic-ref", "-q",
                          "refs/remotes/origin/HEAD").strip()
        origin_head = origin_head.replace("refs/remotes/origin/", "")
    except SystemExit:
        origin_head = "main"

    data = {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "window": WINDOW,
        "total": int(run("rev-list", "--all", "--count").strip()),
        "current": run("rev-parse", "--abbrev-ref", "HEAD").strip(),
        "default": origin_head,
        "repoUrl": run("remote", "get-url", "origin").strip().removesuffix(".git"),
        "branches": branches,
        "commits": commits,
        "heads": heads,
    }

    html = TEMPLATE.replace("__DATA__", json.dumps(data))
    out_path = ROOT / "scripts" / "branch-viewer.html"
    out_path.write_text(html)
    kb = out_path.stat().st_size // 1024
    print(f"wrote {out_path.relative_to(ROOT)} ({kb} KB) "
          f"[{len(branches)} branches, {len(commits)}/{data['total']} commits]")


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Commit Graph — Job Dashboard</title>
<style>
:root{
  --bg:#0e1126;--panel:#131732;--panel2:#171b3a;--line:#232a4d;--line2:#2e3766;
  --text:#e5e6f3;--mut:#8f97b8;--dim:#5f678d;--acc:#ff2d78;--acc2:#00b8d9;
  --vio:#8b5cf6;--ok:#22d3a6;--warn:#ffb020;
}
*{box-sizing:border-box}
body{margin:0;background:
  radial-gradient(1000px 460px at 88% -12%,#2a1158 0%,transparent 60%),
  radial-gradient(900px 400px at -10% -5%,#06283a 0%,transparent 55%),
  var(--bg);
  color:var(--text);font:14px/1.45 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.hd{position:sticky;top:0;z-index:30;display:flex;align-items:center;gap:14px;
  padding:9px 16px;background:#0e1126e8;backdrop-filter:blur(10px);
  border-bottom:1px solid var(--line);flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:11px}
.brand .mark{width:15px;height:15px;border-radius:50%;flex-shrink:0;
  background:conic-gradient(from 210deg,#ff2d78,#8b5cf6,#00b8d9,#ff2d78);
  box-shadow:0 0 14px #ff2d7866}
.brand .tt{font-size:12px;letter-spacing:.16em;color:var(--mut);font-weight:600}
.brand .tt b{color:var(--text);font-size:13.5px;letter-spacing:.02em;margin-left:8px}
.brand .tt b small{color:var(--dim);font-weight:500;letter-spacing:0}
.tabs{display:flex;background:var(--panel);border:1px solid var(--line);border-radius:999px;padding:3px;gap:2px}
.tabs button{border:0;background:transparent;color:var(--mut);padding:5.5px 15px;border-radius:999px;
  font:inherit;font-size:12.5px;font-weight:600;cursor:pointer;transition:.15s}
.tabs button:hover{color:var(--text)}
.tabs button.on{background:linear-gradient(135deg,#8b5cf6,#ff2d78);color:#fff;box-shadow:0 2px 12px #8b5cf655}
.tools{display:flex;gap:8px;margin-left:auto;align-items:center;flex-wrap:wrap}
input,select{background:#0d1030;border:1px solid var(--line);color:var(--text);
  border-radius:999px;padding:7px 13px;font:inherit;font-size:13px;outline:none;min-width:0}
input:focus,select:focus{border-color:var(--acc2);box-shadow:0 0 0 3px #00b8d922}
input{width:250px}
.stats{color:var(--dim);font-size:11.5px;white-space:nowrap}
.main{max-width:1400px;margin:0 auto;padding:10px 14px 70px}
.view{display:none}.view.on{display:block}

/* ---- commit graph ---- */
.graphwrap{position:relative;border:1px solid var(--line);border-radius:14px;background:#0d1030;
  overflow:hidden;box-shadow:0 14px 44px #060a1780}
#svg{position:absolute;top:0;pointer-events:none;opacity:.98}
.crow{display:flex;align-items:center;height:30px;padding-right:14px;position:relative;
  cursor:pointer;transition:background .1s,opacity .25s}
.crow:nth-child(even){background:#ffffff05}
.crow:hover{background:#1a214555}
.crow.dim{opacity:.13}
.crow.open{background:#8b5cf61c}
.rail{position:absolute;left:0;top:0;bottom:0;width:var(--railw);display:flex;align-items:center;
  gap:6px;padding-left:10px;overflow:hidden;z-index:2}
.chip{font-size:11px;font-weight:600;padding:1.5px 9px 1.5px 19px;border-radius:6px;
  position:relative;white-space:nowrap;cursor:pointer;max-width:calc(var(--railw) - 26px);
  overflow:hidden;text-overflow:ellipsis}
.chip::before{content:"";position:absolute;left:7px;top:50%;width:7px;height:7px;border-radius:50%;
  transform:translateY(-50%)}
.chip.cur{background:#8b5cf626;color:#c4b5fd;border:1px solid #8b5cf655}
.chip.cur::before{background:#a78bfa}
.chip.main{background:#ff2d7822;color:#ff9ec2;border:1px solid #ff2d7855}
.chip.main::before{background:#ff2d78}
.chip.loc{background:#00b8d914;color:#7fdcef;border:1px solid #00b8d940}
.chip.loc::before{background:#00b8d9}
.chip.rem{border:1px dashed #3a4370;color:var(--mut);padding-left:12px;background:#ffffff06}
.chip.cur.selr{outline:1.5px solid #a78bfa;outline-offset:1px}
.av{position:absolute;width:19px;height:19px;border-radius:50%;z-index:3;pointer-events:none;
  display:grid;place-items:center;font-size:8.5px;font-weight:800;color:#0b0e1c;
  box-shadow:0 0 0 2.5px #0d1030,0 0 10px 1px var(--glow,#8b5cf666)}
.crow.dim .av{opacity:.15}
.subj{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#dcdef2;font-size:13.2px}
.crow.dim .subj{opacity:.4}
.meta{display:flex;gap:10px;align-items:center;color:var(--dim);font-size:11.5px;flex-shrink:0;padding-left:14px}
.auth{color:var(--mut)}
.time{min-width:64px;text-align:right}
.hash{font:11px ui-monospace,Menlo,monospace;color:#7d86ad;background:#ffffff08;
  border:1px solid #ffffff0f;border-radius:5px;padding:2px 6px}

/* ---- drawer ---- */
#det{position:fixed;right:18px;bottom:18px;width:400px;max-width:calc(100vw - 36px);z-index:40;
  background:linear-gradient(165deg,#191f43,#131732);border:1px solid var(--line2);
  border-radius:14px;padding:16px;box-shadow:0 24px 60px #060a17cc;
  transform:translateY(14px);opacity:0;pointer-events:none;transition:.2s}
#det.on{transform:none;opacity:1;pointer-events:auto}
#det h3{margin:0 14px 10px 0;font-size:14.5px;font-weight:700;color:#f1f2fa}
#det .rowline{display:flex;gap:8px;align-items:center;margin:7px 0;color:var(--mut);font-size:13px}
#det .k{color:var(--dim);width:64px;flex-shrink:0;font-size:12px}
#det .v{font:12px/1.4 ui-monospace,Menlo,monospace;color:var(--text);word-break:break-all}
#det a{color:var(--acc2);text-decoration:none;font-size:13px}
#det a:hover{text-decoration:underline}
#det .x{position:absolute;top:10px;right:12px;border:0;background:#ffffff0d;color:var(--mut);
  width:26px;height:26px;border-radius:8px;cursor:pointer}
#det .x:hover{color:var(--text);background:#ffffff1a}
#det .tips{display:flex;flex-wrap:wrap;gap:6px}
#det .tips .chip{position:static;padding:1.5px 9px 1.5px 9px}
#det .tips .chip::before{display:none}

/* ---- branch cards ---- */
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:14px}
.card{background:linear-gradient(160deg,var(--panel2),var(--panel));border:1px solid var(--line);
  border-radius:14px;padding:14px 16px;cursor:pointer;transition:.15s}
.card:hover{transform:translateY(-2px);border-color:var(--line2);box-shadow:0 10px 28px #060a1788}
.card.on{border-color:#8b5cf688;box-shadow:0 0 0 3px #8b5cf622,0 10px 28px #060a1788}
.card .nm{font:600 13px/1.3 ui-monospace,Menlo,monospace;display:flex;align-items:center;gap:8px}
.card .nm .dot{width:9px;height:9px;border-radius:50%;background:var(--acc);flex-shrink:0;box-shadow:0 0 8px var(--acc)}
.card.remote .nm .dot{background:var(--dim);box-shadow:none}
.card .badges{display:flex;flex-wrap:wrap;gap:6px;margin:9px 0}
.pill{font-size:11px;padding:2.5px 9px;border-radius:20px;border:1px solid}
.pill.ahead{background:#22d3a617;border-color:#22d3a640;color:#7deede}
.pill.behind{background:#ffb02014;border-color:#ffb02033;color:#ffce70}
.pill.wt{background:#00b8d914;border-color:#00b8d940;color:#7fdcef}
.pill.up{border-style:dashed;border-color:var(--line2);color:var(--dim)}
.pill.ro{background:#8b5cf617;border-color:#8b5cf644;color:#c4b5fd}
.pill.cur{background:#ff2d781f;border-color:#ff2d7855;color:#ff9ec2}
.card .tip{color:var(--mut);font-size:12.5px;margin-top:8px;display:flex;justify-content:space-between;gap:10px}
.card .tip span:first-child{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.card .wpath{color:var(--dim);font:11px ui-monospace,Menlo,monospace;margin-top:7px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.grp{margin:6px 0 12px;color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.12em}

/* ---- pipeline ---- */
.flow{max-width:860px;margin:0 auto}
.stage{border:1px solid var(--line);border-left:4px solid var(--acc);border-radius:12px;padding:14px 18px;
  background:linear-gradient(160deg,var(--panel2),var(--panel))}
.stage h4{margin:0 0 4px;font-size:14px}
.stage .n{color:var(--dim);font-size:11px;letter-spacing:.1em;margin-right:8px}
.stage p{margin:6px 0 0;color:var(--mut);font-size:12.5px}
.stage .srcs{display:flex;flex-wrap:wrap;gap:6px;margin-top:9px}
.tag{font-size:11px;background:#0d1030;border:1px solid var(--line);border-radius:20px;
  padding:2px 9px;color:var(--mut)}
.tag.b{border-color:#00b8d944;color:#7fdcef}
.arr{text-align:center;color:var(--acc);font-size:18px;padding:4px 0;line-height:1}
.note{border:1px solid #ffb02033;border-left:4px solid var(--warn);border-radius:12px;padding:12px 16px;
  background:#ffb0210a;color:#ffce70;font-size:12.5px;margin-top:14px}
.note b{color:#ffce70}
code{font:12px ui-monospace,Menlo,monospace;background:#0d1030;border:1px solid var(--line);
  border-radius:6px;padding:1.5px 6px;color:#7fdcef}
</style>
</head>
<body>
<div class="hd">
  <div class="brand">
    <div class="mark"></div>
    <div class="tt">COMMIT GRAPH <b>Job Dashboard <small id="repo"></small></b></div>
  </div>
  <div class="tabs">
    <button data-v="graph" class="on">Graph</button>
    <button data-v="branches">Branches</button>
    <button data-v="flow">Pipeline</button>
  </div>
  <div class="tools">
    <input id="q" placeholder="Search commits ( author, message, sha )" spellcheck="false">
    <select id="sel"><option value="">All Branches</option></select>
    <span class="stats" id="st"></span>
  </div>
</div>

<div class="main">
  <div class="view on" id="v-graph">
    <div class="graphwrap" id="gw"><svg id="svg"></svg><div id="list"></div></div>
  </div>

  <div class="view" id="v-branches"><div class="cards" id="cards"></div></div>

  <div class="view" id="v-flow">
    <div class="flow">
      <div class="stage"><h4><span class="n">TRIGGER</span>Refresh — API entry point</h4>
        <p><code>api/refresh_job.py</code> → <code>pipeline.run_pipeline()</code> runs stages in order and reports per-stage callbacks.</p>
      </div>
      <div class="arr">↓</div>
      <div class="stage"><h4><span class="n">1 · INGEST</span>Pull job listings from public APIs</h4>
        <p>Wired via <code>source_registry.job_sources()</code> — search terms × region; target-role filter applied on loose sources.</p>
        <div class="srcs"><span class="tag b">jobspy → Indeed (India)</span><span class="tag b">remotive</span><span class="tag b">himalayas</span><span class="tag">remoteok (whole board)</span><span class="tag b">weworkremotely</span><span class="tag">20 ML/AI/DS search terms</span></div>
      </div>
      <div class="arr">↓</div>
      <div class="stage"><h4><span class="n">2 · BROWSER</span>CDP browser sources (logged-in session)</h4>
        <p>Streamed per-site with own counts. Wellfound is <b style="color:#7fdcef">on-demand only</b> — deliberately not in the unattended refresh.</p>
        <div class="srcs"><span class="tag b">LinkedIn (CDP)</span><span class="tag b">Naukri (CDP)</span><span class="tag">wellfound (manual)</span></div>
      </div>
      <div class="arr">↓</div>
      <div class="stage"><h4><span class="n">3 · DEDUP</span><code>match/dedup ·mark_duplicates()</code></h4>
        <p>Marks duplicates; suspected duplicates reported back.</p></div>
      <div class="arr">↓</div>
      <div class="stage"><h4><span class="n">4 · CLASSIFY</span><code>classify.run ·classify_unclassified()</code></h4>
        <p>Company classification. Syntax/import failures silently skip (count stays 0).</p></div>
      <div class="arr">↓</div>
      <div class="stage"><h4><span class="n">5 · SCORE</span>Embedding match vs profile</h4>
        <p><code>compose_profile_text()</code> → embed model → <code>compute_embed_scores()</code> keyed by profile hash.</p></div>
      <div class="arr">↓</div>
      <div class="stage" style="border-left-color:var(--acc2)"><h4 style="color:#7fdcef"><span class="n">STORE</span><code>data/jobs.db</code></h4>
        <p>Single shared store for both subsystems.</p>
        <div class="srcs"><span class="tag">deep_rank</span><span class="tag">eligibility</span><span class="tag">freshness</span><span class="tag">relevance</span><span class="tag">compensation</span><span class="tag">apply_type</span><span class="tag">liveness</span></div></div>
      <div class="arr">↓</div>
      <div class="stage" style="border-left-color:var(--vio)"><h4 style="color:#c4b5fd"><span class="n">CONSUME</span>API → frontend / extension / career_agent</h4>
        <p><code>api/app.py</code> serves dashboard; browser extension reads it; <code>career_agent</code> consumes jobs + profile for auto-apply (dry-run gated).</p></div>
      <div class="note"><b>Failure semantics:</b> embedding problems (missing dep / profile / model errors) never abort ingest or dedup — they surface as <b>embed_skipped</b>. Browser-source errors become <b>site notes</b>. No CI/CD: this repo has no GitHub Actions — the pipeline is data, triggered by the API.</div>
    </div>
  </div>
</div>

<div id="det">
  <button class="x" onclick="closeDet()">✕</button>
  <h3 id="d-sub"></h3>
  <div class="rowline"><span class="k">author</span><span class="v" id="d-au"></span></div>
  <div class="rowline"><span class="k">commit</span><span class="v" id="d-h"></span></div>
  <div class="rowline"><span class="k">date</span><span class="v" id="d-t"></span></div>
  <div class="rowline"><span class="k">parents</span><span class="v" id="d-p"></span></div>
  <div class="rowline"><span class="k">refs</span><span class="tips" id="d-r"></span></div>
  <div class="rowline"><span class="k">github</span><a id="d-l" target="_blank">open commit ↗</a></div>
</div>

<script>
const DATA = __DATA__;
const PALETTE=["#ff2d78","#00b8d9","#8b5cf6","#22d3a6","#ffb020","#4f8cff","#e254ff","#35e0d0","#ff6d4d","#b8e62e"];
const ROWH=30, COLW=17, RAILW=210;
let selRef=null, selSet=null, openCommit=null;
document.documentElement.style.setProperty("--railw", RAILW+"px");

const $=s=>document.querySelector(s);
const esc=s=>String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");

function relTime(ts){
  const d=Date.now()/1000-ts;
  if(d<3600) return Math.max(1,d/60|0)+"m";
  if(d<86400) return (d/3600|0)+"h";
  if(d<86400*14) return (d/86400|0)+"d";
  if(d<86400*60) return (d/604800|0)+"w";
  if(d<86400*365) return (d/2592000|0)+"mo";
  return (d/31536000|0)+"y";
}
function fullDate(ts){return new Date(ts*1000).toLocaleString("en-GB",{dateStyle:"medium",timeStyle:"short"})}
function initials(n){const p=n.trim().split(/[\s._-]+/);return ((p[0]||"?")[0]+(p[1]?p[1][0]:"")).toUpperCase()}
function avColor(n){let h=0;for(const c of n)h=(h*31+c.charCodeAt(0))%360;return `hsl(${h},66%,58%)`}
function chipClass(ref){
  if(ref===DATA.default||ref==="main") return "main";
  if(ref===DATA.current) return "cur";
  if(ref.startsWith("origin/")) return "rem";
  return "loc";
}
function chipHTML(ref,extra){
  const short=ref.startsWith("origin/")?ref.slice(7)+" ⟠":ref;
  return `<span class="chip ${chipClass(ref)}${ref===selRef?" selr":""}" data-ref="${esc(ref)}" ${extra||""}>${esc(short)}</span>`;
}

function computeGraph(commits){
  const S=[],C=[]; const rows=[]; let ci=0;
  const nc=()=>PALETTE[ci++%PALETTE.length];
  let maxLanes=0;
  for(const c of commits){
    const before=S.slice();
    let li;
    const incoming=[];
    for(let k=0;k<before.length;k++) if(before[k]===c.h) incoming.push(k);
    if(incoming.length){ li=incoming[0]; incoming.forEach(k=>S[k]=null); }
    else{
      li=S.indexOf(null);
      if(li<0){ S.push(null); C.push(nc()); li=S.length-1; }
    }
    const color = C[li]!==undefined ? C[li] : nc();
    C[li]=color;
    const outgoing=[];
    if(c.p.length){ S[li]=c.p[0];
      for(let i=1;i<c.p.length;i++){
        const p=c.p[i], ex=S.indexOf(p);
        if(ex>=0) continue;
        let fr=S.indexOf(null);
        if(fr<0){ S.push(p); C.push(color); outgoing.push(S.length-1); }
        else{ S[fr]=p; C[fr]=color; outgoing.push(fr); }
      }
    } else S[li]=null;
    const after=S.slice();
    for(let k=0;k<S.length;k++) if(S[k]&&(k>=C.length)){C[k]=color;}
    const vertical=[];
    for(let k=0;k<Math.min(before.length,S.length);k++)
      if(before[k]&&S[k]===before[k]) vertical.push(k);
    maxLanes=Math.max(maxLanes,S.length);
    rows.push({c,li,color,incoming,vertical,outgoing});
  }
  return {rows,maxLanes};
}

const X=k=>k*COLW+16, Y=i=>i*ROWH+ROWH/2, TOP=i=>i*ROWH, BOT=i=>(i+1)*ROWH;

function render(){
  let list=DATA.commits;
  const q=$("#q").value.trim().toLowerCase();
  if(q) list=list.filter(c=>(c.s+" "+c.a+" "+c.sh+" "+c.h).toLowerCase().includes(q));
  const g=computeGraph(list);
  const GW=(g.maxLanes+1)*COLW+14;
  const svg=$("#svg");
  svg.style.left=RAILW+"px";
  const H=list.length*ROWH;
  svg.setAttribute("width",GW); svg.setAttribute("height",H);
  svg.setAttribute("viewBox","0 0 "+GW+" "+H);
  let pl="";
  const line=(d,col)=>pl+=`<path d="${d}" stroke="${col}" fill="none" stroke-width="2.6" stroke-linecap="round" opacity=".92"/>`;
  for(let i=0;i<g.rows.length;i++){
    const r=g.rows[i];
    for(const k of r.incoming) line(`M ${X(k)} ${TOP(i)} C ${X(k)} ${TOP(i)+8}, ${X(r.li)} ${Y(i)-9}, ${X(r.li)} ${Y(i)}`,PALETTE[r.color]);
    for(const k of r.vertical) line(`M ${X(k)} ${TOP(i)} L ${X(k)} ${BOT(i)}`,PALETTE[r.color]);
    for(const k of r.outgoing) line(`M ${X(r.li)} ${Y(i)} C ${X(r.li)} ${Y(i)+9}, ${X(k)} ${BOT(i)-8}, ${X(k)} ${BOT(i)}`,PALETTE[r.color]);
  }
  svg.innerHTML=pl;
  let html="";
  for(const r of g.rows){
    const c=r.c;
    const dim=selSet&&!selSet.has(c.h);
    const chips=(DATA.heads[c.h]||[]).map(ref=>chipHTML(ref));
    const col=avColor(c.a);
    html+=`<div class="crow${dim?" dim":""}" data-h="${c.h}" style="padding-left:${RAILW+GW+16}px">
      <div class="rail">${chips.join("")}</div>
      <div class="av" style="left:${RAILW+X(r.li)-9.5}px;--glow:${PALETTE[r.color]}66;background:${col}">${esc(initials(c.a))}</div>
      <span class="subj">${esc(c.s)}</span>
      <span class="meta"><span class="auth">${esc(c.a)}</span><span class="time">${relTime(c.t)}</span><span class="hash">${c.sh}</span></span>
    </div>`;
  }
  $("#list").innerHTML=html||`<div style="padding:30px;color:var(--dim)">No commits match “${esc(q)}”.</div>`;
  $("#st").textContent=`${DATA.total} commits · showing latest ${DATA.window}`+(q?` · matching ${list.length}`:"");
}

/* drawer */
function openDet(hash){
  const c=DATA.commits.find(x=>x.h===hash); if(!c)return;
  openCommit=hash;
  $("#d-sub").textContent=c.s;
  $("#d-au").textContent=c.a+" · "+relTime(c.t)+" ago";
  $("#d-h").textContent=c.sh+" "+c.h;
  $("#d-h").dataset.full=c.h;
  $("#d-t").textContent=fullDate(c.t);
  $("#d-p").textContent=c.p.length?c.p.map(p=>p.slice(0,7)).join(" ⌥ "):"—";
  const tips=DATA.heads[c.h]||[];
  $("#d-r").innerHTML=tips.length?tips.map(t=>chipHTML(t)).join(""):"<span class='chip rem'>no refs</span>";
  $("#d-l").href=DATA.repoUrl+"/commit/"+c.h;
  $("#det").classList.add("on");
  document.querySelectorAll(".crow.open").forEach(x=>x.classList.remove("open"));
  const row=[...document.querySelectorAll(".crow")].find(x=>x.dataset.h===hash);
  if(row) row.classList.add("open");
}
function closeDet(){$("#det").classList.remove("on");document.querySelectorAll(".crow.open").forEach(x=>x.classList.remove("open"));openCommit=null;}

/* interactions */
$("#list").addEventListener("click",e=>{
  const row=e.target.closest(".crow"); if(!row)return;
  if(e.target.classList.contains("chip")){
    e.stopPropagation();
    const ref=e.target.dataset.ref;
    selRef=(selRef===ref)?null:ref; syncSel(); return;
  }
  if(row.dataset.h) openDet(row.dataset.h);
});
$("#q").addEventListener("input",render);
$("#sel").addEventListener("change",e=>{selRef=e.target.value||null;render()});
$("#d-h").addEventListener("click",()=>{navigator.clipboard&&navigator.clipboard.writeText($("#d-h").dataset.full)});

function syncSel(){
  selSet=null;
  if(selRef){const b=DATA.branches.find(x=>x.ref===selRef); if(b) selSet=new Set(b.hist);}
  $("#sel").value=selRef||"";
  document.querySelectorAll(".card").forEach(cd=>cd.classList.toggle("on",cd.dataset.ref===selRef));
  render();
}

/* tabs */
document.querySelectorAll(".tabs button").forEach(b=>b.onclick=()=>{
  document.querySelectorAll(".tabs button").forEach(x=>x.classList.toggle("on",x===b));
  document.querySelectorAll(".view").forEach(v=>v.classList.toggle("on",v.id==="v-"+b.dataset.v));
});

/* branch select */
(function(){
  const sel=$("#sel");
  const loc=DATA.branches.filter(b=>b.kind==="local"),
        rem=DATA.branches.filter(b=>b.kind==="remote");
  const g=(arr,lbl)=>{
    if(!arr.length)return;
    const og=document.createElement("optgroup"); og.label=lbl;
    arr.forEach(b=>{const o=document.createElement("option");o.value=b.ref;o.textContent=`${b.ref}  (${b.ahead}↑ ${b.behind}↓)`;og.appendChild(o);});
    sel.appendChild(og);
  };
  g(loc,"Local");g(rem,"Remote");
})();

/* branch cards */
(function(){
  const wrap=$("#cards");
  const mk=b=>{
    const wt=b.worktree?`<div class="wpath" title="${esc(b.worktree)}">└ worktree · ${esc(b.worktree.split("/").slice(-2).join("/"))}</div>`:"";
    const d=document.createElement("div");
    d.className="card "+(b.kind==="remote"?"remote":"");
    d.dataset.ref=b.ref;
    d.innerHTML=`<div class="nm"><span class="dot"></span>${esc(b.ref)}
        ${b.ref===DATA.current?`<span class="pill cur">current</span>`:""}
        ${b.ref===DATA.default?`<span class="pill cur">HEAD</span>`:""}</div>
      <div class="badges">
        ${b.ahead?`<span class="pill ahead">${b.ahead} ahead</span>`:""}
        ${b.behind?`<span class="pill behind">${b.behind} behind</span>`:""}
        ${b.kind==="remote"?`<span class="pill ro">remote</span>`:""}
        ${b.upstream?`<span class="pill up">↕ ${esc(b.upstream)}</span>`:""}
        ${!b.ahead&&!b.behind?`<span class="pill ahead">in sync</span>`:""}
      </div>
      <div class="tip"><span>${esc(b.subject)}</span><span style="flex-shrink:0;color:var(--dim)">${relTime(b.ts)} · ${b.short}</span></div>${wt}`;
    d.onclick=()=>{selRef=selRef===b.ref?null:b.ref;syncSel();};
    return d;
  };
  DATA.branches.filter(b=>b.kind==="local").forEach(b=>wrap.appendChild(mk(b)));
  DATA.branches.filter(b=>b.kind==="remote").forEach(b=>wrap.appendChild(mk(b)));
})();

$("#repo").textContent="· "+DATA.repoUrl.replace(/^https?:\/\//,"");
if(selRef===null&&DATA.current){/* show everything by default */}
render();
window.closeDet=closeDet;
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
