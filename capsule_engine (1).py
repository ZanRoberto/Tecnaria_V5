"""
OVERTOP V16 — CAPSULE ENGINE
==============================
Le capsule modificano i parametri delle skill — non il codice.
Ogni capsula ha stati: APPRENDIMENTO → ATTIVA → DOMINANTE → ESAURITA
Si autorevoca se sbaglia. Nasce da evidenza reale.
"""

import time
import json
import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# STATI CAPSULE
# ═══════════════════════════════════════════════════════════════════════════

class CapsuleStato:
    APPRENDIMENTO = "APPRENDIMENTO"  # raccoglie dati — non agisce ancora
    ATTIVA        = "ATTIVA"         # agisce con cautela
    DOMINANTE     = "DOMINANTE"      # ha dimostrato — agisce con forza
    ESAURITA      = "ESAURITA"       # ha smesso di funzionare
    REVOCATA      = "REVOCATA"       # revocata manualmente o da autorevoca

# Colori per dashboard
COLORI_STATO = {
    CapsuleStato.APPRENDIMENTO: "#f59e0b",   # arancione
    CapsuleStato.ATTIVA:        "#3b82f6",   # blu
    CapsuleStato.DOMINANTE:     "#00ff88",   # verde
    CapsuleStato.ESAURITA:      "#6b7280",   # grigio
    CapsuleStato.REVOCATA:      "#ff3355",   # rosso
}


# ═══════════════════════════════════════════════════════════════════════════
# CAPSULE
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Capsule:
    """
    Una capsula — regola adattiva con stato e ciclo di vita.
    
    Modifica i parametri di una skill in condizioni specifiche.
    Si autorevoca se il risultato è negativo.
    """
    id:            str
    skill:         str           # ENTRY | EXIT | REGIME | DIRECTION
    parametro:     str           # quale parametro modifica
    valore:        float         # il nuovo valore
    condizione:    str           # es. "regime == EXPLOSIVE and oi_carica > 0.80"
    nato_da:       str           # origine: "Signal Tracker", "Manual", "AutoGen"
    vita_secs:     int   = 3600  # durata massima in secondi
    min_trades:    int   = 3     # trade minimi prima di valutare
    
    # Auto-revoca
    autorevoca_se: str   = ""    # es. "pnl_ultimi_5 < -10"
    
    # Stato
    stato:         str   = field(default=CapsuleStato.APPRENDIMENTO)
    ts_creazione:  float = field(default_factory=time.time)
    ts_attivazione: float = 0.0
    
    # Metriche
    attivazioni:   int   = 0
    trade_post:    list  = field(default_factory=list)  # PnL trade dopo attivazione
    pnl_totale:    float = 0.0

    # Delta score — per capsule che modificano lo score entry
    delta_score:   float = 0.0

    def is_active(self) -> bool:
        return self.stato in (CapsuleStato.ATTIVA, CapsuleStato.DOMINANTE)

    def is_expired(self) -> bool:
        return time.time() - self.ts_creazione > self.vita_secs

    def check_condizione(self, context: dict) -> bool:
        """Valuta la condizione della capsule."""
        try:
            return bool(eval(self.condizione, {}, context))
        except Exception:
            return False

    def registra_trade(self, pnl: float):
        """Registra il risultato di un trade avvenuto mentre la capsule era attiva."""
        self.trade_post.append(pnl)
        self.pnl_totale += pnl
        self._aggiorna_stato()

    def _aggiorna_stato(self):
        """Aggiorna lo stato in base ai risultati."""
        n = len(self.trade_post)
        if n < self.min_trades:
            return

        wins = sum(1 for p in self.trade_post if p > 0)
        wr   = wins / n

        if self.stato == CapsuleStato.APPRENDIMENTO and n >= self.min_trades:
            self.stato = CapsuleStato.ATTIVA
            self.ts_attivazione = time.time()
            log.info(f"[CAPSULE] {self.id} → ATTIVA (n={n} WR={wr:.0%})")

        if self.stato == CapsuleStato.ATTIVA and n >= 10 and wr >= 0.65:
            self.stato = CapsuleStato.DOMINANTE
            log.info(f"[CAPSULE] {self.id} → DOMINANTE (n={n} WR={wr:.0%})")

        # Auto-revoca se WR < 35% su 5+ trade
        if n >= 5 and wr < 0.35:
            self.stato = CapsuleStato.REVOCATA
            log.warning(f"[CAPSULE] {self.id} → REVOCATA (n={n} WR={wr:.0%} pnl={self.pnl_totale:+.2f})")

    def to_dict(self) -> dict:
        n    = len(self.trade_post)
        wins = sum(1 for p in self.trade_post if p > 0)
        wr   = wins / n if n > 0 else 0
        return {
            "id":           self.id,
            "skill":        self.skill,
            "parametro":    self.parametro,
            "valore":       self.valore,
            "condizione":   self.condizione,
            "nato_da":      self.nato_da,
            "stato":        self.stato,
            "colore":       COLORI_STATO.get(self.stato, "#ffffff"),
            "attivazioni":  self.attivazioni,
            "trades":       n,
            "wr":           round(wr * 100, 1),
            "pnl":          round(self.pnl_totale, 2),
            "eta_secs":     round(time.time() - self.ts_creazione),
            "vita_secs":    self.vita_secs,
            "vita_pct":     round((time.time() - self.ts_creazione) / self.vita_secs * 100, 1),
            "delta_score":  self.delta_score,
            "expired":      self.is_expired(),
        }


# ═══════════════════════════════════════════════════════════════════════════
# CAPSULE ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class CapsuleEngine:
    """
    Gestisce il ciclo di vita di tutte le capsule.
    
    - Valuta condizioni ogni tick
    - Applica modifiche alle skill
    - Traccia risultati
    - Genera nuove capsule da pattern emergenti
    """

    def __init__(self, db_path: Optional[str] = None):
        self._capsule: list  = []
        self._lock           = __import__("threading").RLock()
        self._db_path        = db_path
        self._tick_count     = 0
        self._last_context:  dict = {}

    def add(self, capsule: Capsule):
        """Aggiungi una capsule."""
        with self._lock:
            # Rimuovi eventuale duplicato con stesso ID
            self._capsule = [c for c in self._capsule if c.id != capsule.id]
            self._capsule.append(capsule)
            log.info(f"[CAPSULE_ENGINE] + {capsule.id} [{capsule.stato}] cond={capsule.condizione}")

    def on_tick(self, context: dict, skills: dict):
        """
        Chiamato ogni tick.
        Valuta condizioni e applica modifiche alle skill.
        
        context: {"regime": "EXPLOSIVE", "oi_stato": "FUOCO", "oi_carica": 0.95, ...}
        skills:  {"ENTRY": skill_entry, "EXIT": skill_exit, ...}
        """
        with self._lock:
            self._tick_count += 1
            self._last_context = context
            active_ids = []

            for cap in self._capsule:
                # Salta esaurite/revocate/scadute
                if not cap.is_active() and cap.stato != CapsuleStato.APPRENDIMENTO:
                    continue
                if cap.is_expired():
                    cap.stato = CapsuleStato.ESAURITA
                    log.info(f"[CAPSULE_ENGINE] {cap.id} → ESAURITA (vita={cap.vita_secs}s)")
                    continue

                # Valuta condizione
                if cap.check_condizione(context):
                    cap.attivazioni += 1
                    active_ids.append(cap.id)

                    # Applica modifica alla skill
                    skill = skills.get(cap.skill)
                    if skill and cap.parametro:
                        skill.set_param(cap.parametro, cap.valore, fonte=cap.id)

            return active_ids

    def on_trade_closed(self, pnl: float, context: dict):
        """
        Notifica chiusura trade — aggiorna tutte le capsule attive o in apprendimento.
        """
        with self._lock:
            for cap in self._capsule:
                # Aggiorna anche capsule in APPRENDIMENTO — raccolgono dati
                if cap.stato in (CapsuleStato.APPRENDIMENTO, CapsuleStato.ATTIVA, CapsuleStato.DOMINANTE):
                    if cap.check_condizione(context):
                        cap.registra_trade(pnl)

    def get_active_modifiers(self, skill: str, regime: str, direction: str) -> list:
        """
        Restituisce modificatori attivi per una skill in un contesto.
        Usato da SkillEntry per applicare bonus/malus allo score.
        """
        mods = []
        ctx  = {"regime": regime, "direction": direction}
        with self._lock:
            for cap in self._capsule:
                if cap.skill == skill and cap.is_active():
                    if cap.check_condizione({**ctx, **self._last_context}):
                        mods.append(cap.to_dict())
        return mods

    def get_all(self) -> list:
        """Restituisce tutte le capsule per la dashboard."""
        with self._lock:
            return [c.to_dict() for c in self._capsule]

    def get_by_stato(self, stato: str) -> list:
        with self._lock:
            return [c.to_dict() for c in self._capsule if c.stato == stato]

    def remove_expired(self):
        """Pulizia periodica."""
        with self._lock:
            before = len(self._capsule)
            self._capsule = [c for c in self._capsule
                             if c.stato not in (CapsuleStato.ESAURITA, CapsuleStato.REVOCATA)
                             or not c.is_expired()]
            after = len(self._capsule)
            if before != after:
                log.info(f"[CAPSULE_ENGINE] Pulizia: {before - after} capsule rimosse")

    def stats(self) -> dict:
        with self._lock:
            by_stato = {}
            for c in self._capsule:
                by_stato[c.stato] = by_stato.get(c.stato, 0) + 1
            return {
                "total":   len(self._capsule),
                "by_stato": by_stato,
                "colors":   COLORI_STATO,
            }
