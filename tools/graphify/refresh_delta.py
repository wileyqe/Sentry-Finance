"""Delta-aware graphify refresh.

Looks at commits since the last recorded refresh, re-extracts only the touched
files (AST for code, Sonnet for docs/yaml/json), merges them into the previous
snapshot, and writes a rolling output at docs/audits/graphify-current/.

Semantic re-extraction is dispatched by the host Claude Code session via the
/refresh-graph slash command (or `claude -p /refresh-graph` from the nightly
scheduler). This script never calls the Anthropic API directly; it produces
a manifest of chunks for the host to consume, then reads the per-chunk result
files back during --finalize.

Modes (mutually exclusive):
  --dry-run      Classify diff, print plan, write nothing.
  --code-only    AST-only end-to-end refresh. No agents needed. Used by the
                 pre-push hook.
  --plan-only    AST + manifest. Writes <work>/ast.json plus
                 <work>/manifest.json + <work>/chunk_NN.json files. Exits 0
                 if the host needs to dispatch agents, 1 if the diff was
                 empty or code-only (in which case it finalizes in place).
  --finalize     Consume <work>/manifest.json + chunk_NN_result.json from
                 the host, merge into the previous snapshot, write outputs.

Exit codes (every mode):
  0  refresh applied OR manifest produced and ready for host dispatch
  1  no diff since last_sha (clean exit)
  2  error
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# Resolve project root the same way the rest of tools/graphify/ does.
def _resolve_project_root() -> Path:
    env = os.environ.get("GRAPHIFY_PROJECT_ROOT")
    if env:
        return Path(env).resolve()
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        if out:
            return Path(out).resolve()
    except Exception:
        pass
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT = _resolve_project_root()
TOOLS_DIR = PROJECT_ROOT / "tools" / "graphify"
STATE_PATH = TOOLS_DIR / ".last_refresh.json"
AUDITS_ROOT = PROJECT_ROOT / "docs" / "audits"
CURRENT_DIR = AUDITS_ROOT / "graphify-current"
DEFAULT_WORK_DIR = Path.home() / ".graphify-refresh-cache"

CODE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx"}
SEMANTIC_EXTS = {".md", ".yaml", ".yml", ".json", ".cfg", ".toml", ".ini"}

CHUNK_SIZE_DEFAULT = 22

SKIP_DIR_PATTERN = re.compile(
    r"(^|[\\/])(node_modules|__pycache__|\.git|\.venv|venv|dist|build|\.next|out|coverage|\.cache)([\\/]|$)"
)
SECRET_HINT_RE = re.compile(r"credential|secret|\.env\b", re.IGNORECASE)


def _is_excluded(rel_path: str) -> bool:
    p = rel_path.replace("\\", "/")
    if p.startswith("docs/audits/graphify-"):
        return True
    if p.endswith(".last_refresh.json"):
        return True
    if p.startswith("graphify-out") or "/graphify-out" in p:
        return True
    return False


def _is_sensitive(rel_path: str) -> bool:
    return bool(SECRET_HINT_RE.search(rel_path))


@dataclass
class Plan:
    last_sha: str = ""
    head_sha: str = ""
    code_files: list[Path] = field(default_factory=list)
    semantic_files: list[Path] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)
    ignored_files: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.code_files or self.semantic_files or self.deleted_files)


# -------- git --------

def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=PROJECT_ROOT,
        capture_output=True, text=True, check=True,
    ).stdout


def _git_head() -> str:
    return _git("rev-parse", "HEAD").strip()


def _git_is_clean() -> bool:
    return _git("status", "--porcelain").strip() == ""


def _git_changed_files(since_sha: str, head_sha: str) -> list[tuple[str, str]]:
    out = _git("diff", "--name-status", "--diff-filter=AMRDCT", f"{since_sha}..{head_sha}")
    rows: list[tuple[str, str]] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        rows.append((parts[0][:1], parts[-1]))
    return rows


def _classify(rows: list[tuple[str, str]]) -> Plan:
    plan = Plan()
    for status, rel in rows:
        if SKIP_DIR_PATTERN.search(rel) or _is_excluded(rel) or _is_sensitive(rel):
            plan.ignored_files.append(rel)
            continue
        ext = Path(rel).suffix.lower()
        if status == "D":
            plan.deleted_files.append(rel)
            continue
        abspath = (PROJECT_ROOT / rel).resolve()
        if not abspath.exists():
            plan.deleted_files.append(rel)
            continue
        if ext in CODE_EXTS:
            plan.code_files.append(abspath)
        elif ext in SEMANTIC_EXTS:
            plan.semantic_files.append(abspath)
        else:
            plan.ignored_files.append(rel)
    return plan


# -------- state marker --------

def _load_state() -> dict[str, Any]:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {}


def _write_state(head_sha: str, mode: str) -> None:
    STATE_PATH.write_text(
        json.dumps(
            {
                "last_sha": head_sha,
                "last_run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "last_mode": mode,
                "schema": 1,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _resolve_since(args_since: str | None, state: dict[str, Any]) -> str | None:
    if args_since:
        return args_since
    return state.get("last_sha")


def _bootstrap_last_sha(log) -> str:
    dated = sorted(AUDITS_ROOT.glob("graphify-2*/graph.json"), key=lambda p: p.parent.name)
    if not dated:
        return ""
    try:
        sha = _git("log", "-n", "1", "--format=%H", "--", str(dated[-1])).strip()
        if sha:
            log(f"[bootstrap] using {dated[-1].parent.name} commit as last_sha={sha[:8]}")
            return sha
    except subprocess.CalledProcessError:
        pass
    return ""


# -------- previous-graph discovery --------

def _previous_graph_path() -> Path | None:
    rolling = CURRENT_DIR / "graph.json"
    if rolling.exists():
        return rolling
    candidates = sorted(AUDITS_ROOT.glob("graphify-*/graph.json"), key=lambda p: p.parent.name)
    return candidates[-1] if candidates else None


# -------- AST extraction --------

def _run_ast(code_files: list[Path], work_dir: Path, log) -> dict[str, Any]:
    from graphify.extract import extract  # type: ignore
    if not code_files:
        return {"nodes": [], "edges": [], "input_tokens": 0, "output_tokens": 0}
    work_dir.mkdir(parents=True, exist_ok=True)
    log(f"[ast] re-extracting {len(code_files)} code files")
    result = extract(code_files, cache_root=work_dir)
    nodes = list(result.get("nodes", []))
    edges = list(result.get("edges", []))
    log(f"[ast] {len(nodes)} nodes, {len(edges)} edges")
    return {"nodes": nodes, "edges": edges, "input_tokens": 0, "output_tokens": 0}


# -------- chunking for the manifest --------

def _build_chunks(files: list[Path], chunk_size: int = CHUNK_SIZE_DEFAULT) -> list[list[Path]]:
    chunks: list[list[Path]] = []
    cur: list[Path] = []
    for f in sorted(files):
        cur.append(f)
        if len(cur) >= chunk_size:
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


# -------- merge --------

def _normalize_source(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\\", "/")
    root = str(PROJECT_ROOT).replace("\\", "/")
    lower = text.casefold()
    root_lower = root.casefold()
    if root_lower in lower:
        idx = lower.index(root_lower)
        return text[idx + len(root):].lstrip("/")
    return text


def _merge(
    previous_graph_path: Path | None,
    ast: dict[str, Any],
    semantic: dict[str, Any],
    changed_files_rel: set[str],
    deleted_files_rel: set[str],
    log,
) -> dict[str, Any]:
    if previous_graph_path is None:
        log("[merge] no previous graph; starting from empty base")
        prev_nodes: list[dict[str, Any]] = []
        prev_links: list[dict[str, Any]] = []
        prev_hyperedges: list[dict[str, Any]] = []
    else:
        log(f"[merge] loading previous graph: {previous_graph_path.relative_to(PROJECT_ROOT)}")
        data = json.loads(previous_graph_path.read_text(encoding="utf-8"))
        prev_nodes = list(data.get("nodes", []))
        prev_links = list(data.get("links", []))
        prev_hyperedges = list(data.get("hyperedges", []))

    invalidated = changed_files_rel | deleted_files_rel

    kept_nodes: list[dict[str, Any]] = []
    pruned_ids: set[str] = set()
    for node in prev_nodes:
        src = _normalize_source(node.get("source_file"))
        if src and src in invalidated:
            pruned_ids.add(str(node.get("id")))
            continue
        kept_nodes.append(node)

    def _endpoint(value: Any) -> str:
        return str(value)

    kept_links: list[dict[str, Any]] = []
    for edge in prev_links:
        s = _endpoint(edge.get("source"))
        t = _endpoint(edge.get("target"))
        src = _normalize_source(edge.get("source_file"))
        if s in pruned_ids or t in pruned_ids or (src and src in invalidated):
            continue
        kept_links.append(edge)

    kept_hyperedges: list[dict[str, Any]] = []
    for he in prev_hyperedges:
        if any(_endpoint(n) in pruned_ids for n in he.get("nodes", []) or []):
            continue
        src = _normalize_source(he.get("source_file"))
        if src and src in invalidated:
            continue
        kept_hyperedges.append(he)

    log(
        f"[merge] kept {len(kept_nodes)}/{len(prev_nodes)} nodes, "
        f"{len(kept_links)}/{len(prev_links)} edges, "
        f"{len(kept_hyperedges)}/{len(prev_hyperedges)} hyperedges "
        f"(pruned {len(pruned_ids)} nodes from {len(invalidated)} changed/deleted files)"
    )

    seen_ids = {str(n.get("id")) for n in kept_nodes if n.get("id") is not None}
    new_nodes = list(kept_nodes)
    for node in ast.get("nodes", []) or []:
        nid = str(node.get("id"))
        if nid in seen_ids:
            new_nodes = [n for n in new_nodes if str(n.get("id")) != nid]
        new_nodes.append(node)
        seen_ids.add(nid)
    new_links = list(kept_links) + list(ast.get("edges", []) or [])

    for node in semantic.get("nodes", []) or []:
        nid = str(node.get("id"))
        if nid in seen_ids:
            continue
        new_nodes.append(node)
        seen_ids.add(nid)
    new_links.extend(semantic.get("edges", []) or [])
    new_hyperedges = list(kept_hyperedges) + list(semantic.get("hyperedges", []) or [])

    log(
        f"[merge] final: {len(new_nodes)} nodes, {len(new_links)} edges, "
        f"{len(new_hyperedges)} hyperedges"
    )
    return {
        "nodes": new_nodes,
        "edges": new_links,
        "hyperedges": new_hyperedges,
        "input_tokens": 0,
        "output_tokens": 0,
    }


# -------- rebuild outputs --------

def _rebuild_outputs(extraction: dict[str, Any], out_dir: Path, detection: dict[str, Any], log) -> None:
    from graphify.analyze import god_nodes, suggest_questions, surprising_connections
    from graphify.build import build_from_json
    from graphify.cluster import cluster, score_all
    from graphify import export as graphify_export
    from graphify.export import to_html, to_json
    graphify_export.MAX_NODES_FOR_VIZ = 20_000
    from graphify.report import generate

    out_dir.mkdir(parents=True, exist_ok=True)
    G = build_from_json(extraction, directed=True)
    log(f"[build] {G.number_of_nodes()} nodes, {G.number_of_edges()} edges (directed)")
    if G.number_of_nodes() == 0:
        raise RuntimeError("merged graph is empty; refusing to overwrite snapshot")

    log("[cluster] louvain")
    communities = cluster(G)
    cohesion = score_all(G, communities)
    log(f"[cluster] {len(communities)} communities")

    gods = god_nodes(G)
    surprises = surprising_connections(G, communities)

    from collections import Counter
    STOP = {
        "the", "and", "for", "with", "from", "this", "that", "are", "was",
        "were", "has", "have", "had", "not", "but", "out", "any", "all",
        "one", "two", "now", "new", "old", "use", "uses", "set", "get",
        "got", "put", "post", "delete", "patch", "head", "options", "run",
        "runs", "ran", "return", "returns", "returned", "list", "lists",
        "listed", "endpoint", "endpoints", "router", "routers", "request",
        "requests", "response", "responses", "param", "params", "payload",
        "data", "value", "values", "result", "results", "type", "types",
        "name", "names", "info", "true", "false", "none", "null",
        "callable", "instance", "class", "method", "function", "func",
        "var", "vars", "init", "main", "self", "cls", "obj", "key", "keys",
        "default", "defaults", "opt", "opts", "option", "props", "react",
        "tsx", "page", "view", "sentry", "finance", "backend", "frontend",
        "json", "html", "yaml", "api", "fastapi", "pydantic", "model",
        "schema", "yes", "see", "section", "above", "below", "phase",
        "task", "todo", "wip", "node", "edge", "step", "test", "tests",
    }
    TOK_RE = re.compile(r"[a-z][a-z0-9]+")
    labels: dict[int, str] = {}
    for cid, members in communities.items():
        bag: Counter[str] = Counter()
        for nid in members:
            label = G.nodes[nid].get("label", nid)
            for tok in TOK_RE.findall(str(label).lower()):
                if len(tok) >= 4 and tok not in STOP:
                    bag[tok] += 1
        top = [t for t, _ in bag.most_common(3)]
        labels[cid] = " / ".join(top) if top else f"Community {cid}"

    questions = suggest_questions(G, communities, labels)
    tokens = {"input": 0, "output": 0}
    report = generate(
        G, communities, cohesion, labels, gods, surprises, detection, tokens,
        str(PROJECT_ROOT), suggested_questions=questions,
    )
    (out_dir / "GRAPH_REPORT.md").write_text(report, encoding="utf-8")
    to_json(G, communities, str(out_dir / "graph.json"))
    log(f"[html] rendering {G.number_of_nodes()} nodes")
    to_html(G, communities, str(out_dir / "graph.html"), community_labels=labels)


def _write_readme(out_dir: Path, head_sha: str, last_sha: str, plan: Plan, mode: str) -> None:
    short_head = head_sha[:8] if head_sha else "(unknown)"
    short_last = last_sha[:8] if last_sha else "(bootstrap)"
    body = (
        f"# graphify rolling refresh\n\n"
        f"This folder is auto-refreshed by `tools/graphify/refresh_delta.py` "
        f"(scheduled by Windows Task Scheduler at 3am every other day, or "
        f"triggered manually via `/refresh-graph`). Periodic full audits "
        f"continue to land in dated `graphify-YYYY-MM-DD/` folders.\n\n"
        f"- Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n"
        f"- Mode: `{mode}`\n"
        f"- HEAD at refresh: `{short_head}`\n"
        f"- Previous refresh SHA: `{short_last}`\n"
        f"- Code files re-extracted: {len(plan.code_files)}\n"
        f"- Doc files re-extracted: {len(plan.semantic_files)}\n"
        f"- Files dropped (deleted/renamed): {len(plan.deleted_files)}\n"
        f"\n"
        f"Run `python tools/graphify/query_local.py quality "
        f"--graph docs/audits/graphify-current/graph.json` for shape stats.\n"
    )
    (out_dir / "README.md").write_text(body, encoding="utf-8")


# -------- detection payload --------

def _build_detection_payload() -> dict[str, Any]:
    from graphify.detect import (
        CODE_EXTENSIONS, DOC_EXTENSIONS, _is_sensitive as gf_sensitive,
    )
    code: list[str] = []
    docs: list[str] = []
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        if SKIP_DIR_PATTERN.search(rel) or _is_excluded(rel):
            continue
        try:
            if gf_sensitive(path):
                continue
        except Exception:
            pass
        ext = path.suffix.lower()
        if ext in CODE_EXTENSIONS:
            code.append(str(path))
        elif ext in DOC_EXTENSIONS or ext in SEMANTIC_EXTS:
            docs.append(str(path))
    return {
        "total_files": len(code) + len(docs),
        "total_words": 0,
        "files": {"code": code, "document": docs, "paper": []},
        "skipped_sensitive": [],
        "needs_graph": True,
        "warning": None,
    }


# -------- helpers --------

def _abs_to_relset(paths: list[Path]) -> set[str]:
    out: set[str] = set()
    for p in paths:
        try:
            out.add(p.resolve().relative_to(PROJECT_ROOT).as_posix())
        except ValueError:
            out.add(p.as_posix())
    return out


def _stage_outputs(out_dir: Path, log) -> None:
    if not out_dir.is_relative_to(PROJECT_ROOT):
        return
    rel_out = out_dir.relative_to(PROJECT_ROOT).as_posix()
    rel_state = STATE_PATH.relative_to(PROJECT_ROOT).as_posix()
    try:
        _git("add", rel_out, rel_state)
        log(f"[git] staged {rel_out} and {rel_state}")
    except subprocess.CalledProcessError as exc:
        log(f"[git] staging failed: {exc.stderr or exc}")


def _finalize_with(
    head_sha: str,
    last_sha: str,
    plan: Plan,
    ast: dict[str, Any],
    semantic: dict[str, Any],
    out_dir: Path,
    no_commit: bool,
    mode: str,
    log,
) -> None:
    invalidated_rel = _abs_to_relset(plan.code_files + plan.semantic_files)
    deleted_rel = set(plan.deleted_files)
    extraction = _merge(
        previous_graph_path=_previous_graph_path(),
        ast=ast, semantic=semantic,
        changed_files_rel=invalidated_rel,
        deleted_files_rel=deleted_rel,
        log=log,
    )
    detection = _build_detection_payload()
    log(f"[render] writing snapshot to {out_dir.relative_to(PROJECT_ROOT)}")
    _rebuild_outputs(extraction, out_dir, detection, log=log)
    _write_readme(out_dir, head_sha, last_sha, plan, mode)
    _write_state(head_sha, mode=mode)
    log(f"[state] last_sha={head_sha[:8]}, mode={mode}")
    if not no_commit:
        _stage_outputs(out_dir, log)


def _save_plan(work_dir: Path, plan: Plan) -> None:
    payload = {
        "schema": 1,
        "head_sha": plan.head_sha,
        "last_sha": plan.last_sha,
        "code_files": [str(p) for p in plan.code_files],
        "semantic_files": [str(p) for p in plan.semantic_files],
        "deleted_files": list(plan.deleted_files),
        "ignored_files": list(plan.ignored_files),
    }
    (work_dir / "plan.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_plan(work_dir: Path) -> Plan:
    payload = json.loads((work_dir / "plan.json").read_text(encoding="utf-8"))
    return Plan(
        last_sha=payload.get("last_sha", ""),
        head_sha=payload.get("head_sha", ""),
        code_files=[Path(p) for p in payload.get("code_files", [])],
        semantic_files=[Path(p) for p in payload.get("semantic_files", [])],
        deleted_files=list(payload.get("deleted_files", [])),
        ignored_files=list(payload.get("ignored_files", [])),
    )


def _save_ast(work_dir: Path, ast: dict[str, Any]) -> None:
    (work_dir / "ast.json").write_text(json.dumps(ast), encoding="utf-8")


def _load_ast(work_dir: Path) -> dict[str, Any]:
    return json.loads((work_dir / "ast.json").read_text(encoding="utf-8"))


def _write_manifest(work_dir: Path, plan: Plan, chunks: list[list[Path]], no_commit: bool, out_dir: Path) -> dict[str, Any]:
    chunk_entries: list[dict[str, Any]] = []
    for i, files in enumerate(chunks, 1):
        rel_files = [p.resolve().relative_to(PROJECT_ROOT).as_posix() for p in files]
        chunk_input = {
            "chunk_num": i,
            "total_chunks": len(chunks),
            "files": rel_files,
            "output_path": str((work_dir / f"chunk_{i:02d}_result.json").resolve()),
        }
        in_path = work_dir / f"chunk_{i:02d}.json"
        in_path.write_text(json.dumps(chunk_input, indent=2), encoding="utf-8")
        chunk_entries.append({
            "chunk_num": i,
            "input_path": str(in_path.resolve()),
            "output_path": chunk_input["output_path"],
            "file_count": len(rel_files),
        })

    manifest = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_root": str(PROJECT_ROOT),
        "head_sha": plan.head_sha,
        "last_sha": plan.last_sha,
        "out_dir": str(out_dir.resolve()),
        "no_commit": no_commit,
        "code_files": [str(p) for p in plan.code_files],
        "semantic_files": [str(p) for p in plan.semantic_files],
        "deleted_files": list(plan.deleted_files),
        "total_chunks": len(chunks),
        "chunks": chunk_entries,
    }
    (work_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _read_manifest(work_dir: Path) -> dict[str, Any]:
    return json.loads((work_dir / "manifest.json").read_text(encoding="utf-8"))


def _collect_chunk_results(manifest: dict[str, Any], log) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    hyperedges: list[dict[str, Any]] = []
    missing: list[int] = []
    for entry in manifest.get("chunks", []):
        out_path = Path(entry["output_path"])
        if not out_path.exists():
            missing.append(entry["chunk_num"])
            continue
        try:
            data = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception as exc:
            log(f"[finalize] chunk {entry['chunk_num']} unreadable: {exc}")
            missing.append(entry["chunk_num"])
            continue
        nodes.extend(data.get("nodes", []) or [])
        edges.extend(data.get("edges", []) or [])
        hyperedges.extend(data.get("hyperedges", []) or [])
    if missing:
        log(f"[finalize] missing chunk results: {missing}")
    return {"nodes": nodes, "edges": edges, "hyperedges": hyperedges}


# -------- main --------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="Classify diff and print the plan; write nothing.")
    mode.add_argument("--code-only", action="store_true",
                      help="AST-only end-to-end refresh. No agents needed.")
    mode.add_argument("--plan-only", action="store_true",
                      help="AST + manifest. Host then dispatches Sonnet agents per chunk.")
    mode.add_argument("--finalize", action="store_true",
                      help="Read manifest + chunk results from --work-dir, merge, write snapshot.")
    parser.add_argument("--no-commit", action="store_true",
                        help="Do not stage the refreshed snapshot. Used by hooks.")
    parser.add_argument("--since", default=None,
                        help="Override the recorded last-refresh SHA.")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="Skip the clean-tree guard. Use with care.")
    parser.add_argument("--out-dir", default=None,
                        help="Override the output snapshot dir (default docs/audits/graphify-current).")
    parser.add_argument("--work-dir", default=None,
                        help=f"Manifest / chunk cache dir (default {DEFAULT_WORK_DIR}).")
    parser.add_argument("--max-doc-files", type=int, default=50,
                        help="Cost guard: refuse if more docs changed (default 50). Applies to plan-only.")
    args = parser.parse_args(argv)

    def log(msg: str) -> None:
        print(msg, flush=True)

    out_dir = Path(args.out_dir).resolve() if args.out_dir else CURRENT_DIR
    work_dir = Path(args.work_dir).resolve() if args.work_dir else DEFAULT_WORK_DIR

    # ---- finalize: read manifest, no clean-tree guard (host already cleared it).
    if args.finalize:
        try:
            manifest = _read_manifest(work_dir)
        except FileNotFoundError:
            log(f"[error] no manifest at {work_dir / 'manifest.json'}; run --plan-only first")
            return 2
        plan = _load_plan(work_dir)
        plan.last_sha = manifest["last_sha"]
        plan.head_sha = manifest["head_sha"]
        ast = _load_ast(work_dir)
        semantic = _collect_chunk_results(manifest, log=log)
        log(f"[finalize] {len(semantic['nodes'])} sem-nodes, {len(semantic['edges'])} sem-edges, "
            f"{len(semantic['hyperedges'])} sem-hyperedges from {manifest['total_chunks']} chunks")
        # Honor manifest's no_commit unless overridden by current invocation.
        no_commit = args.no_commit or manifest.get("no_commit", False)
        out_dir = Path(manifest.get("out_dir", str(out_dir)))
        _finalize_with(
            head_sha=plan.head_sha, last_sha=plan.last_sha, plan=plan,
            ast=ast, semantic=semantic, out_dir=out_dir,
            no_commit=no_commit, mode="delta", log=log,
        )
        return 0

    # All other modes need a clean tree.
    if not args.allow_dirty and not _git_is_clean():
        log("[error] working tree is dirty; commit/stash first or pass --allow-dirty")
        return 2

    head = _git_head()
    state = _load_state()
    last_sha = _resolve_since(args.since, state)
    if not last_sha:
        last_sha = _bootstrap_last_sha(log)
    if not last_sha:
        log("[error] no last_sha and no dated audit snapshot to bootstrap from; pass --since <sha>")
        return 2

    if last_sha == head:
        log(f"[done] no commits since {last_sha[:8]}; nothing to refresh")
        return 1

    rows = _git_changed_files(last_sha, head)
    plan = _classify(rows)
    plan.last_sha = last_sha
    plan.head_sha = head
    log(f"[plan] {last_sha[:8]}..{head[:8]}: "
        f"{len(plan.code_files)} code, {len(plan.semantic_files)} semantic, "
        f"{len(plan.deleted_files)} deleted, {len(plan.ignored_files)} ignored")

    if plan.empty:
        log(f"[done] no eligible files changed in {last_sha[:8]}..{head[:8]}")
        return 1

    if args.dry_run:
        log("[dry-run] would refresh:")
        for p in plan.code_files:
            log(f"  ast      {p.relative_to(PROJECT_ROOT).as_posix()}")
        for p in plan.semantic_files:
            log(f"  semantic {p.relative_to(PROJECT_ROOT).as_posix()}")
        for rel in plan.deleted_files:
            log(f"  deleted  {rel}")
        log("[dry-run] no writes; exiting")
        return 0

    # AST is always the first wet step.
    ast_cache = work_dir / "ast-cache"
    ast = _run_ast(plan.code_files, ast_cache, log=log)

    # ---- code-only: skip semantic chunks even if they exist.
    if args.code_only:
        if plan.semantic_files:
            log(f"[sem] --code-only: skipping {len(plan.semantic_files)} doc files")
        _finalize_with(
            head_sha=head, last_sha=last_sha, plan=plan,
            ast=ast, semantic={"nodes": [], "edges": [], "hyperedges": []},
            out_dir=out_dir, no_commit=args.no_commit, mode="code-only", log=log,
        )
        return 0

    # ---- plan-only: write manifest, exit 0 if host needs to dispatch.
    if args.plan_only:
        if not plan.semantic_files:
            log("[plan-only] no doc files; finalizing as code-only in place")
            _finalize_with(
                head_sha=head, last_sha=last_sha, plan=plan,
                ast=ast, semantic={"nodes": [], "edges": [], "hyperedges": []},
                out_dir=out_dir, no_commit=args.no_commit, mode="code-only", log=log,
            )
            return 1  # signal "no manifest, no host dispatch needed"

        if len(plan.semantic_files) > args.max_doc_files:
            log(f"[error] {len(plan.semantic_files)} doc files changed (cap {args.max_doc_files}); "
                "kick a full rebuild instead of a delta refresh")
            return 2

        work_dir.mkdir(parents=True, exist_ok=True)
        # Wipe previous chunk results so stale outputs don't get re-merged.
        for old in work_dir.glob("chunk_*"):
            try:
                old.unlink()
            except OSError:
                pass

        _save_plan(work_dir, plan)
        _save_ast(work_dir, ast)

        chunks = _build_chunks(plan.semantic_files, chunk_size=CHUNK_SIZE_DEFAULT)
        manifest = _write_manifest(work_dir, plan, chunks, args.no_commit, out_dir)
        log(f"[manifest] {manifest['total_chunks']} chunk(s) ready at {work_dir}")
        for entry in manifest["chunks"]:
            log(f"  chunk {entry['chunk_num']:02d}: {entry['file_count']} files -> {entry['output_path']}")
        log("[plan-only] manifest ready; host should dispatch agents and then run --finalize")
        return 0

    # No mode picked: tell the user how this script is used now.
    log("[error] specify one of: --dry-run, --code-only, --plan-only, --finalize")
    log("[error] for semantic refreshes, use the /refresh-graph slash command "
        "or run plan-only + dispatch + --finalize manually.")
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"[error] git command failed: {exc}", file=sys.stderr)
        if exc.stderr:
            print(exc.stderr, file=sys.stderr)
        raise SystemExit(2)
