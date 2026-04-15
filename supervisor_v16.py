"""
OVERTOP V16 — SUPERVISOR AI
==============================
Legge lo status ogni 30 secondi.
Capisce cosa sta succedendo.
Agisce direttamente — non suggerisce.

Flusso:
  1. Legge heartbeat kernel
  2. Analizza: comparto giusto? capsule corrette? pattern di perdita?
  3. Se trova incongruenza → interviene subito
  4. Loga ogni decisione con motivo

Non usa DeepSeek per decidere cosa fare.
Usa DeepSeek solo per narrativa — spiegare all'utente in italiano.
"""

import time
import threading
import logging
import os
import json
import urllib.request
from datetime import datetime

log = logging.getLogger(__name__)

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
CALL_INTERVAL    = 30   # secondi tra analisi


class SupervisorV16:
    """
    Supervisore autonomo V16.
    Legge kernel, agisce su comparti e capsule, spiega all'utente.
    """

    def __init__(self, kernel, capsule_engine, comparto_engine):
        self.kernel          = kernel
        self.capsule_engine  = capsule_engine
        self.comparto_engine = comparto_engine

        self._log:      list  = []
        self._lock            = threading.RLock()
        self._last_call: float = 0
        self._interventi: int  = 0
        self._narrativa:  str  = "Supervisore in avvio..."
        self._alert:      str  = "grey"

    # ─────────────────────────────────────────────────────────
    # LOOP PRINCIPALE
    # ─────────────────────────────────────────────────────────

    def start(self):
        t = threading.Thread(target=self._loop, daemon=True, name="supervisor_v16")
        t.start()
        log.info("[SUPERVISOR_V16] Avviato — analisi ogni 30s")

    def _loop(self):
        time.sleep(15)  # boot delay
        while True:
            try:
                self._ciclo()
            except Exception as e:
                log.error(f"[SUPERVISOR_V16] {e}")
            time.sleep(CALL_INTERVAL)

    # ─────────────────────────────────────────────────────────
    # CICLO DI ANALISI
    # ─────────────────────────────────────────────────────────

    def _ciclo(self):
        hb     = self.kernel.heartbeat
        stats  = self.kernel.get_stats()
        regime = hb.get("regime", "UNKNOWN")
        vol    = hb.get("volatilita", "MEDIA")
        trend  = hb.get("trend_str", "SIDEWAYS")
        score  = hb.get("m2_last_score", 0)
        soglia = hb.get("m2_last_soglia", 48)
        pnl    = stats["pnl"]
        wr     = stats["wr"]
        trades = stats["trades"]
        comp   = self.comparto_engine.get_attivo()
        comp_nome = comp.get("nome", "NEUTRO")

        problemi  = []
        azioni    = []

        # ── REGOLA 1: Perdita consecutiva nel comparto ────────
        trades_list = self.kernel.trades[-5:] if self.kernel.trades else []
        loss_streak = sum(1 for t in reversed(trades_list)
                         if t.get("pnl", 0) < 0)
        if loss_streak >= 3:
            problemi.append(f"LOSS_STREAK_{loss_streak} nel comparto {comp_nome}")
            # Genera capsule di blocco per il contesto corrente
            ctx_key = f"{regime}|{hb.get('direction','LONG')}|BLOCK_STREAK"
            self._genera_capsule_blocco(ctx_key, loss_streak, regime, vol, trend)
            azioni.append(f"Capsule blocco generata per {ctx_key}")

        # ── REGOLA 2: Comparto sbagliato per il mercato ───────
        comp_atteso = self._comparto_atteso(regime, vol, trend)
        if comp_nome != comp_atteso:
            problemi.append(f"COMPARTO_SBAGLIATO: attivo={comp_nome} atteso={comp_atteso}")
            # Forza switch comparto
            skills = {
                "ENTRY": self.kernel.skill_entry,
                "EXIT":  self.kernel.skill_exit,
            }
            self.comparto_engine._switch_cooldown = 0  # azzera cooldown
            self.comparto_engine.on_tick(regime, vol, trend, skills)
            azioni.append(f"Switch forzato → {comp_atteso}")

        # ── REGOLA 3: Score sempre sotto soglia da troppo ─────
        if score < soglia * 0.7 and trades == 0 and self.kernel.tick_count > 1000:
            problemi.append(f"SCORE_BASSO: {score:.1f} vs {soglia:.1f} da {self.kernel.tick_count} tick")
            # Abbassa soglia di 2 punti
            if self.kernel.skill_entry:
                current = self.kernel.skill_entry.get_param("soglia_base", soglia)
                if current > 44:
                    self.kernel.skill_entry.set_param("soglia_base", current - 2,
                                                       fonte="SUPERVISOR_V16")
                    azioni.append(f"Soglia abbassata {current:.0f} → {current-2:.0f}")

        # ── REGOLA 4: WR troppo basso su N trade ─────────────
        if trades >= 5 and wr < 20:
            problemi.append(f"WR_CRITICO: {wr:.0f}% su {trades} trade")
            # Blocca SHORT se i loss sono tutti SHORT
            short_losses = sum(1 for t in self.kernel.trades
                              if "SHORT" in t.get("direction","") and t.get("pnl",0) < 0)
            if short_losses >= 3:
                self._blocca_short_temporaneo()
                azioni.append("SHORT bloccato — troppi loss consecutivi")

        # ── REGOLA 5: Crash o errori nel log ─────────────────
        skill_log = hb.get("skill_log", [])
        crash = any("CRASH" in str(l) or "ERRORE" in str(l) for l in skill_log)
        if crash:
            problemi.append("CRASH rilevato nel log skill")
            azioni.append("Allerta critica — verifica deploy")

        # ── Narrativa DeepSeek (solo se ci sono problemi) ────
        if problemi and DEEPSEEK_API_KEY:
            narrativa = self._chiedi_deepseek(problemi, azioni, hb, stats)
        elif not problemi:
            narrativa = self._narrativa_ok(regime, comp_nome, score, soglia, pnl)
        else:
            narrativa = f"Problemi: {' | '.join(problemi)} → Azioni: {' | '.join(azioni)}"

        # ── Log e stato ───────────────────────────────────────
        alert = "red" if crash or (wr < 20 and trades >= 5) else \
                "yellow" if problemi else "green"

        entry = {
            "ts":         datetime.utcnow().strftime("%H:%M:%S"),
            "regime":     regime,
            "comparto":   comp_nome,
            "score":      round(score, 1),
            "soglia":     round(soglia, 1),
            "pnl":        round(pnl, 2),
            "wr":         round(wr, 1),
            "trades":     trades,
            "problemi":   problemi,
            "azioni":     azioni,
            "narrativa":  narrativa,
            "alert":      alert,
        }

        with self._lock:
            self._log.append(entry)
            if len(self._log) > 100:
                self._log.pop(0)
            self._narrativa  = narrativa
            self._alert      = alert
            self._last_call  = time.time()
            if azioni:
                self._interventi += len(azioni)

        if problemi:
            log.warning(f"[SUPERVISOR_V16] {' | '.join(problemi)}")
        if azioni:
            log.info(f"[SUPERVISOR_V16] Azioni: {' | '.join(azioni)}")

    # ─────────────────────────────────────────────────────────
    # LOGICA INTERNA
    # ─────────────────────────────────────────────────────────

    def _comparto_atteso(self, regime, vol, trend) -> str:
        if regime == "EXPLOSIVE":
            return "ATTACCO"
        if regime == "TRENDING_BULL":
            return "TRENDING_BULL"
        if regime == "TRENDING_BEAR":
            return "TRENDING_BEAR"
        if regime == "RANGING" and vol == "ALTA":
            return "DIFENSIVO"
        return "NEUTRO"

    def _genera_capsule_blocco(self, ctx_key, streak, regime, vol, trend):
        from capsule_engine import Capsule, CapsuleStato
        cap_id = f"AUTO_BLOCK_{regime}_{vol}_{trend}_{int(time.time())}"
        # Evita duplicati
        existing = [c for c in self.capsule_engine.get_all() if regime in c["id"] and "AUTO_BLOCK" in c["id"]]
        if existing:
            return
        cap = Capsule(
            id          = cap_id,
            skill       = "ENTRY",
            parametro   = "",
            valore      = 0,
            condizione  = f"regime == '{regime}'",
            nato_da     = f"SUPERVISOR_V16 streak={streak}",
            vita_secs   = 1800,  # 30 minuti
            stato       = CapsuleStato.ATTIVA,
            delta_score = -30,
        )
        self.capsule_engine.add(cap)
        log.info(f"[SUPERVISOR_V16] Capsule auto-blocco: {cap_id}")

    def _blocca_short_temporaneo(self):
        if self.kernel.skill_entry:
            self.kernel.skill_entry.set_param("short_ok", False,
                                               fonte="SUPERVISOR_V16_SHORT_BLOCK")

    def _narrativa_ok(self, regime, comparto, score, soglia, pnl) -> str:
        gap = soglia - score
        if gap > 10:
            return (f"Sistema in {comparto} — {regime}. "
                    f"Score {score:.0f}/{soglia:.0f} — attendo setup migliore. "
                    f"PnL: {'+'if pnl>=0 else ''}{pnl:.2f}$")
        elif gap <= 0:
            return f"Score sopra soglia — pronto per entry. Comparto {comparto} attivo."
        else:
            return (f"{comparto} attivo — gap {gap:.0f} punti alla soglia. "
                    f"Mercato {regime}.")

    def _chiedi_deepseek(self, problemi, azioni, hb, stats) -> str:
        prompt = f"""Sei il supervisore del bot OVERTOP V16.

STATO ATTUALE:
- Regime: {hb.get('regime')} | Comparto: {self.comparto_engine.get_attivo().get('nome')}
- Score: {hb.get('m2_last_score',0):.1f} / Soglia: {hb.get('m2_last_soglia',0):.1f}
- Trade: {stats['trades']} | WR: {stats['wr']:.0f}% | PnL: ${stats['pnl']:+.2f}

PROBLEMI RILEVATI:
{chr(10).join('- '+p for p in problemi)}

AZIONI GIÀ APPLICATE:
{chr(10).join('- '+a for a in azioni)}

Spiega in 2 righe max cosa sta succedendo e perché le azioni sono corrette.
Tono: diretto, tecnico, italiano. Niente fronzoli."""

        try:
            payload = json.dumps({
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 150
            }).encode()
            req = urllib.request.Request(
                "https://api.deepseek.com/v1/chat/completions",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
                }
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            return f"Problemi: {' | '.join(problemi)} → {' | '.join(azioni)}"

    # ─────────────────────────────────────────────────────────
    # API PUBBLICA
    # ─────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        with self._lock:
            return {
                "narrativa":    self._narrativa,
                "alert":        self._alert,
                "interventi":   self._interventi,
                "ultimo_ciclo": datetime.utcfromtimestamp(self._last_call).strftime("%H:%M:%S") if self._last_call else "—",
                "log":          list(reversed(self._log[-20:])),
            }
