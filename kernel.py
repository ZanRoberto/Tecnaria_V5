"""
OVERTOP V16 — KERNEL
=====================
Il motore. Fa UNA cosa: ciclo di vita del tick.

Input:  prezzo, timestamp
Output: ENTRA / BLOCCA / CHIUDI / NIENTE

Non sa niente di RSI, MACD, regime, fingerprint.
Sa solo: chiedi alle skill, esegui la decisione.
Zero gate hardcoded. Zero return silenziosi.
"""

import time
import logging
import threading
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# STRUTTURE DATI
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class TickData:
    """Un tick di mercato."""
    price:     float
    timestamp: float
    volume:    float = 0.0

@dataclass
class SkillResult:
    """Risultato di una skill — sempre esplicito, mai silenzioso."""
    ok:      bool
    motivo:  str
    valore:  float = 0.0
    extra:   dict  = field(default_factory=dict)

@dataclass
class KernelDecision:
    """Decisione finale del kernel per questo tick."""
    azione:    str        # ENTRA | BLOCCA | CHIUDI | NIENTE
    motivo:    str        # sempre presente
    size:      float = 0.0
    direction: str   = ""
    score:     float = 0.0
    soglia:    float = 0.0
    skill_log: list  = field(default_factory=list)

@dataclass
class Position:
    """Posizione aperta."""
    direction:   str      # LONG | SHORT
    entry_price: float
    size:        float
    entry_time:  float
    entry_score: float = 0.0

# ═══════════════════════════════════════════════════════════════════════════
# KERNEL
# ═══════════════════════════════════════════════════════════════════════════

class Kernel:
    """
    Kernel V16 — immutabile, testabile, sostituibile.
    
    Ciclo per ogni tick:
      1. SKILL_HEALTH   — sistema sano?
      2. SKILL_REGIME   — che mercato è?
      3. SKILL_DIRECTION — long o short?
      4. SKILL_ENTRY    — entra o blocca?
      5. SKILL_EXIT     — chiudi posizione?
      6. Esegui decisione
    """

    VERSION = "V16.0"

    def __init__(self, symbol: str, capital: float = 10000.0, paper: bool = True):
        self.symbol   = symbol
        self.capital  = capital
        self.paper    = paper

        # Stato
        self.position:  Optional[Position] = None
        self.trades:    list = []
        self.tick_count: int = 0
        self._last_tick_time: float = 0.0
        self._lock = threading.RLock()

        # Skills — iniettate dall'esterno (dependency injection)
        self.skill_health    = None
        self.skill_regime    = None
        self.skill_direction = None
        self.skill_entry     = None
        self.skill_exit      = None

        # Capsule engine — iniettato dall'esterno
        self.capsule_engine  = None

        # Comparto engine — switcha assetto completo
        self.comparto_engine  = None

        # Nervosismo engine — reattivo ad ogni tick
        self.nervosismo_engine = None

        # Breath engine — timing entry/exit sull'impulso
        self.breath_engine = None

        # Respiro engine — impulso entry/exit
        self.respiro_engine = None

        # Heartbeat — per dashboard
        self.heartbeat: dict = {
            "symbol":    symbol,
            "version":   self.VERSION,
            "tick":      0,
            "price":     0.0,
            "regime":    "UNKNOWN",
            "direction": "LONG",
            "position":  None,
            "trades":    0,
            "wins":      0,
            "losses":    0,
            "pnl":       0.0,
            "last_decision": {},
            "skill_log": [],
            "capsules":  [],
        }

        log.info(f"[KERNEL] {self.VERSION} avviato — {symbol} {'PAPER' if paper else 'LIVE'}")

    # ────────────────────────────────────────────────────────────────────
    # CICLO PRINCIPALE
    # ────────────────────────────────────────────────────────────────────

    def on_tick(self, price: float, volume: float = 0.0) -> KernelDecision:
        """
        Chiamato ad ogni tick di mercato.
        Restituisce SEMPRE una KernelDecision con motivo esplicito.
        """
        with self._lock:
            now  = time.time()
            tick = TickData(price=price, timestamp=now, volume=volume)
            self.tick_count += 1
            skill_log = []

            # ── 1. HEALTH ────────────────────────────────────────────────
            if self.skill_health:
                h = self.skill_health.evaluate(tick, self)
                skill_log.append(f"HEALTH:{h.motivo}")
                if not h.ok:
                    return self._decide("BLOCCA", f"HEALTH: {h.motivo}", skill_log)

            # ── 2. REGIME ────────────────────────────────────────────────
            regime = "UNKNOWN"
            regime_conf = 0.0
            regime_result = None
            if self.skill_regime:
                regime_result = self.skill_regime.evaluate(tick, self)
                r = regime_result
                skill_log.append(f"REGIME:{r.motivo}")
                regime      = r.extra.get("regime", "UNKNOWN")
                regime_conf = r.valore
            
            # ── 2a. NERVOSISMO — rilevazione tensione ad ogni tick ─────────
            if self.nervosismo_engine:
                skills_map = {"ENTRY": self.skill_entry, "EXIT": self.skill_exit}
                nerv_stato = self.nervosismo_engine.on_tick(price, regime, direction, skills_map)
                self.heartbeat["nervosismo"] = nerv_stato

            # ── 2b. COMPARTO — switcha assetto completo ──────────────────
            if self.comparto_engine and self.skill_regime:
                volatilita = regime_result.extra.get("volatilita", "MEDIA") if 'regime_result' in dir() else "MEDIA"
                trend_now  = regime_result.extra.get("trend", "SIDEWAYS") if 'regime_result' in dir() else "SIDEWAYS"
                skills_map = {
                    "ENTRY": self.skill_entry,
                    "EXIT":  self.skill_exit,
                }
                self.comparto_engine.on_tick(regime, volatilita, trend_now, skills_map)
                self.heartbeat["comparto"] = self.comparto_engine.get_attivo()

            # ── 3. DIRECTION ─────────────────────────────────────────────
            direction = self.heartbeat.get("direction", "LONG")
            if self.skill_direction:
                d = self.skill_direction.evaluate(tick, self)
                skill_log.append(f"DIR:{d.motivo}")
                direction = d.extra.get("direction", direction)

            # ── 3b. RESPIRO — fase impulso ───────────────────────────────
            respiro_stato = None
            if self.respiro_engine:
                respiro_stato = self.respiro_engine.on_tick(price)
                self.heartbeat["respiro"] = respiro_stato

            # ── 4. EXIT (se ho posizione aperta) ─────────────────────────
            if self.position and self.skill_exit:
                # Controlla exit signal dal respiro — priorità su timer
                respiro_exit = False
                if respiro_stato and self.position:
                    dur = time.time() - self.position.entry_time
                    respiro_exit = self.respiro_engine.get_exit_signal(dur)

                e = self.skill_exit.evaluate(tick, self)
                skill_log.append(f"EXIT:{e.motivo}")
                if e.ok or respiro_exit:
                    motivo_exit = "RESPIRO_DECEL" if respiro_exit else e.motivo
                    pnl = self._close_position(price)
                    return self._decide("CHIUDI", f"EXIT: {motivo_exit} PnL={pnl:+.2f}", skill_log)

            # ── 5. ENTRY (se NON ho posizione) ────────────────────────────
            if not self.position and self.skill_entry:
                en = self.skill_entry.evaluate(tick, self)
                skill_log.append(f"ENTRY:{en.motivo}")
                if en.ok:
                    size = en.extra.get("size", 0.3)
                    self._open_position(price, direction, size, en.valore)
                    return self._decide(
                        "ENTRA",
                        f"ENTRY: {en.motivo} size={size}",
                        skill_log,
                        size=size, direction=direction,
                        score=en.valore,
                        soglia=en.extra.get("soglia", 0)
                    )
                else:
                    return self._decide("BLOCCA", f"ENTRY: {en.motivo}", skill_log,
                                        score=en.valore, soglia=en.extra.get("soglia", 0))

            self._update_heartbeat(price, regime, direction, skill_log)
            return self._decide("NIENTE", "nessuna condizione attiva", skill_log)

    # ────────────────────────────────────────────────────────────────────
    # GESTIONE POSIZIONE
    # ────────────────────────────────────────────────────────────────────

    def _open_position(self, price: float, direction: str, size: float, score: float):
        self.position = Position(
            direction=direction,
            entry_price=price,
            size=size,
            entry_time=time.time(),
            entry_score=score,
        )
        log.info(f"[KERNEL] ENTRY {direction} @ {price:.2f} size={size}")

    def _close_position(self, price: float) -> float:
        if not self.position:
            return 0.0
        p = self.position
        if p.direction == "LONG":
            pnl = (price - p.entry_price) / p.entry_price * self.capital * p.size
        else:
            pnl = (p.entry_price - price) / p.entry_price * self.capital * p.size
        
        # Fee
        fee = self.capital * p.size * 0.0002 * 2
        pnl -= fee

        self.trades.append({
            "direction":   p.direction,
            "entry":       p.entry_price,
            "exit":        price,
            "size":        p.size,
            "pnl":         round(pnl, 2),
            "duration":    round(time.time() - p.entry_time),
            "score":       p.entry_score,
            "ts":          time.time(),
        })
        if pnl > 0:
            self.heartbeat["wins"] = self.heartbeat.get("wins", 0) + 1
        else:
            self.heartbeat["losses"] = self.heartbeat.get("losses", 0) + 1

        # Notifica comparto del risultato
        if self.comparto_engine:
            self.comparto_engine.on_trade_closed(pnl)

        # Notifica nervosismo del risultato — calibra soglie
        if self.nervosismo_engine:
            self.nervosismo_engine.on_trade_closed(pnl)

        self.heartbeat["pnl"]    = round(self.heartbeat.get("pnl", 0) + pnl, 2)
        self.heartbeat["trades"] = len(self.trades)
        log.info(f"[KERNEL] EXIT {p.direction} @ {price:.2f} PnL={pnl:+.2f}")
        self.position = None
        return round(pnl, 2)

    # ────────────────────────────────────────────────────────────────────
    # HELPERS
    # ────────────────────────────────────────────────────────────────────

    def _decide(self, azione: str, motivo: str, skill_log: list,
                size=0.0, direction="", score=0.0, soglia=0.0) -> KernelDecision:
        dec = KernelDecision(
            azione=azione, motivo=motivo,
            size=size, direction=direction,
            score=score, soglia=soglia,
            skill_log=skill_log,
        )
        self.heartbeat["last_decision"] = {
            "azione": azione, "motivo": motivo,
            "score": score, "soglia": soglia,
        }
        self.heartbeat["skill_log"] = skill_log[-10:]
        return dec

    def _update_heartbeat(self, price, regime, direction, skill_log):
        self.heartbeat.update({
            "tick":      self.tick_count,
            "price":     price,
            "regime":    regime,
            "direction": direction,
            "position":  {
                "direction":    self.position.direction,
                "entry_price":  self.position.entry_price,
                "size":         self.position.size,
                "duration":     round(time.time() - self.position.entry_time),
            } if self.position else None,
        })

    def attach_skills(self, health=None, regime=None, direction=None,
                      entry=None, exit=None, capsule_engine=None,
                      comparto_engine=None, nervosismo_engine=None,
                      respiro_engine=None):
        """Inietta le skill nel kernel."""
        if health:             self.skill_health      = health
        if regime:             self.skill_regime      = regime
        if direction:          self.skill_direction   = direction
        if entry:              self.skill_entry       = entry
        if exit:               self.skill_exit        = exit
        if capsule_engine:     self.capsule_engine    = capsule_engine
        if comparto_engine:    self.comparto_engine   = comparto_engine
        if nervosismo_engine:  self.nervosismo_engine = nervosismo_engine
        if respiro_engine:     self.respiro_engine    = respiro_engine
        log.info(f"[KERNEL] Skills attaccate: "
                 f"health={'✓' if self.skill_health else '✗'} "
                 f"regime={'✓' if self.skill_regime else '✗'} "
                 f"direction={'✓' if self.skill_direction else '✗'} "
                 f"entry={'✓' if self.skill_entry else '✗'} "
                 f"exit={'✓' if self.skill_exit else '✗'}")

    def get_stats(self) -> dict:
        t = self.trades
        wins   = sum(1 for x in t if x["pnl"] > 0)
        losses = sum(1 for x in t if x["pnl"] <= 0)
        wr     = wins / len(t) * 100 if t else 0.0
        pnl    = sum(x["pnl"] for x in t)
        return {
            "trades": len(t), "wins": wins, "losses": losses,
            "wr": round(wr, 1), "pnl": round(pnl, 2),
            "tick": self.tick_count,
            "position": self.position is not None,
        }
