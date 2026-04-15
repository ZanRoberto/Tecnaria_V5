"""
OVERTOP V16 — SKILL BASE
=========================
Classe base per tutte le skill.
Ogni skill:
  - Riceve tick + kernel
  - Legge parametri dalle capsule
  - Restituisce SkillResult con motivo SEMPRE esplicito
  - Non crasha mai — restituisce fallback in caso di errore
"""

import time
import logging
from kernel import TickData, SkillResult

log = logging.getLogger(__name__)


class BaseSkill:
    """
    Classe base per tutte le skill V16.
    
    Ogni skill figlia implementa _evaluate() — mai evaluate() direttamente.
    Il wrapper evaluate() garantisce:
      - Nessun crash silenzioso
      - Log di ogni chiamata
      - Fallback sicuro in caso di errore
    """

    NAME = "BASE"

    def __init__(self):
        self._params: dict = {}       # parametri modificabili dalle capsule
        self._call_count: int = 0
        self._error_count: int = 0
        self._last_result: SkillResult = SkillResult(ok=True, motivo="init")

    def evaluate(self, tick: TickData, kernel) -> SkillResult:
        """
        Wrapper sicuro — non crasha mai.
        Chiama _evaluate() e gestisce eccezioni.
        """
        self._call_count += 1
        try:
            result = self._evaluate(tick, kernel)
            self._last_result = result
            return result
        except Exception as e:
            self._error_count += 1
            log.error(f"[{self.NAME}] CRASH in evaluate: {e}")
            # Fallback sicuro — non blocca il kernel
            return SkillResult(
                ok=False,
                motivo=f"CRASH_{self.NAME}: {str(e)[:60]}",
                extra={"crash": True, "error": str(e)}
            )

    def _evaluate(self, tick: TickData, kernel) -> SkillResult:
        """Override nelle skill figlie."""
        raise NotImplementedError

    def set_param(self, key: str, value, fonte: str = ""):
        """Modifica un parametro — chiamato dal capsule engine."""
        old = self._params.get(key)
        self._params[key] = value
        log.info(f"[{self.NAME}] param {key}: {old} → {value} [{fonte}]")

    def get_param(self, key: str, default=None):
        """Leggi un parametro con fallback al default."""
        return self._params.get(key, default)

    def get_status(self) -> dict:
        return {
            "skill":        self.NAME,
            "calls":        self._call_count,
            "errors":       self._error_count,
            "params":       self._params,
            "last_motivo":  self._last_result.motivo,
            "last_ok":      self._last_result.ok,
        }


# ═══════════════════════════════════════════════════════════════════════════
# SKILL_HEALTH
# ═══════════════════════════════════════════════════════════════════════════

class SkillHealth(BaseSkill):
    """
    Monitora la salute del sistema.
    Se trova problemi — li ripara autonomamente.
    Se non può ripararli — blocca il kernel finché non sono risolti.
    """

    NAME = "HEALTH"

    def __init__(self):
        super().__init__()
        self._params = {
            "max_errors_per_min":  5,
            "warmup_ticks":       50,
            "max_position_secs": 3600,
        }
        self._error_log: list = []
        self._repairs:   list = []
        self._warmup_done = False

    def _evaluate(self, tick: TickData, kernel) -> SkillResult:
        problems = []

        # 1. Warmup
        if kernel.tick_count < self._params["warmup_ticks"]:
            return SkillResult(
                ok=False,
                motivo=f"WARMUP {kernel.tick_count}/{self._params['warmup_ticks']}",
                valore=kernel.tick_count / self._params["warmup_ticks"]
            )

        # 2. Prezzi anomali
        if tick.price <= 0:
            problems.append("PREZZO_ZERO")

        # 3. Posizione bloccata troppo a lungo
        if kernel.position:
            dur = time.time() - kernel.position.entry_time
            if dur > self._params["max_position_secs"]:
                problems.append(f"POSITION_STUCK_{dur:.0f}s")
                # Auto-repair: forza chiusura
                kernel.position = None
                self._repairs.append({"ts": time.time(), "azione": "FORCE_CLOSE_STUCK"})
                log.warning("[HEALTH] ⚠️ Posizione bloccata — forzata chiusura")

        # 4. Skill mancanti critiche
        if not kernel.skill_entry:
            problems.append("SKILL_ENTRY_MANCANTE")
        if not kernel.skill_exit:
            problems.append("SKILL_EXIT_MANCANTE")

        if problems:
            return SkillResult(
                ok=False,
                motivo=" | ".join(problems),
                extra={"problems": problems}
            )

        return SkillResult(ok=True, motivo="OK", valore=1.0)


# ═══════════════════════════════════════════════════════════════════════════
# SKILL_REGIME
# ═══════════════════════════════════════════════════════════════════════════

class SkillRegime(BaseSkill):
    """
    Rileva il regime di mercato.
    Output: RANGING | EXPLOSIVE | TRENDING_BULL | TRENDING_BEAR
    """

    NAME = "REGIME"

    def __init__(self):
        super().__init__()
        self._params = {
            "window":          200,
            "dir_ratio_trend": 0.52,
            "trend_pct":       0.003,   # 0.3% per considerare trend
            "explosive_mult":  1.8,     # volatilità > 1.8x media = EXPLOSIVE
        }
        self._prices:  list = []
        self._current: str  = "RANGING"
        self._conf:    float = 0.0

    def _evaluate(self, tick: TickData, kernel) -> SkillResult:
        self._prices.append(tick.price)
        w = self._params["window"]
        if len(self._prices) > w:
            self._prices = self._prices[-w:]

        if len(self._prices) < 20:
            return SkillResult(ok=True, motivo=f"WARMUP_REGIME {len(self._prices)}/20",
                               extra={"regime": "RANGING"}, valore=0.0)

        prices = self._prices
        n = len(prices)

        # Direzione: quante candele salgono
        ups   = sum(1 for i in range(1, n) if prices[i] > prices[i-1])
        dir_r = ups / (n - 1)

        # Trend: variazione totale
        trend_pct = (prices[-1] - prices[0]) / prices[0]

        # Volatilità: std degli ultimi 20 vs std globale
        def std(lst):
            m = sum(lst) / len(lst)
            return (sum((x-m)**2 for x in lst) / len(lst)) ** 0.5

        vol_now  = std(prices[-20:]) / prices[-1]
        vol_full = std(prices)       / prices[-1] if len(prices) >= 40 else vol_now

        explosive_mult = self._params["explosive_mult"]
        trend_thresh   = self._params["trend_pct"]
        dir_thresh     = self._params["dir_ratio_trend"]

        if vol_full > 0 and vol_now > vol_full * explosive_mult:
            regime = "EXPLOSIVE"
            conf   = min(1.0, vol_now / (vol_full * explosive_mult))
        elif abs(trend_pct) > trend_thresh and dir_r > dir_thresh:
            regime = "TRENDING_BULL" if trend_pct > 0 else "TRENDING_BEAR"
            conf   = min(1.0, abs(trend_pct) / (trend_thresh * 2))
        else:
            regime = "RANGING"
            conf   = 1.0 - abs(trend_pct) / max(trend_thresh, 0.001)

        self._current = regime
        self._conf    = round(conf, 2)
        kernel.heartbeat["regime"]      = regime
        kernel.heartbeat["regime_conf"] = self._conf

        # Volatilità
        vol_str = "ALTA" if vol_full > 0 and vol_now > vol_full * 1.2 else                   "BASSA" if vol_now < vol_full * 0.7 else "MEDIA"

        # Trend stringa
        trend_str = "UP" if trend_pct > trend_thresh/2 else                     "DOWN" if trend_pct < -trend_thresh/2 else "SIDEWAYS"

        kernel.heartbeat["volatilita"] = vol_str
        kernel.heartbeat["trend_str"]  = trend_str

        return SkillResult(
            ok=True,
            motivo=f"{regime} conf={self._conf:.0%}",
            valore=self._conf,
            extra={"regime": regime, "conf": self._conf,
                   "dir_ratio": round(dir_r, 2), "trend_pct": round(trend_pct, 4),
                   "volatilita": vol_str, "trend": trend_str}
        )


# ═══════════════════════════════════════════════════════════════════════════
# SKILL_DIRECTION
# ═══════════════════════════════════════════════════════════════════════════

class SkillDirection(BaseSkill):
    """
    Decide la direzione: LONG o SHORT.
    Basata su momentum, EMA, RSI.
    """

    NAME = "DIRECTION"

    def __init__(self):
        super().__init__()
        self._params = {
            "ema_fast":         12,
            "ema_slow":         26,
            "rsi_period":       14,
            "flip_cooldown":    120,   # secondi minimo tra flip
            "bullish_threshold": 0.55,
        }
        self._prices:      list  = []
        self._direction:   str   = "LONG"
        self._last_flip:   float = 0.0
        self._flip_count:  int   = 0

    def _evaluate(self, tick: TickData, kernel) -> SkillResult:
        self._prices.append(tick.price)
        if len(self._prices) > 200:
            self._prices = self._prices[-200:]

        if len(self._prices) < self._params["ema_slow"] + 5:
            return SkillResult(ok=True, motivo=f"WARMUP_DIR {len(self._prices)}",
                               extra={"direction": self._direction})

        prices = self._prices

        # EMA
        def ema(data, period):
            k = 2 / (period + 1)
            e = data[0]
            for p in data[1:]:
                e = p * k + e * (1 - k)
            return e

        fast = self._params["ema_fast"]
        slow = self._params["ema_slow"]
        ema_f = ema(prices[-fast*3:], fast)
        ema_s = ema(prices[-slow*3:], slow)
        bullish = ema_f > ema_s

        # RSI
        period = self._params["rsi_period"]
        if len(prices) >= period + 1:
            gains  = [max(0, prices[i]-prices[i-1]) for i in range(-period, 0)]
            losses = [max(0, prices[i-1]-prices[i]) for i in range(-period, 0)]
            ag = sum(gains)  / period
            al = sum(losses) / period
            rsi = 100 - (100 / (1 + ag/al)) if al > 0 else 50
        else:
            rsi = 50

        # Direzione suggerita
        bullish_score = (1 if bullish else 0) + (1 if rsi > 55 else 0 if rsi < 45 else 0.5)
        new_dir = "LONG" if bullish_score >= self._params["bullish_threshold"] * 2 else "SHORT"

        # Flip con cooldown
        now = time.time()
        if new_dir != self._direction:
            cooldown = self._params["flip_cooldown"]
            if now - self._last_flip < cooldown:
                return SkillResult(
                    ok=True,
                    motivo=f"FLIP_COOLDOWN {cooldown - (now-self._last_flip):.0f}s",
                    extra={"direction": self._direction}
                )
            self._direction = new_dir
            self._last_flip = now
            self._flip_count += 1
            kernel.heartbeat["direction"] = new_dir
            log.info(f"[DIRECTION] FLIP → {new_dir} (EMA_F={ema_f:.0f} EMA_S={ema_s:.0f} RSI={rsi:.0f})")

        kernel.heartbeat["direction"] = self._direction
        return SkillResult(
            ok=True,
            motivo=f"{self._direction} ema={'BULL' if bullish else 'BEAR'} rsi={rsi:.0f}",
            valore=bullish_score / 2,
            extra={"direction": self._direction, "rsi": round(rsi, 1),
                   "ema_bull": bullish, "flip_count": self._flip_count}
        )


# ═══════════════════════════════════════════════════════════════════════════
# SKILL_ENTRY
# ═══════════════════════════════════════════════════════════════════════════

class SkillEntry(BaseSkill):
    """
    Decide se entrare in una posizione.
    Score composito: regime + direzione + OI + fingerprint.
    Nessun gate silenzioso — ogni blocco ha motivo esplicito.
    """

    NAME = "ENTRY"

    def __init__(self):
        super().__init__()
        self._params = {
            "soglia_base":       48.0,
            "soglia_min":        38.0,
            "size_default":      0.3,
            "size_fuoco":        0.5,
            "cooldown_secs":     30,
            "regime_bonus": {
                "EXPLOSIVE":     15.0,
                "TRENDING_BULL": 10.0,
                "TRENDING_BEAR": 10.0,
                "RANGING":        0.0,
            },
        }
        self._last_entry:  float = 0.0
        self._block_log:   list  = []

    def _evaluate(self, tick: TickData, kernel) -> SkillResult:
        now = time.time()

        # Cooldown
        cooldown = self._params["cooldown_secs"]
        if now - self._last_entry < cooldown:
            remaining = cooldown - (now - self._last_entry)
            return SkillResult(ok=False, motivo=f"COOLDOWN {remaining:.0f}s",
                               extra={"soglia": self._params["soglia_base"]})

        # Leggi stato dal kernel/skill
        regime    = kernel.heartbeat.get("regime", "RANGING")
        direction = kernel.heartbeat.get("direction", "LONG")
        oi_stato  = kernel.heartbeat.get("oi_stato", "NEUTRO")
        oi_carica = kernel.heartbeat.get("oi_carica", 0.0)

        # Score composito
        score = 0.0
        motivi = []

        # Regime bonus
        bonus = self._params["regime_bonus"].get(regime, 0)
        score += bonus
        if bonus > 0:
            motivi.append(f"REGIME_{regime}+{bonus}")

        # OI contribution
        if oi_stato == "FUOCO" and oi_carica >= 0.65:
            oi_score = oi_carica * 20
            score += oi_score
            motivi.append(f"OI_FUOCO+{oi_score:.1f}")
        elif oi_stato == "CARICA":
            oi_score = oi_carica * 10
            score += oi_score
            motivi.append(f"OI_CARICA+{oi_score:.1f}")

        # Respiro bonus — entra sull'impulso, non in coda
        if kernel.respiro_engine:
            respiro_bonus = kernel.respiro_engine.get_entry_bonus()
            if respiro_bonus != 0:
                score += respiro_bonus
                fase = kernel.heartbeat.get("respiro", {}).get("fase", "NEUTRO")
                motivi.append(f"RESPIRO_{fase}:{respiro_bonus:+.0f}")

        # Capsule bonus/malus
        if kernel.capsule_engine:
            caps = kernel.capsule_engine.get_active_modifiers("ENTRY", regime, direction)
            for cap in caps:
                score += cap.get("delta_score", 0)
                if cap.get("delta_score"):
                    motivi.append(f"CAP_{cap['id']}:{cap['delta_score']:+.1f}")

        # Soglia
        soglia = self._params["soglia_base"]
        if soglia < self._params["soglia_min"]:
            soglia = self._params["soglia_min"]

        score = round(score, 1)

        kernel.heartbeat["m2_last_score"] = score
        kernel.heartbeat["m2_last_soglia"] = soglia

        if score >= soglia:
            size = self._params["size_fuoco"] if oi_stato == "FUOCO" else self._params["size_default"]
            self._last_entry = now
            return SkillResult(
                ok=True,
                motivo=" | ".join(motivi) if motivi else "SCORE_OK",
                valore=score,
                extra={"soglia": soglia, "size": size, "direction": direction}
            )
        else:
            gap = soglia - score
            reason = f"SCORE_{score:.1f}_vs_{soglia:.1f}_gap={gap:.1f}"
            self._block_log.append({"ts": now, "motivo": reason})
            return SkillResult(
                ok=False,
                motivo=reason,
                valore=score,
                extra={"soglia": soglia, "gap": gap}
            )


# ═══════════════════════════════════════════════════════════════════════════
# SKILL_EXIT
# ═══════════════════════════════════════════════════════════════════════════

class SkillExit(BaseSkill):
    """
    Decide quando chiudere una posizione aperta.
    Trigger: decelerazione momentum, trend inverso, timeout, stop loss.
    """

    NAME = "EXIT"

    def __init__(self):
        super().__init__()
        self._params = {
            "min_hold_secs":    30,
            "max_hold_secs":  1800,   # 30 minuti max
            "stop_loss_pct":   0.02,  # 2%
            "decel_threshold": 0.60,
            "trend_reverse_sensitivity": 0.003,
        }
        self._prices_since_entry: list = []

    def _evaluate(self, tick: TickData, kernel) -> SkillResult:
        if not kernel.position:
            return SkillResult(ok=False, motivo="NO_POSITION")

        pos = kernel.position
        now = time.time()
        dur = now - pos.entry_time
        price = tick.price

        self._prices_since_entry.append(price)
        if len(self._prices_since_entry) > 200:
            self._prices_since_entry = self._prices_since_entry[-200:]

        # Min hold
        if dur < self._params["min_hold_secs"]:
            return SkillResult(ok=False, motivo=f"MIN_HOLD {dur:.0f}/{self._params['min_hold_secs']}s")

        # Stop loss
        if pos.direction == "LONG":
            move = (price - pos.entry_price) / pos.entry_price
        else:
            move = (pos.entry_price - price) / pos.entry_price

        if move < -self._params["stop_loss_pct"]:
            return SkillResult(ok=True, motivo=f"STOP_LOSS {move:.2%}",
                               valore=move, extra={"trigger": "STOP_LOSS"})

        # Timeout
        if dur > self._params["max_hold_secs"]:
            return SkillResult(ok=True, motivo=f"TIMEOUT {dur:.0f}s",
                               extra={"trigger": "TIMEOUT"})

        # Trend inverso
        if len(self._prices_since_entry) >= 10:
            recent = self._prices_since_entry[-10:]
            trend  = (recent[-1] - recent[0]) / recent[0]
            reverse_thresh = self._params["trend_reverse_sensitivity"]
            if pos.direction == "LONG" and trend < -reverse_thresh:
                return SkillResult(ok=True, motivo=f"TREND_REVERSE {trend:.3%}",
                                   extra={"trigger": "TREND_REVERSE"})
            elif pos.direction == "SHORT" and trend > reverse_thresh:
                return SkillResult(ok=True, motivo=f"TREND_REVERSE {trend:.3%}",
                                   extra={"trigger": "TREND_REVERSE"})

        return SkillResult(ok=False, motivo=f"HOLD move={move:.2%} dur={dur:.0f}s")
