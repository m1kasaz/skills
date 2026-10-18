"""mikasa skill 渲染器：DSL → 单文件交互式手绘架构图 HTML。

用法:  python3 render.py case.dsl out.html

DSL 语法（行式）：
  case: 标题
  prose: |                  # 可选，1-2 句引子
    ...
  comp 名字 [类型] @分组:    # 类型: client/web/gateway/service/db/cache/mq/storage
    note: |                 # 内容块: note/api/lua/table/sql/logic
      ...                   # @分组 可选；同组组件会被虚线框圈在一起
    seq: 时序标题 |          # 时序图块（渲染在架构图下方整幅）
      用户 -> 网关: 请求      # -> 同步实线；--> 虚线返回
  edge A -> B [1.2]: 标签:   # [编号] 可选，不写自动按顺序编
    problems: |             # 这条交互可能遇到的问题（+解法）
      ...

交互：点图标/连线 → 详情面板出现在架构图下方；点空白处或 ✕ 收起。
输出：自包含 HTML（rough.js 走 CDN）。
"""

import html
import json
import re
import sys

NODE_TYPES = {"client", "web", "gateway", "service", "db", "cache", "mq", "storage"}

COMP_RE = re.compile(r"^comp\s+(.+?)\s*\[(\w+)\](?:\s*@(.+?))?\s*:\s*$")
EDGE_RE = re.compile(r"^edge\s+(.+?)\s*->\s*(.+?)(?:\s*\[([\d.]+)\])?\s*:\s*(.*?)\s*:\s*$")
CASE_RE = re.compile(r"^case:\s*(.+)$")
BLOCK_RE = re.compile(r"^  (\w+):\s*(?:(.*?)\s*)?\|\s*$")
INLINE_RE = re.compile(r"^  (\w+):\s*(.+)$")


SLOT_RE = re.compile(r"^(现象|分析|解法):\s*\|\s*$", re.M)
PROBLEM_RE = re.compile(r"^【(.+?)】\s*$", re.M)


def _split_code_fences(text):
    """把文本按 ``` 围栏切成 text/code 段（围栏允许前导空白和语言标注）。
    用 finditer 逐围栏扫描维护开/关状态：开围栏（可带语言）之后是 code，
    关围栏（```）之后回到 text。re.split 方案会把语言标注错算成段边界，不能用。"""
    segs = []
    pos = 0
    in_code = False
    lang = ""
    for m in re.finditer(r"^[ \t]*```(\w*)[ \t]*$", text, flags=re.M):
        chunk = text[pos:m.start()].strip("\n")
        if in_code:
            lines = chunk.splitlines()
            indents = [len(ln) - len(ln.lstrip()) for ln in lines if ln.strip()]
            pad = min(indents) if indents else 0
            code = "\n".join(ln[pad:] for ln in lines)
            if code.strip():
                segs.append({"t": "code", "c": code, "lang": lang})
            in_code = False
        else:
            if chunk.strip():
                segs.append({"t": "text", "c": chunk.strip()})
            lang = m.group(1) or ""
            in_code = True
        pos = m.end()
    tail = text[pos:].strip("\n")
    if tail.strip():
        if in_code:
            segs.append({"t": "code", "c": tail.strip(), "lang": lang})
        else:
            segs.append({"t": "text", "c": tail.strip()})
    return segs


def _parse_problems(text, what):
    """problems 块的结构化解析：每个【问题】必须含 现象/分析/解法 三槽位，
    且 分析/解法 必须含代码围栏（```）。缺则报错——形状问题不靠模型自觉。"""
    chunks = PROBLEM_RE.split(text)
    if chunks[0].strip():
        raise SyntaxError(f"{what}: problems 内容必须以【问题名】开头")
    problems = []
    names = chunks[1::2]
    bodies = chunks[2::2]
    for name, body in zip(names, bodies):
        slot_marks = list(SLOT_RE.finditer(body))
        slots = {}
        for idx, m in enumerate(slot_marks):
            end = slot_marks[idx + 1].start() if idx + 1 < len(slot_marks) else len(body)
            slots[m.group(1)] = body[m.end():end].strip("\n")
        for s in ("现象", "分析", "解法"):
            if s not in slots or not slots[s].strip():
                raise SyntaxError(f"{what}: 问题「{name}」缺「{s}」段")
        for s in ("分析", "解法"):
            segs = _split_code_fences(slots[s])
            if not any(seg["t"] == "code" for seg in segs):
                raise SyntaxError(f"{what}: 问题「{name}」的「{s}」段必须含代码围栏（```）")
        problems.append({"name": name,
                         "slots": {k: _split_code_fences(v) for k, v in slots.items()}})
    return problems


def _parse_blocks(lines, i, what):
    blocks = {}
    n = len(lines)
    while i < n:
        line = lines[i].rstrip("\n")
        if not line.strip():
            i += 1
            continue
        if not line.startswith("  "):
            break
        m = BLOCK_RE.match(line)
        if m:
            key = m.group(1)
            title = (m.group(2) or "").strip()
            i += 1
            body = []
            while i < n and (lines[i].startswith("    ") or not lines[i].strip()):
                body.append(lines[i][4:] if lines[i].startswith("    ") else "")
                i += 1
            text = "\n".join(body).strip("\n")
            if key == "seq":
                blocks["seq"] = {"title": title, "text": text}
            elif key == "problems":
                if title:
                    raise SyntaxError(f"{what}: problems 块不支持标题（第 {i + 1} 行附近）")
                blocks[key] = _parse_problems(text, what)
            else:
                if title:
                    raise SyntaxError(f"{what}: 块 {key!r} 不支持标题（第 {i + 1} 行附近）")
                blocks[key] = text
            continue
        m = INLINE_RE.match(line)
        if m:
            blocks[m.group(1)] = m.group(2).strip()
            i += 1
            continue
        raise SyntaxError(f"{what}: 无法解析的内容块行 {i + 1}: {line!r}")
    return blocks, i


def parse(text):
    model = {"title": "", "prose": "", "comps": [], "edges": []}
    lines = text.splitlines()
    i, n = 0, len(lines)
    while i < n:
        line = lines[i].rstrip()
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue
        m = CASE_RE.match(line)
        if m:
            model["title"] = m.group(1).strip()
            i += 1
            continue
        m = re.match(r"^prose:\s*\|\s*$", line)
        if m:
            i += 1
            body = []
            while i < n and (lines[i].startswith("  ") or not lines[i].strip()):
                body.append(lines[i][2:] if lines[i].startswith("  ") else "")
                i += 1
            model["prose"] = "\n".join(body).strip("\n")
            continue
        m = COMP_RE.match(line)
        if m:
            name, typ, group = m.group(1).strip(), m.group(2).strip(), (m.group(3) or "").strip()
            if typ not in NODE_TYPES:
                raise SyntaxError(f"未知组件类型 {typ!r}（第 {i + 1} 行），可选: {sorted(NODE_TYPES)}")
            blocks, i = _parse_blocks(lines, i + 1, f"comp {name}")
            model["comps"].append({"name": name, "type": typ, "group": group, "blocks": blocks})
            continue
        m = EDGE_RE.match(line)
        if m:
            frm, to, num, label = (m.group(1).strip(), m.group(2).strip(),
                                   m.group(3), m.group(4).strip())
            blocks, i = _parse_blocks(lines, i + 1, f"edge {frm}->{to}")
            model["edges"].append({"from": frm, "to": to, "num": num or "", "label": label,
                                   "blocks": blocks})
            continue
        raise SyntaxError(f"无法解析第 {i + 1} 行: {line!r}")
    return model


CELL_W, CELL_H, COL_GAP, ROW_GAP, PAD = 240, 190, 300, 240, 90
ICON_R = 78  # 图标活动半径（连线锚点用）


def layout(model):
    """最长路径分层，列内垂直居中。"""
    names = [c["name"] for c in model["comps"]]
    depth = {n: 0 for n in names}
    for _ in range(len(names)):
        for e in model["edges"]:
            if e["from"] in depth and e["to"] in depth:
                depth[e["to"]] = max(depth[e["to"]], depth[e["from"]] + 1)
    cols = {}
    for name, d in depth.items():
        cols.setdefault(d, []).append(name)
    max_rows = max(len(v) for v in cols.values())
    pos = {}
    for d, ns in sorted(cols.items()):
        y0 = PAD + (max_rows - len(ns)) * ROW_GAP / 2
        for k, name in enumerate(ns):
            pos[name] = (PAD + d * COL_GAP, y0 + k * ROW_GAP)
    width = max(x for x, _ in pos.values()) + CELL_W + PAD if pos else 400
    height = (PAD + max_rows * ROW_GAP) if pos else 300
    return pos, width, height


def gen_groups(model, pos):
    """按 @分组 聚合成员，产出虚线框几何（包围盒 + padding）。"""
    groups = {}
    for c in model["comps"]:
        if c["group"] and c["name"] in pos:
            groups.setdefault(c["group"], []).append(pos[c["name"]])
    out = []
    for name, pts in groups.items():
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        out.append({"name": name,
                    "x": min(xs) - 36, "y": min(ys) - 52,
                    "w": max(xs) - min(xs) + CELL_W + 72,
                    "h": max(ys) - min(ys) + CELL_H + 104})
    return out


def _esc(text):
    return html.escape(text, quote=True)


BLOCK_LABELS = {
    "note": "说明", "api": "接口设计", "lua": "Lua 脚本", "table": "表设计",
    "sql": "SQL", "logic": "逻辑", "problems": "可能遇到的问题",
}


def _collect_seqs(model):
    seqs = []
    for c in model["comps"]:
        s = c["blocks"].get("seq")
        if s:
            seqs.append({"owner": c["name"], "kind": "comp",
                         "title": s["title"] or f"{c['name']} 的时序", "text": s["text"]})
    for e in model["edges"]:
        s = e["blocks"].get("seq")
        if s:
            seqs.append({"owner": f"{e['from']} → {e['to']} · {e['label']}", "kind": "edge",
                         "title": s["title"] or f"{e['from']} → {e['to']} 的时序", "text": s["text"]})
    return seqs


def _est_tokens(text):
    """粗估 token 数：CJK 一字符一 token，其余按 ~4 字符一 token。"""
    cjk = sum(1 for c in text if ord(c) > 0x2E7F)
    return round(cjk + (len(text) - cjk) / 4)


def render_html(model, pos, width, height, dsl_text):
    seqs = _collect_seqs(model)

    def seq_no(blocks):
        s = blocks.get("seq")
        if not s:
            return None
        for idx, item in enumerate(seqs):
            if item["text"] == s["text"]:
                return idx
        return None

    nodes = []
    for c in model["comps"]:
        nodes.append({"name": c["name"], "type": c["type"],
                      "x": pos[c["name"]][0], "y": pos[c["name"]][1],
                      "blocks": {k: v for k, v in c["blocks"].items() if k != "seq"},
                      "seqNo": seq_no(c["blocks"]),
                      "hasContent": bool(c["blocks"])})
    edges = []
    for i, e in enumerate(model["edges"]):
        if e["from"] in pos and e["to"] in pos:
            edges.append({"from": e["from"], "to": e["to"], "label": e["label"],
                          "num": e["num"] or str(i + 1),
                          "blocks": {k: v for k, v in e["blocks"].items() if k != "seq"},
                          "seqNo": seq_no(e["blocks"]),
                          "hasContent": bool(e["blocks"])})
    payload = {"title": model["title"], "width": width, "height": height,
               "cellW": CELL_W, "cellH": CELL_H, "iconR": ICON_R,
               "groups": gen_groups(model, pos),
               "nodes": nodes, "edges": edges, "seqs": seqs, "blockLabels": BLOCK_LABELS}
    prose_html = "".join(
        f"<p>{_esc(p).replace(chr(10), '<br>')}</p>"
        for p in re.split(r"\n\s*\n", model["prose"]) if p.strip()
    )
    model_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    stats = f"DSL <b>≈{_est_tokens(dsl_text)}</b> tokens · {len(dsl_text.encode('utf-8'))} B"
    return _TEMPLATE.replace("__TITLE__", _esc(model["title"])) \
        .replace("__PROSE__", prose_html) \
        .replace("__STATS__", stats) \
        .replace("__MODEL__", model_json)


_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ · mikasa</title>
<style>
  :root { --bg:#16171c; --panel:#1e2027; --ink:#e8e6e3; --dim:#8b8d94; --red:#d64545; --line:#2a2c34;
          --blue:#5b8fc9; --green:#57a773; }
  * { box-sizing: border-box; }
  ::-webkit-scrollbar { width:10px; height:10px; }
  ::-webkit-scrollbar-track { background:var(--bg); }
  ::-webkit-scrollbar-thumb { background:#33363f; border-radius:5px; border:2px solid var(--bg); }
  ::-webkit-scrollbar-thumb:hover { background:#4a4e59; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font-family:"Sarasa Mono SC","SF Mono",Menlo,Consolas,monospace; }
  header { padding:34px 48px 18px; border-bottom:2px solid var(--line); }
  header h1 { margin:0; font-size:28px; letter-spacing:3px; }
  header .sub { color:var(--red); font-size:12px; margin-top:8px; letter-spacing:5px; }
  #prose { padding:22px 48px 8px; max-width:880px; line-height:1.9; font-size:15px; color:#c9c7c2; }
  #prose p { margin:0 0 12px; }
  #diagram { padding:8px 24px; overflow-x:auto; }
  #canvas { display:block; margin:0 auto; }
  text { font-family:inherit; fill:var(--ink); }
  .node { cursor:pointer; }
  .node:hover { filter:drop-shadow(0 0 12px rgba(214,69,69,.4)); }
  .node-label { font-size:15px; }
  .edge-label-bg { fill:var(--bg); }
  .edge-label { fill:var(--dim); font-size:13px; }
  .edge-num { fill:#16171c; font-size:12.5px; font-weight:bold; }
  .edge-group { cursor:pointer; }
  .edge-group:hover .edge-line { stroke:var(--red); }
  .edge-group:hover .edge-label { fill:var(--red); }
  .group-label { fill:var(--dim); font-size:13px; letter-spacing:1px; }
  header { position:relative; }
  header .stats { position:absolute; top:38px; right:48px; color:var(--dim); font-size:12px;
                  text-align:right; line-height:1.7; }
  header .stats b { color:var(--red); font-weight:normal; }
  /* 详情面板（图下方，非抽屉） */
  #detail { max-width:960px; margin:8px auto 0; padding:0 24px; display:none; }
  #detail.open { display:block; }
  .detail-card { background:var(--panel); border:1px solid var(--line); border-radius:8px;
                 padding:22px 26px 26px; position:relative;
                 box-shadow:0 8px 28px rgba(0,0,0,.4); }
  .detail-card h2 { font-size:19px; margin:0 0 4px; }
  .detail-card .tag { color:var(--red); font-size:12px; letter-spacing:2px; }
  .detail-card h4 { color:var(--red); margin:22px 0 8px; font-size:13px; letter-spacing:1px;
                    border-left:3px solid var(--red); padding-left:8px; }
  .detail-card pre.code-block { background:#14151a; border:1px solid var(--line); padding:14px; font-size:13px;
                     line-height:1.75; white-space:pre-wrap; word-break:break-word; margin:8px 0;
                     border-radius:4px; }
  .detail-card pre code.hljs { background:transparent; padding:0; }
  /* 槽位内文字段：去盒子化，纯段落流动；只有代码保留盒子 */
  .detail-card .prose-block { font-family:"PingFang SC","Microsoft YaHei",sans-serif;
                              font-size:14px; color:#d6d4cf;
                              margin:4px 0; line-height:1.75; }
  .detail-card .prose-block.candidate { margin-top:18px; color:#e8e6e3; font-weight:600; }
  .detail-card .prose-block.candidate::before { content:""; display:inline-block; width:8px; height:8px;
                              border-radius:50%; background:var(--red); margin-right:8px; }
  .detail-card .seq-link { display:inline-block; margin-top:18px; color:var(--red); font-size:13px;
                           text-decoration:none; border:1px solid var(--red); padding:6px 12px;
                           border-radius:4px; }
  .detail-hint { position:absolute; top:16px; right:20px; color:var(--dim); font-size:11.5px; }
  /* 问题卡片：每个问题一个节点，现象/分析/解法三段分栏 */
  .problem { border:1px solid var(--line); border-radius:6px; margin:16px 0 20px;
             overflow:hidden; background:#17181d; }
  .problem-name { color:var(--ink); font-size:14.5px; font-weight:bold;
                  padding:10px 16px; background:#1c1e24; border-bottom:1px solid var(--line);
                  border-left:3px solid var(--red); }
  .slot { display:flex; gap:14px; padding:12px 16px; }
  .slot + .slot { border-top:1px dashed #26282f; }
  .slot-name { flex:0 0 auto; align-self:flex-start; font-size:11px; letter-spacing:2px;
               border-radius:3px; padding:2px 8px; margin-top:2px; }
  .slot-现象 .slot-name { color:#8b8d94; border:1px solid #4a4d55; }
  .slot-分析 .slot-name { color:#d6a756; border:1px solid #d6a756; }
  .slot-解法 .slot-name { color:#7fb77e; border:1px solid #7fb77e; }
  .slot-body { flex:1; min-width:0; }
  .slot-body pre + pre { margin-top:8px; }
  .seq-section { padding:20px 48px 40px; max-width:1100px; margin:0 auto; }
  .seq-block { margin:36px 0; }
  .seq-block h3 { font-size:15px; color:var(--ink); margin:0 0 4px; }
  .seq-block .owner { color:var(--dim); font-size:12px; margin-bottom:12px; }
  .seq-svg-wrap { background:var(--panel); border:1px solid var(--line); border-radius:6px;
                  padding:18px; }
  .seq-svg-wrap svg { display:block; width:100%; height:auto; }
</style>
<script src="https://unpkg.com/roughjs@4.6.6/bundled/rough.js"></script>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
</head>
<body>
<header>
  <h1>__TITLE__</h1>
  <div class="sub">M I K A S A · 系统设计手绘稿</div>
  <div class="stats">__STATS__</div>
</header>
<main>
  <section id="prose">__PROSE__</section>
  <section id="diagram"><svg id="canvas"></svg></section>
  <section id="detail"><div class="detail-card" id="detail-card"></div></section>
  <section class="seq-section" id="sequences"></section>
</main>

<script id="model" type="application/json">__MODEL__</script>
<script>
const M = JSON.parse(document.getElementById('model').textContent);
const svg = document.getElementById('canvas');
svg.setAttribute('viewBox', `0 0 ${M.width} ${M.height}`);
svg.setAttribute('width', M.width); svg.setAttribute('height', M.height);
const rc = rough.svg(svg);
const NS = 'http://www.w3.org/2000/svg';
const S = { stroke:'#e8e6e3', roughness:0.9, strokeWidth:1.7 };
const DIM = '#8b8d94';

function el(node, parent){ (parent||svg).appendChild(node); return node; }
function mktext(x, y, str, cls, anchor, parent){
  const t = document.createElementNS(NS,'text');
  t.setAttribute('x', x); t.setAttribute('y', y);
  t.setAttribute('text-anchor', anchor || 'middle');
  if (cls) t.setAttribute('class', cls);
  t.textContent = str; return el(t, parent);
}
const CN = ['①','②','③','④','⑤','⑥','⑦','⑧','⑨','⑩'];
const ICON_COLORS = { client:'#e8e6e3', web:'#e8e6e3', gateway:'#e8e6e3', service:'#e8e6e3',
                      db:'#5b8fc9', cache:'#d64545', mq:'#57a773', storage:'#e8e6e3' };

function drawIcon(type, cx, cy, parent){
  const col = ICON_COLORS[type] || '#e8e6e3';
  const A = { ...S, stroke: col };
  const filled = { ...A, fill: col, fillStyle:'hachure', fillWeight:1.3 };
  switch(type){
    case 'client':
      el(rc.rectangle(cx-30,cy-56,60,112,A), parent);
      el(rc.rectangle(cx-21,cy-40,42,62,A), parent);
      el(rc.circle(cx,cy+37,10,A), parent);
      break;
    case 'web':
      el(rc.rectangle(cx-60,cy-48,120,96,A), parent);
      el(rc.line(cx-60,cy-26,cx+60,cy-26,A), parent);
      el(rc.circle(cx-47,cy-37,4.5,filled), parent);
      el(rc.circle(cx-36,cy-37,4.5,filled), parent);
      el(rc.circle(cx-25,cy-37,4.5,filled), parent);
      el(rc.line(cx-42,cy-8,cx+42,cy-8,{...A,stroke:DIM}), parent);
      el(rc.line(cx-42,cy+8,cx+26,cy+8,{...A,stroke:DIM}), parent);
      break;
    case 'gateway':
      el(rc.circle(cx,cy,96,A), parent);
      el(rc.ellipse(cx,cy,42,96,A), parent);
      el(rc.line(cx-48,cy,cx+48,cy,A), parent);
      el(rc.ellipse(cx,cy,96,44,A), parent);
      break;
    case 'service':
      el(rc.rectangle(cx-42,cy-20,74,66,filled), parent);
      el(rc.rectangle(cx-22,cy-40,74,66,{...A,stroke:DIM}), parent);
      el(rc.line(cx-42,cy-20,cx-22,cy-40,A), parent);
      el(rc.line(cx+32,cy-20,cx+52,cy-40,A), parent);
      el(rc.line(cx-42,cy+46,cx-22,cy+26,A), parent);
      el(rc.line(cx+32,cy+46,cx+52,cy+26,A), parent);
      break;
    case 'db':
      el(rc.ellipse(cx,cy-40,88,30,filled), parent);
      el(rc.line(cx-44,cy-40,cx-44,cy+40,A), parent);
      el(rc.line(cx+44,cy-40,cx+44,cy+40,A), parent);
      el(rc.path(`M ${cx-44} ${cy+40} A 44 15 0 0 0 ${cx+44} ${cy+40}`, A), parent);
      el(rc.path(`M ${cx-44} ${cy} A 44 15 0 0 0 ${cx+44} ${cy}`, {...A,stroke:DIM}), parent);
      break;
    case 'cache':
      el(rc.path(`M ${cx} ${cy-50} L ${cx+54} ${cy-28} L ${cx} ${cy-6} L ${cx-54} ${cy-28} Z`, filled), parent);
      el(rc.path(`M ${cx-54} ${cy-13} L ${cx} ${cy+9} L ${cx+54} ${cy-13}`, filled), parent);
      el(rc.path(`M ${cx-54} ${cy+3} L ${cx} ${cy+25} L ${cx+54} ${cy+3}`, filled), parent);
      break;
    case 'mq':
      el(rc.ellipse(cx-50,cy,22,66,filled), parent);
      el(rc.line(cx-50,cy-33,cx+50,cy-33,A), parent);
      el(rc.line(cx-50,cy+33,cx+50,cy+33,A), parent);
      el(rc.path(`M ${cx+50} ${cy-33} A 11 33 0 0 1 ${cx+50} ${cy+33}`, filled), parent);
      el(rc.path(`M ${cx-50} ${cy-33} A 11 33 0 0 1 ${cx-50} ${cy+33}`, {...A,stroke:DIM}), parent);
      break;
    case 'storage':
      el(rc.rectangle(cx-37,cy-48,72,92,{...A,stroke:DIM}), parent);
      el(rc.rectangle(cx-29,cy-38,72,92,A), parent);
      for(let k=0;k<4;k++) el(rc.line(cx-16,cy-18+k*16,cx+28,cy-18+k*16,{...A,stroke:DIM}), parent);
      break;
    default:
      el(rc.rectangle(cx-55,cy-40,110,80,A), parent);
  }
}

// ---------- 详情面板（图下方，非抽屉） ----------
const detail = document.getElementById('detail');
const detailCard = document.getElementById('detail-card');
let detailKey = null;
function closeDetail(){ detail.classList.remove('open'); detailKey = null; }
document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') closeDetail(); });
// 代码块语言映射：有语言的走高亮，没有的就是大白话块
const BLOCK_LANG = { sql:'sql', table:'sql', lua:'lua', api:'javascript', logic:'javascript' };
// 文本里的 ``` 围栏 → text/code 段（围栏可带语言，如 ```sql）
// 逐围栏扫描维护开/关状态：开围栏（可带语言）之后是 code，关围栏之后回到 text
function splitFences(text){
  const segs = [];
  const re = /^[ \\t]*```(\\w*)[ \\t]*$/gm;
  let pos = 0, inCode = false, lang = '', m;
  const dedent = (chunk) => {
    const lines = chunk.split('\\n');
    const indents = lines.filter(l => l.trim()).map(l => l.length - l.trimStart().length);
    const pad = indents.length ? Math.min(...indents) : 0;
    return lines.map(l => l.slice(pad)).join('\\n');
  };
  while ((m = re.exec(text)) !== null){
    const chunk = text.slice(pos, m.index).replace(/^\\n+|\\n+$/g, '');
    if (inCode){
      const code = dedent(chunk);
      if (code.trim()) segs.push({ t:'code', c:code, lang });
      inCode = false;
    } else {
      if (chunk.trim()) segs.push({ t:'text', c:chunk.trim() });
      lang = m[1] || '';
      inCode = true;
    }
    pos = re.lastIndex;
  }
  const tail = text.slice(pos).replace(/^\\n+|\\n+$/g, '');
  if (tail.trim()) segs.push(inCode ? { t:'code', c:tail.trim(), lang } : { t:'text', c:tail.trim() });
  return segs;
}
function openDetail(key, title, tag, blocks, seqNo){
  if (detailKey === key){ closeDetail(); return; }   // 再点同一目标 = 收起
  detailKey = key;
  let h = `<div class="detail-hint">再点一次 / Esc / 点空白处收起</div><h2>${title}</h2><div class="tag">${tag}</div>`;
  const entries = Object.entries(blocks || {}).filter(([,v]) => v && (!Array.isArray(v) || v.length));
  const values = [];
  const segHtml = (seg, fallbackLang) => {
    if (seg.t === 'code'){
      values.push(seg.c);
      return `<pre class="code-block"><code class="language-${seg.lang || fallbackLang || 'javascript'}" data-v></code></pre>`;
    }
    // 文字段按空行拆成段落；候选标题行（候选一/二/三…）即使没有空行也单独成段并加圆点
    // 段落内的单行换行折叠掉：两侧都是拉丁字符时补空格，否则直接拼接（中文排版）
    const isCJK = (ch) => !!ch && ch.charCodeAt(0) > 0x2E7F;
    return seg.c.split(/\\n\\s*\\n|\\n(?=\\s*候选[一二三四五六七八九十\\d])/).map(p => p.trim()).filter(Boolean).map(p => {
      p = p.replace(/[ \\t]*\\n[ \\t]*/g, (m, i, s) => {
        let a = i - 1; while (a >= 0 && (s[a] === ' ' || s[a] === '\\t')) a--;
        const b = i + m.length;
        return (isCJK(s[a]) || isCJK(s[b])) ? '' : ' ';
      });
      values.push(p);
      const cand = /^候选[一二三四五六七八九十\\d]/.test(p) ? ' candidate' : '';
      return `<div data-v class="prose-block${cand}"></div>`;
    }).join('');
  };
  if (!entries.length && (seqNo === null || seqNo === undefined)){
    values.push('（无内容）');
    h += `<div data-v class="prose-block"></div>`;
  }
  for (const [k, v] of entries){
    if (k === 'problems' && Array.isArray(v)){
      h += `<h4>${M.blockLabels[k]}</h4>`;
      for (const p of v){
        h += `<div class="problem"><div class="problem-name">${p.name}</div>`;
        for (const slot of ['现象','分析','解法']){
          h += `<div class="slot slot-${slot}"><span class="slot-name">${slot}</span><div class="slot-body">`;
          for (const seg of p.slots[slot]) h += segHtml(seg);
          h += `</div></div>`;
        }
        h += `</div>`;
      }
      continue;
    }
    const lang = BLOCK_LANG[k];
    h += `<h4>${M.blockLabels[k] || k}</h4>`;
    if (lang){
      values.push(v);
      h += `<pre class="code-block"><code class="language-${lang}" data-v></code></pre>`;
    } else {
      for (const seg of splitFences(v)) h += segHtml(seg);
    }
  }
  if (seqNo !== null && seqNo !== undefined)
    h += `<a class="seq-link" href="#seq-${seqNo}">↓ 看这条链路的完整时序图</a>`;
  detailCard.innerHTML = h;
  detailCard.querySelectorAll('[data-v]').forEach((el, i) => { if (i < values.length) el.textContent = values[i]; });
  detailCard.querySelectorAll('code[class^="language-"]').forEach(c => hljs.highlightElement(c));
  detail.classList.add('open');
  detail.scrollIntoView({ behavior:'smooth', block:'nearest' });
}

// ---------- 架构图 ----------
// 点阵背景
const defs = document.createElementNS(NS,'defs');
defs.innerHTML = `<pattern id="dots" width="26" height="26" patternUnits="userSpaceOnUse">
  <circle cx="2" cy="2" r="1.1" fill="#23252c"/></pattern>`;
svg.appendChild(defs);
const bgRect = document.createElementNS(NS,'rect');
bgRect.setAttribute('width','100%'); bgRect.setAttribute('height','100%');
bgRect.setAttribute('fill','url(#dots)'); svg.appendChild(bgRect);
// 点空白处收起详情
bgRect.addEventListener('click', closeDetail);

// 分组虚线框（最底层）
for (const gdef of M.groups){
  const rect = rc.rectangle(gdef.x, gdef.y, gdef.w, gdef.h,
    { stroke:'#3a3d47', roughness:1.1, strokeWidth:1.4, strokeLineDash:[10,7] });
  svg.appendChild(rect);
  mktext(gdef.x + 14, gdef.y + 22, gdef.name, 'group-label', 'start');
}

// edges（压在节点下）
const byName = Object.fromEntries(M.nodes.map(n => [n.name, n]));
function center(n){ return [n.x + M.cellW/2, n.y + M.cellH/2]; }
for (const e of M.edges){
  const a = byName[e.from], b = byName[e.to];
  if (!a || !b) continue;
  const [ax, ay] = center(a), [bx, by] = center(b);
  const dx = bx - ax, dy = by - ay;
  const dist = Math.hypot(dx, dy) || 1;
  const ux = dx / dist, uy = dy / dist;
  const x1 = ax + ux * M.iconR, y1 = ay + uy * M.iconR;
  const x2 = bx - ux * M.iconR, y2 = by - uy * M.iconR;
  const g = document.createElementNS(NS,'g');
  g.setAttribute('class','edge-group'); svg.appendChild(g);
  const line = rc.line(x1, y1, x2, y2, { stroke:'#8b8d94', roughness:0.9, strokeWidth:1.5 });
  line.setAttribute('class','edge-line'); g.appendChild(line);
  const ang = Math.atan2(y2-y1, x2-x1), L = 13;
  g.appendChild(rc.line(x2, y2, x2 - L*Math.cos(ang-0.4), y2 - L*Math.sin(ang-0.4),
    {stroke:'#8b8d94', roughness:0.6, strokeWidth:1.5}));
  g.appendChild(rc.line(x2, y2, x2 - L*Math.cos(ang+0.4), y2 - L*Math.sin(ang+0.4),
    {stroke:'#8b8d94', roughness:0.6, strokeWidth:1.5}));
  const mx = (x1+x2)/2, my = (y1+y2)/2;
  // 步骤编号红标 + 标签（底衬芯片）
  const numW = (e.num.length * 8) + 12;
  const numChip = rc.rectangle(mx - numW - 4, my - 26, numW, 20,
    { stroke:'#d64545', fill:'#d64545', fillStyle:'solid', roughness:0.6, strokeWidth:1 });
  g.appendChild(numChip);
  const nt = mktext(mx - numW/2 - 4, my - 12, e.num, 'edge-num', 'middle', g);
  const labelW = e.label.length * 13.5 + 14;
  const chip = document.createElementNS(NS,'rect');
  chip.setAttribute('x', mx + 8); chip.setAttribute('y', my - 26);
  chip.setAttribute('width', labelW); chip.setAttribute('height', 22);
  chip.setAttribute('class','edge-label-bg'); chip.setAttribute('rx','4');
  g.appendChild(chip);
  mktext(mx + 8 + labelW/2, my - 10, e.label, 'edge-label', 'middle', g);
  const hit = document.createElementNS(NS,'line');
  hit.setAttribute('x1',x1); hit.setAttribute('y1',y1);
  hit.setAttribute('x2',x2); hit.setAttribute('y2',y2);
  hit.setAttribute('stroke','transparent'); hit.setAttribute('stroke-width','30');
  hit.setAttribute('class','edge-hit');
  g.appendChild(hit);
  g.addEventListener('click', (ev) => { ev.stopPropagation();
    openDetail(`e:${e.from}->${e.to}:${e.num}`, `${e.from} → ${e.to}`, e.label, e.blocks, e.seqNo); });
}

// nodes（图标无框，透明热区）
for (const n of M.nodes){
  const g = document.createElementNS(NS,'g');
  g.setAttribute('class','node'); svg.appendChild(g);
  const [cx, cy] = center(n);
  drawIcon(n.type, cx, cy - 6, g);
  mktext(cx, cy + M.iconR - 6, n.name, 'node-label', 'middle', g);
  // 透明热区
  const hit = document.createElementNS(NS,'rect');
  hit.setAttribute('x', cx - M.iconR); hit.setAttribute('y', cy - M.iconR);
  hit.setAttribute('width', M.iconR * 2); hit.setAttribute('height', M.iconR * 2);
  hit.setAttribute('fill', 'transparent');
  g.appendChild(hit);
  g.addEventListener('click', (ev) => { ev.stopPropagation();
    openDetail(`n:${n.name}`, n.name, n.type.toUpperCase(), n.blocks, n.seqNo); });
}

// ---------- 时序图（架构图下方整幅，宽度自适应） ----------
const seqRoot = document.getElementById('sequences');
function renderSeq(item, idx){
  const wrap = document.createElement('div');
  wrap.className = 'seq-block'; wrap.id = `seq-${idx}`;
  const h = document.createElement('h3'); h.textContent = item.title;
  const o = document.createElement('div'); o.className = 'owner'; o.textContent = item.owner;
  const box = document.createElement('div'); box.className = 'seq-svg-wrap';
  wrap.appendChild(h); wrap.appendChild(o); wrap.appendChild(box); seqRoot.appendChild(wrap);

  const lines = item.text.split('\\n').map(s => s.trim()).filter(Boolean);
  const msgs = [];
  const parts = [];
  for (const ln of lines){
    const m = ln.match(/^(.+?)\\s*(-+>)\\s*(.+?)\\s*:\\s*(.+)$/);
    if (!m) continue;
    const [ , from, arrow, to, label ] = m;
    for (const p of [from, to]) if (!parts.includes(p)) parts.push(p);
    msgs.push({ from, to, dashed: arrow === '-->', label });
  }
  if (!msgs.length) { box.textContent = item.text; return; }
  const n = parts.length;
  const W = Math.max(560, n * 200 + 80), LX = i => 80 + i * ((W - 160) / Math.max(n-1, 1));
  const TOP = 46, STEP = 52, H = TOP + msgs.length * STEP + 40;
  const s = document.createElementNS(NS,'svg');
  s.setAttribute('viewBox', `0 0 ${W} ${H}`);
  box.appendChild(s);
  const r = rough.svg(s);
  parts.forEach((p, i) => {
    const x = LX(i);
    s.appendChild(r.rectangle(x - 66, 10, 132, 30,
      { stroke:'#8b8d94', roughness:0.7, strokeWidth:1.3, fill:'#16171c', fillStyle:'solid' }));
    const t = document.createElementNS(NS,'text');
    t.setAttribute('x', x); t.setAttribute('y', 30);
    t.setAttribute('text-anchor','middle'); t.setAttribute('class','edge-label');
    t.setAttribute('fill','#e8e6e3'); t.textContent = p; s.appendChild(t);
    s.appendChild(r.line(x, TOP, x, H - 16,
      { stroke:'#3a3d47', roughness:0.4, strokeWidth:1.2, strokeLineDash:[6,6] }));
  });
  msgs.forEach((m, k) => {
    const y = TOP + 14 + k * STEP;
    const x1 = LX(parts.indexOf(m.from)), x2 = LX(parts.indexOf(m.to));
    const opts = { stroke:'#e8e6e3', roughness:0.8, strokeWidth:1.6 };
    if (m.dashed) opts.strokeLineDash = [7,5];
    if (m.from === m.to){
      // 自调用：默认向右画小回环；标签会超出画布右缘时改为向左画
      const label = `${CN[k] || (k+1)} ${m.label}`;
      const goLeft = x1 + 46 + label.length * 13 > W;
      const sgn = goLeft ? -1 : 1;
      s.appendChild(r.path(`M ${x1} ${y} h ${36*sgn} v 14 h ${-36*sgn}`, opts));
      s.appendChild(r.line(x1, y + 14, x1 + 10*sgn, y + 9, opts));
      s.appendChild(r.line(x1, y + 14, x1 + 10*sgn, y + 19, opts));
      const t = document.createElementNS(NS,'text');
      t.setAttribute('x', x1 + 46*sgn); t.setAttribute('y', y + 4);
      t.setAttribute('text-anchor', goLeft ? 'end' : 'start');
      t.setAttribute('class','edge-label');
      t.textContent = label; s.appendChild(t);
      return;
    }
    s.appendChild(r.line(x1, y, x2, y, opts));
    // 同步/返回都有箭头；返回用空心小箭头区分
    const dir = Math.sign(x2 - x1) || 1;
    const hl = m.dashed ? 9 : 12, hy = m.dashed ? 4 : 5;
    s.appendChild(r.line(x2, y, x2 - hl*dir, y - hy, opts));
    s.appendChild(r.line(x2, y, x2 - hl*dir, y + hy, opts));
    const t = document.createElementNS(NS,'text');
    t.setAttribute('x', (x1+x2)/2); t.setAttribute('y', y - 8);
    t.setAttribute('text-anchor','middle'); t.setAttribute('class','edge-label');
    t.textContent = `${CN[k] || (k+1)} ${m.label}`; s.appendChild(t);
  });
}
M.seqs.forEach((item, i) => renderSeq(item, i));
</script>
</body>
</html>
"""


def main():
    if len(sys.argv) != 3:
        sys.exit("用法: python3 render.py case.dsl out.html")
    with open(sys.argv[1], encoding="utf-8") as f:
        dsl_text = f.read()
    model = parse(dsl_text)
    if not model["comps"]:
        sys.exit("DSL 里至少需要一个 comp")
    pos, width, height = layout(model)
    out = render_html(model, pos, width, height, dsl_text)
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        f.write(out)
    seqs = len(_collect_seqs(model))
    groups = len({c["group"] for c in model["comps"] if c["group"]})
    print(f"OK -> {sys.argv[2]}  ({len(model['comps'])} 组件 / {len(model['edges'])} 连线 / "
          f"{seqs} 时序图 / {groups} 分组)")


if __name__ == "__main__":
    main()
