"""
OVERTOP V16 — APP.PY
=====================
Flask server + Binance WebSocket + Kernel V16.
Sostituisce completamente V15.

Stack:
  - Binance aggTrade WebSocket → kernel.on_tick()
  - 5 Skill + CapsuleEngine collegati al kernel
  - Memoria V15 (SQLite) in sola lettura
  - Dashboard HTML con dati live
  - Route /heartbeat compatibile con UptimeRobot
"""

import os
import json
import time
import threading
import logging
import sqlite3
from datetime import datetime
from flask import Flask, jsonify, render_template_string

# ── V16 components ────────────────────────────────────────────
import sys
sys.path.insert(0, os.path.dirname(__file__))

from kernel import Kernel
from skills import SkillHealth, SkillRegime, SkillDirection, SkillEntry, SkillExit
from capsule_engine import CapsuleEngine, Capsule, CapsuleStato

# ── Config ────────────────────────────────────────────────────
SYMBOL     = os.environ.get("SYMBOL", "BTCUSDC")
PAPER      = os.environ.get("PAPER_TRADE", "true").lower() == "true"
DB_PATH    = os.environ.get("DB_PATH", "/home/app/data/trading_data.db")
DB_V15     = os.environ.get("DB_V15", DB_PATH)  # memoria V15 in sola lettura
PORT       = int(os.environ.get("PORT", 5000))
WS_URL     = f"wss://stream.binance.com:9443/ws/{SYMBOL.lower()}@aggTrade"

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

# ── Shared state ──────────────────────────────────────────────
heartbeat_data = {}
heartbeat_lock = threading.RLock()

# ═══════════════════════════════════════════════════════════════
# MEMORIA V15 — lettura fingerprint da SQLite
# ═══════════════════════════════════════════════════════════════

def load_v15_fingerprints() -> dict:
    """Legge i fingerprint storici dal DB V15 — sola lettura."""
    fp = {}
    try:
        conn = sqlite3.connect(f"file:{DB_V15}?mode=ro", uri=True, timeout=5)
        c = conn.cursor()
        c.execute("""SELECT context_key, wins, total, pnl_avg
                     FROM oracolo_memory WHERE total >= 3""")
        for key, wins, total, pnl_avg in c.fetchall():
            fp[key] = {
                "wr": wins / total if total > 0 else 0,
                "real_samples": total,
                "pnl_avg": pnl_avg or 0,
            }
        conn.close()
        log.info(f"[MEMORIA] ✅ {len(fp)} fingerprint V15 caricati")
    except Exception as e:
        log.warning(f"[MEMORIA] DB V15 non disponibile: {e}")
    return fp

def load_v15_capsules(engine: CapsuleEngine):
    """Carica le capsule STATIC dal DB V15."""
    try:
        conn = sqlite3.connect(f"file:{DB_V15}?mode=ro", uri=True, timeout=5)
        c = conn.cursor()
        c.execute("""SELECT id, livello, trigger_json, azione_json, wr, samples, note
                     FROM capsule_attive WHERE enabled=1""")
        rows = c.fetchall()
        conn.close()
        for row in rows:
            cid, livello, trig_json, az_json, wr, samples, note = row
            try:
                triggers = json.loads(trig_json) if trig_json else []
                cond_parts = []
                for t in triggers:
                    param = t.get("param", "")
                    val   = t.get("value", "")
                    if param and val:
                        cond_parts.append(f"{param} == '{val}'")
                condizione = " and ".join(cond_parts) if cond_parts else "True"

                cap = Capsule(
                    id         = cid,
                    skill      = "ENTRY",
                    parametro  = "",
                    valore     = 0,
                    condizione = condizione,
                    nato_da    = f"V15_{livello}",
                    vita_secs  = 999999,
                    stato      = CapsuleStato.DOMINANTE if livello == "STATIC" else CapsuleStato.ATTIVA,
                    delta_score= -100 if wr < 0.35 else 0,
                )
                engine.add(cap)
            except Exception as e:
                log.warning(f"[CAPSULE] Errore caricamento {cid}: {e}")
        log.info(f"[CAPSULE] ✅ {len(rows)} capsule V15 caricate")
    except Exception as e:
        log.warning(f"[CAPSULE] DB non disponibile: {e}")

# ═══════════════════════════════════════════════════════════════
# SETUP KERNEL V16
# ═══════════════════════════════════════════════════════════════

# Kernel
kernel = Kernel(symbol=SYMBOL, capital=10000.0, paper=PAPER)

# Capsule Engine
capsule_engine = CapsuleEngine(db_path=DB_PATH)

# Comparto Engine
from comparto_engine import CompartoEngine
comparto_engine = CompartoEngine()

# Nervosismo Engine — reattivo ad ogni tick
from nervosismo_engine import NervosismoEngine
nervosismo_engine = NervosismoEngine()

# Breath Engine — timing entry/exit sull'impulso
from breath_engine import BreathEngine
breath_engine = BreathEngine()

# Respiro Engine — impulso entry/exit
from respiro_engine import RespiroEngine
respiro_engine = RespiroEngine()

# Skills
skill_health    = SkillHealth()
skill_regime    = SkillRegime()
skill_direction = SkillDirection()
skill_entry     = SkillEntry()
skill_exit      = SkillExit()

# Collega tutto
kernel.attach_skills(
    health            = skill_health,
    regime            = skill_regime,
    direction         = skill_direction,
    entry             = skill_entry,
    exit              = skill_exit,
    capsule_engine    = capsule_engine,
    comparto_engine   = comparto_engine,
    nervosismo_engine = nervosismo_engine,
    respiro_engine    = respiro_engine,
)

# Carica memoria V15 — fingerprint, capsule, comparti, signal tracker
from memoria_v15 import carica_memoria_v15
carica_memoria_v15(kernel, capsule_engine, comparto_engine)

# Supervisor V16 — analisi e intervento autonomo ogni 30s
from supervisor_v16 import SupervisorV16
supervisor = SupervisorV16(kernel, capsule_engine, comparto_engine)

log.info(f"[V16] Kernel pronto — {SYMBOL} {'PAPER' if PAPER else 'LIVE'}")

# ═══════════════════════════════════════════════════════════════
# BINANCE WEBSOCKET
# ═══════════════════════════════════════════════════════════════

def start_websocket():
    """Loop WebSocket con reconnect automatico."""
    import websocket as ws_lib

    def on_message(ws, msg):
        try:
            data   = json.loads(msg)
            price  = float(data.get('p', 0))
            volume = float(data.get('q', 1.0))
            if price <= 0:
                return

            # Tick al kernel
            decision = kernel.on_tick(price, volume)

            # Aggiorna heartbeat
            stats = kernel.get_stats()
            with heartbeat_lock:
                heartbeat_data.update({
                    "symbol":       SYMBOL,
                    "version":      "V16",
                    "last_price":   price,
                    "last_tick":    datetime.utcnow().isoformat(),
                    "tick_count":   kernel.tick_count,
                    "mode":         "PAPER" if PAPER else "LIVE",
                    "status":       "RUNNING",
                    "regime":       kernel.heartbeat.get("regime", "UNKNOWN"),
                    "regime_conf":  kernel.heartbeat.get("regime_conf", 0),
                    "direction":    kernel.heartbeat.get("direction", "LONG"),
                    "m2_last_score":kernel.heartbeat.get("m2_last_score", 0),
                    "m2_last_soglia":kernel.heartbeat.get("m2_last_soglia", 48),
                    "m2_trades":    stats["trades"],
                    "m2_wins":      stats["wins"],
                    "m2_losses":    stats["losses"],
                    "m2_wr":        stats["wr"] / 100,
                    "m2_pnl":       stats["pnl"],
                    "capital":      kernel.capital,
                    "posizione_aperta": kernel.position is not None,
                    "last_decision": kernel.heartbeat.get("last_decision", {}),
                    "skill_log":    kernel.heartbeat.get("skill_log", []),
                    "capsules":     capsule_engine.get_all(),
                    "comparto":     comparto_engine.get_attivo(),
                    "switch_log":   comparto_engine.get_switch_log(),
                    "comparti_tutti": comparto_engine.get_tutti(),
                    "supervisor":     supervisor.get_status(),
                    "nervosismo":     nervosismo_engine.get_stato(),
                    "storia_gomme":   nervosismo_engine.get_storia(10),
                    "breath":         breath_engine.get_stato(),
                    "respiro":        respiro_engine.get_stato(),
                    "oi_stato":     skill_direction._direction if hasattr(skill_direction,'_direction') else "LONG",
                    "diagnosis": {
                        "blocco":       "OK" if not kernel.heartbeat.get("last_decision",{}).get("azione") == "BLOCCA" else "BLOCCA",
                        "crash_attivo": False,
                        "warmup_rsi":   f"{skill_regime._prices.__len__() if hasattr(skill_regime,'_prices') else 0}/50",
                        "score":        kernel.heartbeat.get("m2_last_score", 0),
                        "soglia":       kernel.heartbeat.get("m2_last_soglia", 48),
                    }
                })
        except Exception as e:
            log.error(f"[WS_MSG] {e}")

    def on_error(ws, error):
        log.error(f"[WS_ERROR] {error}")

    def on_close(ws, code, msg):
        log.warning(f"[WS_CLOSE] {code} {msg}")

    def on_open(ws):
        log.info(f"[WS] Connesso a {WS_URL}")

    while True:
        try:
            ws = ws_lib.WebSocketApp(
                WS_URL,
                on_message = on_message,
                on_error   = on_error,
                on_close   = on_close,
                on_open    = on_open,
            )
            ws.run_forever(ping_interval=20, ping_timeout=10)
        except Exception as e:
            log.error(f"[WS_RESTART] {e}")
        time.sleep(5)

# ═══════════════════════════════════════════════════════════════
# FLASK APP
# ═══════════════════════════════════════════════════════════════

app = Flask(__name__)

@app.route('/')
def index():
    return render_template_string(DASHBOARD_HTML)

@app.route('/heartbeat')
def heartbeat():
    with heartbeat_lock:
        return jsonify(dict(heartbeat_data))

@app.route('/trading/status')
def trading_status():
    with heartbeat_lock:
        hb = dict(heartbeat_data)
    stats = kernel.get_stats()
    return jsonify({
        "heartbeat": hb,
        "metrics": {
            "pnl":      stats["pnl"],
            "wr":       stats["wr"],
            "n_trades": stats["trades"],
            "n_wins":   stats["wins"],
        },
        "trades": kernel.trades[-20:],
        "capsules": capsule_engine.get_all(),
    })

@app.route('/supervisor')
def supervisor_status():
    return jsonify(supervisor.get_status())

@app.route('/health')
def health():
    stats = kernel.get_stats()
    ok = stats["trades"] == 0 or stats["wr"] >= 0
    return jsonify({
        "status": "OK" if ok else "WARNING",
        "trades": stats["trades"],
        "wr": stats["wr"],
        "pnl": stats["pnl"],
        "capsules": capsule_engine.stats(),
    })

@app.route('/capsules')
def capsules():
    return jsonify(capsule_engine.get_all())

# ═══════════════════════════════════════════════════════════════
# DASHBOARD HTML
# ═══════════════════════════════════════════════════════════════

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OVERTOP V16</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#060810;color:#8a9bb0;font-family:'Share Tech Mono',monospace;font-size:11px;padding:12px}
.hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid #1e3a5f}
.title{font-size:14px;color:#00d97a;font-weight:700;letter-spacing:2px}
.dot{width:7px;height:7px;border-radius:50%;background:#00d97a;display:inline-block;animation:p 2s infinite;margin-right:6px}
@keyframes p{0%,100%{opacity:1}50%{opacity:.3}}
.g4{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:10px}
.mc{background:#0c1020;border:0.5px solid #1e3a5f;border-radius:5px;padding:8px 10px}
.ml{font-size:9px;letter-spacing:2px;color:#1e3a5f;margin-bottom:3px}
.mv{font-size:20px;font-weight:700;line-height:1}
.ms{font-size:9px;color:#3d5a7a;margin-top:2px}
.panel{background:#0c1020;border:0.5px solid #1e3a5f;border-radius:6px;margin-bottom:8px}
.ph{padding:7px 10px;font-size:9px;letter-spacing:2px;color:#1e3a5f;border-bottom:0.5px solid #1e3a5f;display:flex;justify-content:space-between}
.pb{padding:8px}
canvas{display:block;width:100%}
.sec{font-size:9px;letter-spacing:3px;color:#1e3a5f;margin:8px 0 5px}
.log-box{max-height:120px;overflow-y:auto}
.lr{display:grid;grid-template-columns:52px 58px 1fr;gap:5px;padding:2px 0;border-bottom:0.5px solid #0a1020;font-size:10px}
.lr:last-child{border:none}
.caps-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:6px}
.cap{border-radius:5px;padding:7px 9px;border:0.5px solid;position:relative;overflow:hidden}
.cvita{position:absolute;bottom:0;left:0;height:2px;background:rgba(255,255,255,.1)}
.badge{padding:2px 8px;border-radius:3px;font-size:9px;background:rgba(245,158,11,.12);color:#f59e0b;border:1px solid rgba(245,158,11,.25)}
</style>
</head>
<body>
<div class="hdr">
  <div><span class="dot"></span><span class="title">OVERTOP V16</span> <span style="font-size:9px;color:#1e3a5f;letter-spacing:1px">KERNEL LIVE · CAPSULE ENGINE</span></div>
  <div style="display:flex;gap:8px;align-items:center">
    <span class="badge" id="mode-badge">PAPER</span>
    <span style="font-size:10px;color:#1e3a5f" id="clk">--:--:--</span>
  </div>
</div>

<div class="g4">
  <div class="mc"><div class="ml">PREZZO</div><div class="mv" id="m-p" style="color:#c8d8e8;font-size:17px">—</div><div class="ms" id="m-c">—</div></div>
  <div class="mc"><div class="ml">PNL</div><div class="mv" id="m-pnl" style="color:#3d5a7a">+$0.00</div><div class="ms" id="m-roi">ROI 0.000%</div></div>
  <div class="mc"><div class="ml">SCORE / SOGLIA</div><div class="mv" id="m-sc" style="color:#f59e0b;font-size:15px">— / 48</div><div class="ms" id="m-gap">—</div></div>
  <div class="mc"><div class="ml">WIN RATE</div><div class="mv" id="m-wr" style="color:#3d5a7a">0%</div><div class="ms" id="m-tr">0W 0L</div></div>
</div>

<div class="panel">
  <div class="ph"><span>PREZZO — {{ symbol }}</span><span id="regime-lbl" style="color:#3b82f6">RANGING</span></div>
  <div class="pb"><canvas id="pc" style="height:160px"></canvas></div>
</div>

<div class="panel">
  <div class="ph"><span style="color:#f59e0b">OI — ORACOLO INTERNO</span><span id="oi-lbl" style="color:#f59e0b">—</span></div>
  <div class="pb"><canvas id="oic" style="height:52px"></canvas></div>
</div>

<div class="sec">CAPSULE ATTIVE</div>
<div class="caps-grid" id="caps-grid"></div>

<div class="sec">LOG DECISIONI</div>
<div class="panel">
  <div class="pb log-box" id="log-box"></div>
</div>

<script>
let px=[],oi=[],en=[],ex_=[],logs=[],lastP=0;
const el=id=>document.getElementById(id);
const REGIME_COL={RANGING:'#3b82f6',EXPLOSIVE:'#f59e0b',TRENDING_BULL:'#00d97a',TRENDING_BEAR:'#ff3355',UNKNOWN:'#3d5a7a'};
const STATO_COL={DOMINANTE:'#00d97a',ATTIVA:'#3b82f6',APPRENDIMENTO:'#f59e0b',ESAURITA:'#6b7280',REVOCATA:'#ff3355'};

function drawPrice(){
  const c=el('pc');if(!c||px.length<2)return;
  const W=c.offsetWidth||600,H=160;c.width=W;c.height=H;
  const ctx=c.getContext('2d');
  ctx.fillStyle='#060810';ctx.fillRect(0,0,W,H);
  const P={t:8,r:52,b:18,l:5},w=W-P.l-P.r,h=H-P.t-P.b;
  const mn=Math.min(...px)*.9999,mx=Math.max(...px)*1.0001,rng=mx-mn||1;
  const N=px.length,xO=i=>P.l+(i/(N-1||1))*w,yO=v=>P.t+(1-(v-mn)/rng)*h;
  ctx.strokeStyle='rgba(255,255,255,0.04)';ctx.lineWidth=1;
  for(let i=0;i<=4;i++){const y=P.t+i*h/4;ctx.beginPath();ctx.moveTo(P.l,y);ctx.lineTo(P.l+w,y);ctx.stroke();}
  ctx.beginPath();ctx.strokeStyle='#378ADD';ctx.lineWidth=1.5;ctx.setLineDash([]);
  px.forEach((p,i)=>i===0?ctx.moveTo(xO(i),yO(p)):ctx.lineTo(xO(i),yO(p)));ctx.stroke();
  en.forEach(e=>{const xi=Math.min(N-1,e.i);ctx.fillStyle='#00d97a';ctx.font='13px sans-serif';ctx.textAlign='center';ctx.fillText('▲',xO(xi),yO(e.p)+14);});
  ex_.forEach(e=>{const xi=Math.min(N-1,e.i);ctx.fillStyle=e.w?'#00d97a':'#ff3355';ctx.font='12px sans-serif';ctx.textAlign='center';ctx.fillText('✕',xO(xi),yO(e.p)-4);});
  const lp=px[N-1];ctx.font='bold 9px monospace';ctx.textAlign='left';ctx.fillStyle='#378ADD';
  ctx.fillText('$'+Math.round(lp),P.l+w+2,yO(lp)+4);
}

function drawOI(){
  const c=el('oic');if(!c||oi.length<2)return;
  const W=c.offsetWidth||600,H=52;c.width=W;c.height=H;
  const ctx=c.getContext('2d');ctx.fillStyle='#060810';ctx.fillRect(0,0,W,H);
  const P={l:5,r:28},w=W-P.l-P.r,N=oi.length;
  const xO=i=>P.l+(i/(N-1||1))*w,yO=v=>2+(1-Math.min(1,Math.max(0,v)))*(H-4);
  ctx.beginPath();oi.forEach((v,i)=>i===0?ctx.moveTo(xO(i),yO(v)):ctx.lineTo(xO(i),yO(v)));
  ctx.lineTo(xO(N-1),H);ctx.lineTo(P.l,H);ctx.closePath();
  ctx.fillStyle='rgba(245,158,11,0.12)';ctx.fill();
  ctx.beginPath();oi.forEach((v,i)=>i===0?ctx.moveTo(xO(i),yO(v)):ctx.lineTo(xO(i),yO(v)));
  ctx.strokeStyle='#f59e0b';ctx.lineWidth=1.5;ctx.stroke();
  const ys=yO(0.65);
  ctx.strokeStyle='rgba(255,255,255,0.2)';ctx.lineWidth=1;ctx.setLineDash([2,4]);
  ctx.beginPath();ctx.moveTo(P.l,ys);ctx.lineTo(P.l+w,ys);ctx.stroke();ctx.setLineDash([]);
  const cur=oi[N-1]||0;ctx.font='8px monospace';ctx.fillStyle=cur>=0.65?'#f59e0b':'#3d5a7a';ctx.textAlign='left';
  ctx.fillText(cur.toFixed(2),P.l+w+2,yO(cur)+4);
  ctx.fillText('0.65',P.l+w+2,ys+3);
}

function renderCaps(caps){
  const g=el('caps-grid');if(!g)return;
  if(!caps||!caps.length){g.innerHTML='<div style="color:#1e3a5f;font-size:10px">Nessuna capsule attiva</div>';return;}
  g.innerHTML=caps.map(c=>{
    const col=STATO_COL[c.stato]||'#6b7280';
    return `<div class="cap" style="background:${col}10;border-color:${col}40">
      <div class="cvita" style="width:${c.vita_pct||0}%"></div>
      <div style="font-size:10px;font-weight:700;color:${col};overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${c.id}</div>
      <div style="font-size:8px;letter-spacing:1px;color:${col};margin:2px 0">${c.stato}</div>
      <div style="height:2px;background:rgba(255,255,255,.08);border-radius:1px;margin:3px 0">
        <div style="width:${c.wr||0}%;height:100%;background:${col};border-radius:1px"></div>
      </div>
      <div style="display:flex;justify-content:space-between;font-size:9px;opacity:.65">
        <span>${c.delta_score>0?'+'+c.delta_score:c.delta_score<-10?'VETO':c.delta_score||'—'}</span>
        <span>WR ${c.wr||0}%</span>
      </div>
    </div>`;
  }).join('');
}

function ts(){return new Date().toTimeString().slice(0,8)}
function fmt(n){return(n>=0?'+$':'-$')+Math.abs(n).toFixed(2)}

let prevTrades=0;

async function load(){
  try {
    const r=await fetch('/trading/status');
    const d=await r.json();
    const hb=d.heartbeat||{};
    const price=hb.last_price||0;
    const chg=lastP>0?(price-lastP)/lastP*100:0;
    if(price>0){px.push(price);if(px.length>120)px.shift();}
    lastP=price||lastP;
    const oi_c=hb.oi_carica||0;
    oi.push(oi_c);if(oi.length>120)oi.shift();
    const score=hb.m2_last_score||0,soglia=hb.m2_last_soglia||48;
    el('m-p').textContent='$'+(price||0).toLocaleString('en',{maximumFractionDigits:0});
    el('m-c').textContent=(chg>=0?'+':'')+chg.toFixed(2)+'%';
    el('m-c').style.color=chg>=0?'var(--g,#00d97a)':'#ff3355';
    const pnl=hb.m2_pnl||0;
    el('m-pnl').textContent=fmt(pnl);el('m-pnl').style.color=pnl>0?'#00d97a':pnl<0?'#ff3355':'#3d5a7a';
    el('m-roi').textContent='ROI '+(pnl/10000*100).toFixed(3)+'%';
    el('m-sc').textContent=score.toFixed(1)+' / '+soglia;
    el('m-sc').style.color=score>=soglia?'#00d97a':score>=soglia-8?'#f59e0b':'#3d5a7a';
    el('m-gap').textContent=score>=soglia?'▲ sopra soglia':'gap '+(soglia-score).toFixed(1);
    const wr=hb.m2_wr||0,tot=(hb.m2_trades||0);
    el('m-wr').textContent=(wr*100).toFixed(0)+'%';
    el('m-wr').style.color=wr>=0.6?'#00d97a':wr>=0.4?'#f59e0b':'#3d5a7a';
    el('m-tr').textContent=(hb.m2_wins||0)+'W '+(hb.m2_losses||0)+'L';
    const regime=hb.regime||'UNKNOWN';
    const rl=el('regime-lbl');if(rl){rl.textContent=regime;rl.style.color=REGIME_COL[regime]||'#3d5a7a';}
    el('oi-lbl').textContent=(hb.oi_stato||'—')+' '+(oi_c||0).toFixed(2);
    el('oi-lbl').style.color=oi_c>=0.65?'#00d97a':'#f59e0b';
    el('clk').textContent=ts();
    // Trades → markers
    const trades=d.trades||[];
    if(trades.length>prevTrades){
      trades.slice(prevTrades).forEach(t=>{
        if(t.type==='M2_ENTRY') en.push({i:px.length-1,p:t.price});
        if(t.type==='M2_EXIT')  ex_.push({i:px.length-1,p:t.price,w:t.pnl>0});
      });
      prevTrades=trades.length;
    }
    drawPrice();drawOI();
    renderCaps(d.capsules||[]);
    // Skill log
    const sl=hb.skill_log||[];
    if(sl.length){
      sl.forEach(l=>logs.unshift({ts:ts(),txt:l}));
      if(logs.length>30)logs.length=30;
      const lb=el('log-box');
      if(lb)lb.innerHTML=logs.map(l=>`<div class="lr"><span style="color:#1e3a5f">${l.ts}</span><span style="color:#3d5a7a">—</span><span style="color:#3d5a7a;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${l.txt}</span></div>`).join('');
    }
  } catch(e){console.error(e);}
}

load();setInterval(load,2000);
</script>
</body>
</html>"""

# ═══════════════════════════════════════════════════════════════
# AVVIO
# ═══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    # Avvia Supervisor
    supervisor.start()

    # Avvia WebSocket in thread daemon
    ws_thread = threading.Thread(target=start_websocket, daemon=True, name="ws_binance")
    ws_thread.start()
    log.info(f"[V16] WebSocket avviato — {WS_URL}")

    # Flask
    log.info(f"[V16] Flask su porta {PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)
