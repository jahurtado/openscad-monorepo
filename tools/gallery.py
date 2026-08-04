#!/usr/bin/env python3
"""
A live catalogue/viewer of the repo's projects — served on a port.

A "browser of the parts": ONE card per project, each with a client-rendered 3D
thumbnail and a short summary pulled from its docs/design.md. Click a project
for a detail view with ALL its printable pieces in 3D, its dimension drawings,
and its rendered design documentation.

STLs are rendered ON DEMAND via the shared pipeline (the SAME throwaway
`use <main>; <piece>();` build.py uses — never the raw binary by hand) and
cached; the cache is invalidated by the mtime of the project's .scad (+ lib/ +
components/), so editing a piece and reloading re-renders it live.

Usage:
    uv run tools/gallery.py                 # serve on http://127.0.0.1:8000
    uv run tools/gallery.py --port 9000
    uv run tools/gallery.py --fn 64         # viewer render quality (default 48)
    uv run tools/gallery.py --open          # serve AND open a browser
    uv run tools/gallery.py --export g.html # instead of serving: write ONE
                                            # self-contained HTML (all inlined)
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from _common import (build_dir, discover_modules, locate_openscad, render_module,
                     repo_root)

ROOT = repo_root()
UI_LANG = "en"   # initial UI language; --lang overrides ('auto' = follow the browser)


# ---------- discovery ----------

def project_mains(only: str | None) -> list[Path]:
    if only:
        p = ROOT / "projects" / only / "main.scad"
        if not p.is_file():
            sys.exit(f"no such project: {only!r} (expected {p})")
        return [p]
    return sorted(p for p in ROOT.glob("projects/*/main.scad"))


def _read(p: Path) -> str | None:
    try:
        return p.read_text()
    except OSError:
        return None


def _title(design_md: Path, proj: str) -> str:
    """Project title: the `# ` heading of design.md (minus a trailing
    '— Documentación de diseño' / '— Design documentation'), else the dir
    name prettified."""
    t = _read(design_md)
    if t:
        m = re.search(r"^#\s+(.+?)\s*$", t, re.M)
        if m:
            return re.sub(r"\s*[—-]\s*(Documentaci.n de dise.o|Design documentation).*$",
                          "", m.group(1)).strip()
    return proj.replace("_", " ")


def _summary(design_md: Path) -> str:
    """A one-liner: the first prose paragraph of design.md's '## Qué es y
    propósito' / '## What it is and purpose' section (markdown stripped,
    truncated)."""
    t = _read(design_md)
    if not t:
        return ""
    m = re.search(r"##\s*(?:Qu[eé] es|What it is)[^\n]*\n+(.+?)(\n\s*\n|\n#)", t, re.S)
    body = m.group(1) if m else ""
    body = re.sub(r"\s+", " ", body).strip()
    body = re.sub(r"\*\*(.+?)\*\*", r"\1", body)
    body = re.sub(r"\*(.+?)\*", r"\1", body)
    body = re.sub(r"`(.+?)`", r"\1", body)
    body = re.sub(r"\[(.+?)\]\([^)]*\)", r"\1", body)
    return body[:220]


def project_entry(main_scad: Path) -> dict:
    d = main_scad.parent
    proj = d.name
    design = d / "docs" / "design.md"
    draw_dir = d / "drawings"
    drawings = sorted(f.name for f in draw_dir.glob("*.png")) if draw_dir.is_dir() else []
    return {
        "proj": proj,
        "title": _title(design, proj),
        "summary": _summary(design),
        "pieces": discover_modules(main_scad, r"_print"),
        "drawings": drawings,
        "hasDoc": design.is_file(),
    }


def full_catalogue(only: str | None) -> list[dict]:
    return [project_entry(m) for m in project_mains(only)]


# ---------- rendering + safe asset access ----------

def render_stl(openscad: str, proj: str, piece: str, fn: int) -> bytes | None:
    main_scad = ROOT / "projects" / proj / "main.scad"
    out_stl = build_dir(main_scad) / f"_gallery_{piece}.stl"
    render_module(openscad, main_scad, piece, out_stl, fn=fn)
    if not out_stl.is_file() or out_stl.stat().st_size == 0:
        return None
    return out_stl.read_bytes()


def drawing_bytes(proj: str, fname: str) -> bytes | None:
    """A drawing PNG, guarded against path traversal."""
    base = (ROOT / "projects" / proj / "drawings").resolve()
    target = (base / fname).resolve()
    if target.parent != base or target.suffix.lower() != ".png" or not target.is_file():
        return None
    return target.read_bytes()


def doc_text(proj: str) -> str | None:
    if "/" in proj or ".." in proj:
        return None
    p = ROOT / "projects" / proj / "docs" / "design.md"
    return _read(p)


def _dep_mtime(proj: str) -> float:
    latest = 0.0
    for root in (ROOT / "projects" / proj, ROOT / "lib", ROOT / "components"):
        for f in root.rglob("*.scad"):
            latest = max(latest, f.stat().st_mtime)
    return latest


# ---------- live server ----------

class GalleryServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, openscad, fn, only):
        super().__init__(addr, GalleryHandler)
        self.openscad = openscad
        self.fn = fn
        self.only = only
        self.cache: dict[tuple, tuple[float, bytes]] = {}
        self.lock = threading.Lock()

    def stl(self, proj: str, piece: str, fresh: bool) -> bytes | None:
        key = (proj, piece, self.fn)
        stamp = _dep_mtime(proj)
        with self.lock:
            hit = self.cache.get(key)
            if hit and not fresh and hit[0] >= stamp:
                return hit[1]
        data = render_stl(self.openscad, proj, piece, self.fn)
        if data is not None:
            with self.lock:
                self.cache[key] = (stamp, data)
        return data


class GalleryHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, ctype, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        if path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", build_html().encode())
        elif path == "/catalog":
            self._send(200, "application/json",
                       json.dumps(full_catalogue(self.server.only)).encode())
        elif path.startswith("/stl/"):
            try:
                _, _, proj, piece = path.split("/", 3)
            except ValueError:
                return self._send(404, "text/plain", b"bad stl path")
            fresh = parse_qs(u.query).get("fresh", ["0"])[0] == "1"
            data = self.server.stl(proj, piece, fresh)
            if data is None:
                return self._send(404, "text/plain", b"render failed")
            self._send(200, "model/stl", data)
        elif path.startswith("/drawing/"):
            proj, _, fname = path[len("/drawing/"):].partition("/")
            data = drawing_bytes(proj, fname)
            if data is None:
                return self._send(404, "text/plain", b"no drawing")
            self._send(200, "image/png", data)
        elif path.startswith("/doc/"):
            txt = doc_text(path[len("/doc/"):])
            if txt is None:
                return self._send(404, "text/plain", b"no doc")
            self._send(200, "text/markdown; charset=utf-8", txt.encode())
        else:
            self._send(404, "text/plain", b"not found")


def serve(openscad, port, fn, only, do_open):
    srv = GalleryServer(("127.0.0.1", port), openscad, fn, only)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    cat = full_catalogue(only)
    npieces = sum(len(e["pieces"]) for e in cat)
    print(f"gallery: {len(cat)} projects · {npieces} pieces · $fn={fn} · serving {url}")
    print("  (renders each piece on first view; edit a .scad and reload it to re-render)")
    print("  Ctrl-C to stop")
    if do_open:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


# ---------- static export (self-contained, offline) ----------

def export(openscad, out: Path, fn, only):
    cat = full_catalogue(only)
    emb: dict[str, str] = {}   # "proj/piece" -> stl base64
    drw: dict[str, str] = {}   # "proj/file"  -> data URL
    doc: dict[str, str] = {}   # "proj"       -> markdown text
    for e in cat:
        for piece in e["pieces"]:
            print(f"  {e['proj']} · {piece} … ", end="", flush=True)
            data = render_stl(openscad, e["proj"], piece, fn)
            if data is None:
                print("empty, skipped")
                continue
            emb[f"{e['proj']}/{piece}"] = base64.b64encode(data).decode("ascii")
            print(f"ok ({len(data)//1024} KB)")
        for f in e["drawings"]:
            b = drawing_bytes(e["proj"], f)
            if b:
                drw[f"{e['proj']}/{f}"] = "data:image/png;base64," + base64.b64encode(b).decode("ascii")
        if e["hasDoc"]:
            doc[e["proj"]] = doc_text(e["proj"]) or ""
    if not emb:
        sys.exit("no pieces rendered — nothing to export")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_html(cat, emb, drw, doc))
    kb = sum(len(v) for v in emb.values()) * 3 // 4 // 1024
    print(f"\nwrote {out}  ({len(cat)} projects, ~{kb} KB of mesh inlined)")


def build_html(catalog=None, emb=None, drw=None, doc=None) -> str:
    def j(x):
        return "null" if x is None else json.dumps(x, separators=(",", ":"))
    return (HTML_TEMPLATE
            .replace("/*__CATALOG__*/", j(catalog))
            .replace("/*__EMB__*/", j(emb))
            .replace("/*__DRW__*/", j(drw))
            .replace("/*__DOC__*/", j(doc))
            .replace("/*__LANG__*/", j(UI_LANG)))


# ---------- CLI ----------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", nargs="?", help="limit to one project (default: all)")
    ap.add_argument("--port", type=int, default=8000, help="serve port (default 8000)")
    ap.add_argument("--fn", type=int, default=48, help="viewer render quality (default 48)")
    ap.add_argument("--open", action="store_true", help="open a browser at the served URL")
    ap.add_argument("--export", type=Path, metavar="HTML",
                    help="don't serve: write ONE self-contained HTML with everything inlined")
    ap.add_argument("--lang", choices=("en", "es", "auto"), default="en",
                    help="UI language: en (default), es, or auto = follow the browser. "
                         "The in-page toggle overrides it and is remembered.")
    ap.add_argument("--openscad", help="path to the OpenSCAD binary")
    args = ap.parse_args()

    global UI_LANG
    UI_LANG = args.lang

    openscad = locate_openscad(args.openscad)
    if args.export:
        export(openscad, args.export, args.fn, args.project)
    else:
        serve(openscad, args.port, args.fn, args.project, args.open)


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Parts catalogue</title>
<style>
  :root { color-scheme: dark; --accent:#5b9dff; --accent2:#7cc4ff;
    --bg:#111318; --panel:#171a20; --card:#1b1f26; --card-h:#202632; --line:#2a2f3a;
    --text:#e7eaf0; --muted:#8b94a4; --grid:rgba(160,190,255,.05); }
  * { box-sizing: border-box; }
  html, body { margin: 0; min-height: 100%; background: var(--bg); color: var(--text);
    font: 14px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
  .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  /* top bar */
  header { position: sticky; top: 0; z-index: 10; display: flex; align-items: center;
    gap: 18px; height: 60px; padding: 0 24px; background: rgba(19,21,26,.9);
    backdrop-filter: blur(10px); border-bottom: 1px solid var(--line); }
  .brand { display: flex; align-items: baseline; gap: 10px; }
  .brand b { font-size: 16px; font-weight: 700; letter-spacing: .01em; }
  .brand .sub { font-family: ui-monospace, Menlo, monospace; font-size: 12px; color: var(--accent); }
  .search { flex: 1; max-width: 380px; }
  .search input { width: 100%; height: 38px; padding: 0 14px; border-radius: 9px;
    background: #0d0f13; border: 1px solid var(--line); color: var(--text); font: inherit; outline: none; }
  .search input:focus { border-color: var(--accent); }
  .count { margin-left: auto; color: var(--muted); font-size: 13px; white-space: nowrap; }
  .langbtn { font: inherit; font-size: 12px; font-weight: 600; color: var(--muted); background: #12151b;
    border: 1px solid var(--line); border-radius: 7px; padding: 6px 11px; cursor: pointer; }
  .langbtn:hover { color: var(--text); border-color: var(--accent); }
  /* grid of PROJECT cards */
  main { padding: 26px 24px 70px; max-width: 1500px; margin: 0 auto; }
  .grid { display: grid; gap: 22px; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: 12px;
    overflow: hidden; cursor: pointer; display: flex; flex-direction: column;
    transition: transform .12s, border-color .12s, box-shadow .12s; }
  .card:hover { transform: translateY(-3px); border-color: var(--accent);
    box-shadow: 0 12px 30px rgba(0,0,0,.45); }
  .thumb { aspect-ratio: 5/4; position: relative; background-color: #10131a;
    background-image: linear-gradient(var(--grid) 1px, transparent 1px),
      linear-gradient(90deg, var(--grid) 1px, transparent 1px);
    background-size: 22px 22px; display: grid; place-items: center; }
  .thumb img { width: 100%; height: 100%; object-fit: contain; }
  .spin { width: 26px; height: 26px; border-radius: 50%; border: 3px solid #333a48;
    border-top-color: var(--accent); animation: sp .8s linear infinite; }
  @keyframes sp { to { transform: rotate(360deg); } }
  .body { padding: 13px 15px 15px; display: flex; flex-direction: column; gap: 5px; flex: 1; }
  .ptitle { font-weight: 650; font-size: 15px; }
  .pdir { font-size: 11.5px; color: var(--accent); }
  .psum { font-size: 12.5px; color: var(--muted); line-height: 1.45; margin-top: 2px;
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .pfoot { margin-top: auto; padding-top: 9px; display: flex; gap: 8px; flex-wrap: wrap; }
  .badge { font-size: 11px; color: var(--muted); background: #12151b; border: 1px solid var(--line);
    border-radius: 6px; padding: 2px 8px; }
  .none { color: var(--muted); padding: 60px; text-align: center; grid-column: 1/-1; }
  /* detail overlay (two columns) */
  .detail { position: fixed; inset: 0; z-index: 40; display: none; background: var(--bg); }
  .detail.open { display: flex; flex-direction: column; }
  .dbar { display: flex; align-items: center; gap: 14px; height: 60px; padding: 0 22px;
    border-bottom: 1px solid var(--line); background: var(--panel); flex: none; }
  .dbar h2 { margin: 0; font-size: 16px; font-weight: 700; }
  .dbar .dsub { font-size: 12px; color: var(--muted); }
  .iconbtn { font: inherit; font-size: 16px; color: var(--text); background: #1d222b;
    border: 1px solid var(--line); border-radius: 9px; width: 38px; height: 38px; cursor: pointer; }
  .iconbtn:hover { border-color: var(--accent); background: #232a35; }
  .dbody { flex: 1; display: flex; min-height: 0; }
  .dviewer { flex: 1.5; position: relative; min-width: 0;
    background-color: #0e1016;
    background-image: linear-gradient(var(--grid) 1px, transparent 1px),
      linear-gradient(90deg, var(--grid) 1px, transparent 1px); background-size: 26px 26px; }
  .dviewer canvas { display: block; width: 100%; height: 100%; }
  .pills { position: absolute; left: 16px; top: 14px; right: 16px; display: flex; gap: 8px; flex-wrap: wrap; }
  .pill { font: inherit; font-size: 12.5px; color: var(--muted); background: rgba(20,23,30,.82);
    border: 1px solid var(--line); border-radius: 999px; padding: 5px 13px; cursor: pointer;
    backdrop-filter: blur(4px); }
  .pill:hover { color: var(--text); }
  .pill.on { color: #fff; background: var(--accent); border-color: var(--accent); }
  .vhint { position: absolute; left: 16px; bottom: 12px; color: var(--muted); font-size: 12px; pointer-events: none; }
  .vreload { position: absolute; right: 16px; bottom: 12px; }
  .dsplit { width: 7px; flex: none; cursor: col-resize; background: var(--line);
    position: relative; touch-action: none; }
  .dsplit::before { content: ""; position: absolute; inset: 0 -4px; }   /* fatter hit area */
  .dsplit:hover, .dsplit.drag { background: var(--accent); }
  .dinfo { width: 420px; min-width: 300px; max-width: 760px; flex: none;
    border-left: 1px solid var(--line); display: flex; flex-direction: column; background: var(--panel); }
  .tabs { display: flex; gap: 4px; padding: 12px 16px 0; border-bottom: 1px solid var(--line); }
  .tab { font: inherit; font-size: 13px; color: var(--muted); background: none; border: none;
    padding: 8px 12px; cursor: pointer; border-bottom: 2px solid transparent; }
  .tab.on { color: var(--text); border-bottom-color: var(--accent); }
  .pane { flex: 1; overflow-y: auto; padding: 18px 20px; }
  .pane img { max-width: 100%; border-radius: 8px; border: 1px solid var(--line); background: #fff;
    margin-bottom: 14px; cursor: zoom-in; transition: border-color .12s; }
  .pane img:hover { border-color: var(--accent); }
  /* lightbox for enlarged drawings */
  .lightbox { position: fixed; inset: 0; z-index: 60; display: none; place-items: center;
    background: rgba(6,7,9,.9); backdrop-filter: blur(4px); padding: 26px; overflow: hidden; }
  .lightbox.open { display: grid; }
  .lightbox img { max-width: 96vw; max-height: 90vh; border-radius: 8px; background: #fff;
    box-shadow: 0 24px 70px rgba(0,0,0,.6); transform-origin: center center; cursor: grab;
    will-change: transform; user-select: none; -webkit-user-drag: none; }
  .lbtools { position: fixed; top: 16px; right: 16px; z-index: 2; display: flex; gap: 8px; }
  .lbtools button { width: 40px; height: 40px; font: inherit; font-size: 18px; color: var(--text);
    background: rgba(30,34,42,.92); border: 1px solid var(--line); border-radius: 9px; cursor: pointer; }
  .lbtools button:hover { border-color: var(--accent); background: rgba(42,48,58,.96); }
  .lbcap { position: fixed; bottom: 16px; left: 0; right: 0; text-align: center; color: var(--muted); font-size: 12px; }
  .pane .empty { color: var(--muted); text-align: center; padding: 40px 0; }
  /* rendered markdown */
  .md { font-size: 13.5px; line-height: 1.6; }
  .md h1,.md h2,.md h3,.md h4 { line-height: 1.3; margin: 18px 0 8px; }
  .md h1 { font-size: 18px; } .md h2 { font-size: 15px; color: var(--accent2); }
  .md h3 { font-size: 13.5px; } .md h4 { font-size: 13px; color: var(--muted); }
  .md p { margin: 8px 0; } .md ul,.md ol { margin: 8px 0; padding-left: 22px; }
  .md li { margin: 3px 0; } .md code { font-family: ui-monospace, Menlo, monospace; font-size: 12px;
    background: #0e1117; border: 1px solid var(--line); border-radius: 4px; padding: 1px 5px; }
  .md pre { background: #0e1117; border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px;
    overflow-x: auto; } .md pre code { border: none; padding: 0; background: none; }
  .md blockquote { margin: 10px 0; padding: 4px 14px; border-left: 3px solid var(--accent);
    color: var(--muted); } .md hr { border: none; border-top: 1px solid var(--line); margin: 16px 0; }
  .md a { color: var(--accent); } .md table { border-collapse: collapse; width: 100%; font-size: 12.5px; margin: 10px 0; }
  .md th,.md td { border: 1px solid var(--line); padding: 5px 8px; text-align: left; vertical-align: top; }
  .md th { background: #12151b; }
</style>
</head>
<body>
<header>
  <div class="brand"><b>Parts catalogue</b><span class="sub mono" id="scount">// …</span></div>
  <div class="search"><input id="q" type="search" placeholder="Search project…" autocomplete="off"></div>
  <div class="count" id="count"></div>
  <button class="langbtn" id="lang" title="">EN</button>
</header>
<main><div class="grid" id="grid"></div></main>

<div class="detail" id="detail">
  <div class="dbar">
    <button class="iconbtn" id="dback" title="Back">←</button>
    <div><h2 id="dtitle"></h2><div class="dsub mono" id="dsub"></div></div>
  </div>
  <div class="dbody">
    <div class="dviewer">
      <canvas id="view"></canvas>
      <div class="pills" id="pills"></div>
      <div class="vhint">drag: orbit · wheel: zoom · double-click: reframe</div>
      <button class="iconbtn vreload" id="vreload" title="Re-render (re-reads the .scad)">↻</button>
    </div>
    <div class="dsplit" id="dsplit" title="Drag to resize"></div>
    <div class="dinfo" id="dinfo">
      <div class="tabs">
        <button class="tab on" data-tab="planos">Drawings</button>
        <button class="tab" data-tab="diseno">Design</button>
      </div>
      <div class="pane" id="pane-planos"></div>
      <div class="pane" id="pane-diseno" hidden></div>
    </div>
  </div>
</div>

<div class="lightbox" id="lightbox">
  <div class="lbtools">
    <button id="lbout" title="Zoom out (−)">−</button>
    <button id="lbin" title="Zoom in (+)">+</button>
    <button id="lbreset" title="Fit to screen">⤢</button>
    <button id="lbclose" title="Close (Esc)">✕</button>
  </div>
  <img id="lbimg" alt="">
  <div class="lbcap mono" id="lbcap"></div>
</div>

<script>
let CATALOG=/*__CATALOG__*/, EMB=/*__EMB__*/, DRW=/*__DRW__*/, DOC=/*__DOC__*/;

/* ---------- i18n (EN/ES by browser, overridable) ---------- */
function lsGet(k){try{return localStorage.getItem(k);}catch(e){return null;}}
function lsSet(k,v){try{localStorage.setItem(k,v);}catch(e){}}
const I18N={
  en:{ title:'Parts catalogue', brand:'Parts catalogue', projects:'projects', pieces:'parts',
    piece:'part', drawings:'drawings', drawing:'drawing', doc:'doc', search:'Search project…',
    all:'All', planos:'Drawings', design:'Design', noPlanos:'No drawings.', noDoc:'No documentation.',
    loading:'loading…', rendering:'rendering…', noPieces:'no parts',
    hint:'drag: orbit · wheel: zoom · double-click: reframe', noProjects:'No projects.', error:'error',
    tipReload:'Re-render (re-reads the .scad)', tipBack:'Back', tipSplit:'Drag to resize',
    tipZoomOut:'Zoom out (−)', tipZoomIn:'Zoom in (+)', tipFit:'Fit to screen', tipClose:'Close (Esc)',
    langLabel:'ES', langTitle:'Ver en español' },
  es:{ title:'Catálogo de piezas', brand:'Catálogo de piezas', projects:'proyectos', pieces:'piezas',
    piece:'pieza', drawings:'planos', drawing:'plano', doc:'doc', search:'Buscar proyecto…',
    all:'Todas', planos:'Planos', design:'Diseño', noPlanos:'Sin planos.', noDoc:'Sin documentación.',
    loading:'cargando…', rendering:'renderizando…', noPieces:'sin piezas',
    hint:'arrastra: orbitar · rueda: zoom · doble clic: reencuadrar', noProjects:'No hay proyectos.', error:'error',
    tipReload:'Re-renderizar (relee el .scad)', tipBack:'Volver', tipSplit:'Arrastra para redimensionar',
    tipZoomOut:'Alejar (−)', tipZoomIn:'Acercar (+)', tipFit:'Ajustar a pantalla', tipClose:'Cerrar (Esc)',
    langLabel:'EN', langTitle:'View in English' },
};
const DEFLANG=/*__LANG__*/;
const LANG=(()=>{const s=lsGet('galLang');if(s==='es'||s==='en')return s;
  if(DEFLANG==='es'||DEFLANG==='en')return DEFLANG;          // forced with --lang
  return (navigator.language||'en').toLowerCase().startsWith('es')?'es':'en';})();
const T=I18N[LANG]||I18N.en;
function plural(n,one,many){return n+' '+(n===1?one:many);}
function applyStatic(){
  document.documentElement.lang=LANG;
  document.title=T.title;
  document.querySelector('.brand b').textContent=T.brand;
  document.getElementById('q').placeholder=T.search;
  document.querySelector('.tab[data-tab="planos"]').textContent=T.planos;
  document.querySelector('.tab[data-tab="diseno"]').textContent=T.design;
  document.querySelector('.vhint').textContent=T.hint;
  const tip=(id,k)=>{const el=document.getElementById(id);if(el)el.title=T[k];};
  tip('vreload','tipReload');tip('dback','tipBack');tip('dsplit','tipSplit');
  tip('lbout','tipZoomOut');tip('lbin','tipZoomIn');tip('lbreset','tipFit');tip('lbclose','tipClose');
  const lb=document.getElementById('lang');lb.textContent=T.langLabel;lb.title=T.langTitle;
  lb.onclick=()=>{lsSet('galLang',LANG==='es'?'en':'es');location.reload();};
}
applyStatic();

/* ---------- mat / stl ---------- */
function mul(a,b){const o=new Float32Array(16);for(let r=0;r<4;r++)for(let c=0;c<4;c++){let s=0;for(let k=0;k<4;k++)s+=a[k*4+r]*b[c*4+k];o[c*4+r]=s;}return o;}
function perspective(fovy,asp,n,f){const t=1/Math.tan(fovy/2);const o=new Float32Array(16);o[0]=t/asp;o[5]=t;o[10]=(f+n)/(n-f);o[11]=-1;o[14]=2*f*n/(n-f);return o;}
function sub(a,b){return[a[0]-b[0],a[1]-b[1],a[2]-b[2]];}
function cross(a,b){return[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];}
function nrm3(v){const l=Math.hypot(v[0],v[1],v[2])||1;return[v[0]/l,v[1]/l,v[2]/l];}
function lookAt(eye,ctr,up){const z=nrm3(sub(eye,ctr)),x=nrm3(cross(up,z)),y=cross(z,x);
  return new Float32Array([x[0],y[0],z[0],0,x[1],y[1],z[1],0,x[2],y[2],z[2],0,
    -(x[0]*eye[0]+x[1]*eye[1]+x[2]*eye[2]),-(y[0]*eye[0]+y[1]*eye[1]+y[2]*eye[2]),-(z[0]*eye[0]+z[1]*eye[1]+z[2]*eye[2]),1]);}
function mat3of(m){return new Float32Array([m[0],m[1],m[2],m[4],m[5],m[6],m[8],m[9],m[10]]);}
function b64buf(b64){const s=atob(b64),n=s.length,u=new Uint8Array(n);for(let i=0;i<n;i++)u[i]=s.charCodeAt(i);return u.buffer;}
function parseSTL(buf){const dv=new DataView(buf);
  if(buf.byteLength>=84){const n=dv.getUint32(80,true);if(84+n*50===buf.byteLength){
    const pos=new Float32Array(n*9);let o=84,p=0;for(let i=0;i<n;i++){o+=12;for(let j=0;j<9;j++){pos[p++]=dv.getFloat32(o,true);o+=4;}o+=2;}return pos;}}
  const txt=new TextDecoder().decode(new Uint8Array(buf)),m=txt.match(/vertex\s+(\S+)\s+(\S+)\s+(\S+)/g)||[];
  const pos=new Float32Array(m.length*3);let p=0;for(const v of m){const t=v.trim().split(/\s+/);pos[p++]=+t[1];pos[p++]=+t[2];pos[p++]=+t[3];}return pos;}
function faceNormals(pos){const nr=new Float32Array(pos.length);for(let i=0;i<pos.length;i+=9){
  const ux=pos[i+3]-pos[i],uy=pos[i+4]-pos[i+1],uz=pos[i+5]-pos[i+2],vx=pos[i+6]-pos[i],vy=pos[i+7]-pos[i+1],vz=pos[i+8]-pos[i+2];
  let nx=uy*vz-uz*vy,ny=uz*vx-ux*vz,nz=ux*vy-uy*vx;const l=Math.hypot(nx,ny,nz)||1;nx/=l;ny/=l;nz/=l;
  for(let k=0;k<3;k++){nr[i+k*3]=nx;nr[i+k*3+1]=ny;nr[i+k*3+2]=nz;}}return nr;}
function bounds(pos){const mn=[1e9,1e9,1e9],mx=[-1e9,-1e9,-1e9];for(let i=0;i<pos.length;i+=3)for(let a=0;a<3;a++){const v=pos[i+a];if(v<mn[a])mn[a]=v;if(v>mx[a])mx[a]=v;}
  return{mn,mx,c:[(mn[0]+mx[0])/2,(mn[1]+mx[1])/2,(mn[2]+mx[2])/2],r:Math.max(1e-3,Math.hypot(mx[0]-mn[0],mx[1]-mn[1],mx[2]-mn[2])/2)};}

/* ---------- renderer (transparent bg over the CSS blueprint grid) ---------- */
const VS=`attribute vec3 aPos;attribute vec3 aNormal;uniform mat4 uMVP;uniform mat3 uN;varying vec3 vN;void main(){vN=uN*aNormal;gl_Position=uMVP*vec4(aPos,1.0);}`;
const FS=`precision mediump float;varying vec3 vN;uniform vec3 uColor;void main(){vec3 N=normalize(vN);
  float d=max(dot(N,normalize(vec3(0.35,0.45,0.82))),0.0);float d2=max(dot(N,normalize(vec3(-0.4,-0.2,0.3))),0.0);
  gl_FragColor=vec4(uColor*(0.32+0.72*d)+vec3(0.10)*d2,1.0);}`;
function Renderer(canvas,preserve){
  const gl=canvas.getContext('webgl',{antialias:true,alpha:true,premultipliedAlpha:false,preserveDrawingBuffer:!!preserve});
  function sh(t,s){const o=gl.createShader(t);gl.shaderSource(o,s);gl.compileShader(o);return o;}
  const prog=gl.createProgram();gl.attachShader(prog,sh(gl.VERTEX_SHADER,VS));gl.attachShader(prog,sh(gl.FRAGMENT_SHADER,FS));
  gl.linkProgram(prog);gl.useProgram(prog);
  const aPos=gl.getAttribLocation(prog,'aPos'),aN=gl.getAttribLocation(prog,'aNormal');
  const uMVP=gl.getUniformLocation(prog,'uMVP'),uN=gl.getUniformLocation(prog,'uN'),uColor=gl.getUniformLocation(prog,'uColor');
  const posBuf=gl.createBuffer(),nrmBuf=gl.createBuffer();gl.enable(gl.DEPTH_TEST);let cur=null;
  function setMesh(pos){const nr=faceNormals(pos),bb=bounds(pos);
    gl.bindBuffer(gl.ARRAY_BUFFER,posBuf);gl.bufferData(gl.ARRAY_BUFFER,pos,gl.STATIC_DRAW);
    gl.bindBuffer(gl.ARRAY_BUFFER,nrmBuf);gl.bufferData(gl.ARRAY_BUFFER,nr,gl.STATIC_DRAW);cur={n:pos.length/3,bb};return bb;}
  function draw(az,el,distF){
    if(canvas.clientWidth>0){const d=Math.min(devicePixelRatio||1,2);
      const w=Math.max(1,canvas.clientWidth*d|0),h=Math.max(1,canvas.clientHeight*d|0);
      if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}}
    gl.viewport(0,0,canvas.width,canvas.height);gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
    if(!cur)return;const bb=cur.bb,asp=canvas.width/canvas.height,fov=Math.PI/4;
    const dist=bb.r/Math.tan(fov/2)*1.9*distF,ce=Math.cos(el);
    const eye=[bb.c[0]+dist*ce*Math.cos(az),bb.c[1]+dist*ce*Math.sin(az),bb.c[2]+dist*Math.sin(el)];
    const view=lookAt(eye,bb.c,[0,0,1]),proj=perspective(fov,asp,bb.r*0.05,dist+bb.r*4);
    gl.uniformMatrix4fv(uMVP,false,mul(proj,view));gl.uniformMatrix3fv(uN,false,mat3of(view));gl.uniform3f(uColor,0.83,0.69,0.31);
    gl.bindBuffer(gl.ARRAY_BUFFER,posBuf);gl.enableVertexAttribArray(aPos);gl.vertexAttribPointer(aPos,3,gl.FLOAT,false,0,0);
    gl.bindBuffer(gl.ARRAY_BUFFER,nrmBuf);gl.enableVertexAttribArray(aN);gl.vertexAttribPointer(aN,3,gl.FLOAT,false,0,0);
    gl.drawArrays(gl.TRIANGLES,0,cur.n);}
  return {setMesh,draw,get cur(){return cur;}};
}
const TAZ=2.2, TEL=0.5;   // default iso: look at the +Y (room / countersink) side, not the flat back

/* ---------- data access (served ↔ static) ---------- */
const meshCache={};
async function meshOf(proj,piece,fresh){
  const key=proj+'/'+piece; if(meshCache[key]&&!fresh) return meshCache[key];
  let buf;
  if(EMB&&EMB[key]) buf=b64buf(EMB[key]);
  else { const r=await fetch(`/stl/${proj}/${piece}${fresh?'?fresh=1':''}`); if(!r.ok) throw new Error(await r.text()); buf=await r.arrayBuffer(); }
  return meshCache[key]=parseSTL(buf);
}
function drawingSrc(proj,file){ return (DRW&&DRW[proj+'/'+file]) || `/drawing/${proj}/${file}`; }
async function docOf(proj){ if(DOC) return DOC[proj]||''; const r=await fetch(`/doc/${proj}`); return r.ok?await r.text():''; }
function dimStr(bb){return `${(bb.mx[0]-bb.mn[0]).toFixed(1)} × ${(bb.mx[1]-bb.mn[1]).toFixed(1)} × ${(bb.mx[2]-bb.mn[2]).toFixed(1)} mm`;}
/* lay several piece meshes out in a build-plate grid, centred per cell, into one buffer */
function combine(list){
  if(list.length===1) return list[0];
  const bbs=list.map(bounds);
  const cellW=Math.max(...bbs.map(b=>b.mx[0]-b.mn[0]));
  const cellD=Math.max(...bbs.map(b=>b.mx[1]-b.mn[1]));
  const gap=0.18*Math.max(cellW,cellD), cols=Math.ceil(Math.sqrt(list.length));
  let total=0; for(const p of list) total+=p.length;
  const out=new Float32Array(total); let o=0;
  list.forEach((pos,k)=>{
    const b=bbs[k];
    const dx=(k%cols)*(cellW+gap)-(b.mn[0]+b.mx[0])/2;
    const dy=-Math.floor(k/cols)*(cellD+gap)-(b.mn[1]+b.mx[1])/2;
    for(let i=0;i<pos.length;i+=3){out[o++]=pos[i]+dx;out[o++]=pos[i+1]+dy;out[o++]=pos[i+2];}
  });
  return out;
}
async function meshesOf(proj,pieces,fresh){ return Promise.all(pieces.map(p=>meshOf(proj,p,fresh))); }

/* ---------- thumbnails (offscreen, transparent) ---------- */
const thumbCanvas=document.createElement('canvas');thumbCanvas.width=440;thumbCanvas.height=352;
const thumbR=Renderer(thumbCanvas,true);
async function makeThumb(proj,pieces){ const pos=combine(await meshesOf(proj,pieces)); thumbR.setMesh(pos); thumbR.draw(TAZ,TEL,1.0); return thumbCanvas.toDataURL('image/png'); }

/* ---------- markdown ---------- */
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function inl(s){return esc(s).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([\s\S]+?)\*\*/g,'<strong>$1</strong>')
  .replace(/(^|[^*])\*([^*\s][^*]*)\*/g,'$1<em>$2</em>').replace(/\[([^\]]+)\]\(([^)]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');}
function mdToHtml(md){const L=md.replace(/\r/g,'').split('\n');let h='',i=0;
  const stop=/^(#{1,4}\s|\s*[-*]\s|\s*\d+\.\s|>|\||```|-{3,}\s*$)/;
  const cbrk=/^(#{1,4}\s|>|```|-{3,}\s*$|\s*[-*]\s|\s*\d+\.\s)/;   // stops a list item's wrapped-line continuation
  while(i<L.length){let ln=L[i];
    if(/^```/.test(ln)){i++;let c='';while(i<L.length&&!/^```/.test(L[i])){c+=L[i]+'\n';i++;}i++;h+='<pre><code>'+esc(c)+'</code></pre>';continue;}
    let m;if(m=ln.match(/^(#{1,4})\s+(.+)$/)){const n=m[1].length;h+=`<h${n}>`+inl(m[2])+`</h${n}>`;i++;continue;}
    if(/^(-{3,}|\*{3,})\s*$/.test(ln)){h+='<hr>';i++;continue;}
    if(/^\s*[-*]\s+/.test(ln)){h+='<ul>';while(i<L.length&&/^\s*[-*]\s+/.test(L[i])){let it=L[i].replace(/^\s*[-*]\s+/,'');i++;while(i<L.length&&L[i].trim()!==''&&!cbrk.test(L[i])){it+=' '+L[i].trim();i++;}h+='<li>'+inl(it)+'</li>';}h+='</ul>';continue;}
    if(/^\s*\d+\.\s+/.test(ln)){h+='<ol>';while(i<L.length&&/^\s*\d+\.\s+/.test(L[i])){let it=L[i].replace(/^\s*\d+\.\s+/,'');i++;while(i<L.length&&L[i].trim()!==''&&!cbrk.test(L[i])){it+=' '+L[i].trim();i++;}h+='<li>'+inl(it)+'</li>';}h+='</ol>';continue;}
    if(/^\s*>\s?/.test(ln)){h+='<blockquote>';while(i<L.length&&/^\s*>\s?/.test(L[i])){h+=inl(L[i].replace(/^\s*>\s?/,''))+' ';i++;}h+='</blockquote>';continue;}
    if(/\|/.test(ln)&&i+1<L.length&&/^\s*\|?[\s:|-]+\|?\s*$/.test(L[i+1])){
      const cells=s=>s.split('|').map(x=>x.trim()).filter((x,k,a)=>!((k===0||k===a.length-1)&&x===''));
      const head=cells(ln);i+=2;let rows='';
      while(i<L.length&&/\|/.test(L[i])&&L[i].trim()!==''){rows+='<tr>'+cells(L[i]).map(c=>'<td>'+inl(c)+'</td>').join('')+'</tr>';i++;}
      h+='<table><thead><tr>'+head.map(x=>'<th>'+inl(x)+'</th>').join('')+'</tr></thead><tbody>'+rows+'</tbody></table>';continue;}
    if(ln.trim()===''){i++;continue;}
    let p=ln;i++;while(i<L.length&&L[i].trim()!==''&&!stop.test(L[i])){p+=' '+L[i];i++;}h+='<p>'+inl(p)+'</p>';}
  return h;}

/* ---------- grid of project cards ---------- */
const grid=document.getElementById('grid');let cards=[];
function makeCard(e){
  const el=document.createElement('div');el.className='card';
  el.innerHTML=`<div class="thumb"><div class="spin"></div></div>
    <div class="body"><div class="ptitle">${esc(e.title)}</div>
    <div class="pdir mono">projects/${e.proj}</div>
    <div class="psum">${esc(e.summary||'')}</div>
    <div class="pfoot"><span class="badge">${plural(e.pieces.length,T.piece,T.pieces)}</span>
    ${e.drawings.length?`<span class="badge">${plural(e.drawings.length,T.drawing,T.drawings)}</span>`:''}
    ${e.hasDoc?`<span class="badge">${T.doc}</span>`:''}</div></div>`;
  el.onclick=()=>openDetail(e);
  grid.appendChild(el);
  cards.push({el,key:(e.proj+' '+e.title+' '+(e.summary||'')).toLowerCase()});
  return el;
}
async function fillThumb(e){
  const t=e._el.querySelector('.thumb'); if(!e.pieces.length){t.innerHTML=`<div class="badge">${T.noPieces}</div>`;return;}
  try{ const url=await makeThumb(e.proj,e.pieces); t.innerHTML=`<img alt="${e.proj}" src="${url}">`; }
  catch(err){ t.innerHTML=`<div style="color:#d77;font-size:12px;padding:10px;text-align:center">${err.message}</div>`; }
}

/* ---------- detail: viewer + drawings + doc ---------- */
const detail=document.getElementById('detail'), viewCanvas=document.getElementById('view'), viewR=Renderer(viewCanvas,false);
let mAz=TAZ,mEl=TEL,mDist=1.0,mDrag=null,curProj=null,curPiece=null,curPieces=[];
function drawView(){viewR.draw(mAz,mEl,mDist);}
async function loadPiece(proj,piece,fresh){   // piece === '*' -> all pieces laid out together
  curProj=proj;curPiece=piece;
  document.querySelectorAll('#pills .pill').forEach(p=>p.classList.toggle('on',p.dataset.piece===piece));
  document.getElementById('dsub').textContent='projects/'+proj+' · '+T.rendering;
  try{
    let pos,label;
    if(piece==='*'){ pos=combine(await meshesOf(proj,curPieces,fresh)); label=`${curPieces.length} ${T.pieces}`; }
    else { pos=await meshOf(proj,piece,fresh); label=piece.replace(/_print$/,''); }
    viewR.setMesh(pos); mAz=TAZ;mEl=TEL;mDist=1.0; drawView();
    document.getElementById('dsub').textContent=`projects/${proj} · ${label} · ${dimStr(viewR.cur.bb)} · ${(pos.length/9|0).toLocaleString()} △`;
  }catch(e){ document.getElementById('dsub').textContent='projects/'+proj+' · '+T.error+': '+e.message; }
}
async function openDetail(e){
  document.getElementById('dtitle').textContent=e.title;
  const pills=document.getElementById('pills');pills.innerHTML='';curPieces=e.pieces;
  if(e.pieces.length>1){const b=document.createElement('button');b.className='pill';b.dataset.piece='*';
    b.textContent=`${T.all} (${e.pieces.length})`;b.onclick=()=>loadPiece(e.proj,'*');pills.appendChild(b);}
  e.pieces.forEach(pc=>{const b=document.createElement('button');b.className='pill';b.dataset.piece=pc;
    b.textContent=pc.replace(/_print$/,'');b.onclick=()=>loadPiece(e.proj,pc);pills.appendChild(b);});
  // drawings pane
  const pp=document.getElementById('pane-planos');
  pp.innerHTML=e.drawings.length?e.drawings.map(f=>`<img src="${drawingSrc(e.proj,f)}" alt="${f}">`).join(''):`<div class="empty">${T.noPlanos}</div>`;
  // design doc (lazy)
  const pd=document.getElementById('pane-diseno');pd.innerHTML=`<div class="empty">${T.loading}</div>`;
  setTab('planos');
  detail.classList.add('open');
  if(e.pieces.length>1) loadPiece(e.proj,'*'); else if(e.pieces.length) loadPiece(e.proj,e.pieces[0]);
  else document.getElementById('dsub').textContent='projects/'+e.proj+' · '+T.noPieces;
  docOf(e.proj).then(t=>{pd.innerHTML=t?`<div class="md">${mdToHtml(t)}</div>`:`<div class="empty">${T.noDoc}</div>`;})
    .catch(()=>{pd.innerHTML=`<div class="empty">${T.noDoc}</div>`;});
}
function closeDetail(){detail.classList.remove('open');curProj=null;}
function setTab(name){document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('on',t.dataset.tab===name));
  document.getElementById('pane-planos').hidden=name!=='planos';document.getElementById('pane-diseno').hidden=name!=='diseno';}
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>setTab(t.dataset.tab));
document.getElementById('dback').onclick=closeDetail;
addEventListener('keydown',e=>{if(e.key!=='Escape')return;
  const lb=document.getElementById('lightbox');
  if(lb.classList.contains('open'))lb.classList.remove('open');
  else if(detail.classList.contains('open'))closeDetail();});
document.getElementById('vreload').onclick=async()=>{ if(curProj)await loadPiece(curProj,curPiece,true); };
viewCanvas.addEventListener('pointerdown',e=>{mDrag={x:e.clientX,y:e.clientY};viewCanvas.setPointerCapture(e.pointerId);});
viewCanvas.addEventListener('pointermove',e=>{if(!mDrag)return;mAz-=(e.clientX-mDrag.x)*0.01;mEl+=(e.clientY-mDrag.y)*0.01;
  mEl=Math.max(-1.5,Math.min(1.5,mEl));mDrag={x:e.clientX,y:e.clientY};drawView();});
addEventListener('pointerup',()=>mDrag=null);
viewCanvas.addEventListener('wheel',e=>{e.preventDefault();mDist*=Math.exp(e.deltaY*0.001);mDist=Math.max(0.2,Math.min(6,mDist));drawView();},{passive:false});
viewCanvas.addEventListener('dblclick',()=>{mAz=TAZ;mEl=TEL;mDist=1.0;drawView();});
addEventListener('resize',()=>{if(detail.classList.contains('open'))drawView();});

/* ---------- resizable info panel (drag the divider) ---------- */
const dinfo=document.getElementById('dinfo'),dsplit=document.getElementById('dsplit');
{const sw=parseInt(lsGet('galInfoW'));if(sw>=300&&sw<=760)dinfo.style.width=sw+'px';}
let sDrag=false;
dsplit.addEventListener('pointerdown',e=>{sDrag=true;dsplit.classList.add('drag');dsplit.setPointerCapture(e.pointerId);e.preventDefault();});
dsplit.addEventListener('pointermove',e=>{if(!sDrag)return;const w=Math.min(760,Math.max(300,innerWidth-e.clientX));
  dinfo.style.width=w+'px';lsSet('galInfoW',w);drawView();});
dsplit.addEventListener('pointerup',()=>{sDrag=false;dsplit.classList.remove('drag');});

/* ---------- lightbox: click a drawing to enlarge ---------- */
const lightbox=document.getElementById('lightbox'),lbimg=document.getElementById('lbimg'),lbcap=document.getElementById('lbcap');
let lbS=1,lbX=0,lbY=0,lbDrag=null;
function lbApply(){lbimg.style.transform=`translate(${lbX}px,${lbY}px) scale(${lbS})`;}
function lbReset(){lbS=1;lbX=0;lbY=0;lbApply();}
function lbClose(){lightbox.classList.remove('open');}
function lbOpen(src,cap){lbimg.src=src;lbcap.textContent=cap||'';lbReset();lightbox.classList.add('open');}
function lbZoom(f,cx,cy){                       // zoom toward (cx,cy), keeping that point fixed
  const vx=innerWidth/2,vy=innerHeight/2,s0=lbS,s1=Math.min(12,Math.max(0.5,s0*f));
  const lx=(cx-vx-lbX)/s0, ly=(cy-vy-lbY)/s0;
  lbX=cx-vx-lx*s1; lbY=cy-vy-ly*s1; lbS=s1; lbApply();
}
document.getElementById('pane-planos').addEventListener('click',e=>{if(e.target.tagName==='IMG')lbOpen(e.target.src,e.target.alt);});
lightbox.addEventListener('click',e=>{if(e.target===lightbox)lbClose();});   // only the backdrop closes
lightbox.addEventListener('wheel',e=>{e.preventDefault();lbZoom(e.deltaY<0?1.15:1/1.15,e.clientX,e.clientY);},{passive:false});
lbimg.addEventListener('pointerdown',e=>{lbDrag={x:e.clientX,y:e.clientY};lbimg.setPointerCapture(e.pointerId);lbimg.style.cursor='grabbing';e.preventDefault();});
lbimg.addEventListener('pointermove',e=>{if(!lbDrag)return;lbX+=e.clientX-lbDrag.x;lbY+=e.clientY-lbDrag.y;lbDrag={x:e.clientX,y:e.clientY};lbApply();});
lbimg.addEventListener('pointerup',()=>{lbDrag=null;lbimg.style.cursor='grab';});
lbimg.addEventListener('dblclick',e=>{e.preventDefault();lbZoom(lbS<2.5?2:1/lbS,e.clientX,e.clientY);}); // dbl-click toggles zoom
document.getElementById('lbin').onclick=()=>lbZoom(1.3,innerWidth/2,innerHeight/2);
document.getElementById('lbout').onclick=()=>lbZoom(1/1.3,innerWidth/2,innerHeight/2);
document.getElementById('lbreset').onclick=lbReset;
document.getElementById('lbclose').onclick=lbClose;

/* ---------- search ---------- */
document.getElementById('q').addEventListener('input',e=>{const q=e.target.value.trim().toLowerCase();let n=0;
  for(const c of cards){const ok=c.key.includes(q);c.el.style.display=ok?'':'none';if(ok)n++;}
  document.getElementById('count').textContent=`${n} / ${cards.length} ${T.projects}`;});

/* ---------- boot ---------- */
async function boot(cat){
  const np=cat.reduce((s,e)=>s+e.pieces.length,0);
  document.getElementById('scount').textContent=`// ${cat.length} ${T.projects} · ${np} ${T.pieces}`;
  document.getElementById('count').textContent=`${cat.length} ${T.projects}`;
  if(!cat.length){grid.innerHTML=`<div class="none">${T.noProjects}</div>`;return;}
  cat.forEach(e=>{e._el=makeCard(e);});
  for(const e of cat){ await fillThumb(e); }
}
(CATALOG?Promise.resolve(CATALOG):fetch('/catalog').then(r=>r.json()))
  .then(boot).catch(e=>{document.getElementById('count').textContent='error: '+e.message;});
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
