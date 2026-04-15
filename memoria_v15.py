"""
OVERTOP V16 — MEMORIA V15
===========================
Converte tutti i dati V15 in formato V16.
Caricato al boot — nessun DB richiesto.

Contiene:
- 31 fingerprint Oracolo con WR reali
- 8 capsule STATIC calibrate su BTC
- Signal Tracker 500+ osservazioni
- Comparti pre-tarati sui dati reali
"""

import logging
log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# FINGERPRINT ORACOLO V15 — 31 contesti
# ═══════════════════════════════════════════════════════════════

FINGERPRINT_V15 = {
    "LONG|DEBOLE|ALTA|SIDEWAYS":  {"wr": 0.12, "real": 0,  "pnl_avg": -5.04, "samples": 30},
    "LONG|DEBOLE|BASSA|SIDEWAYS": {"wr": 0.42, "real": 6,  "pnl_avg": -0.44, "samples": 7.6},
    "LONG|DEBOLE|BASSA|UP":       {"wr": 0.55, "real": 0,  "pnl_avg":  2.35, "samples": 10},
    "LONG|DEBOLE|MEDIA|SIDEWAYS": {"wr": 0.35, "real": 0,  "pnl_avg": -2.15, "samples": 8.8},
    "LONG|FORTE|ALTA|SIDEWAYS":   {"wr": 0.35, "real": 0,  "pnl_avg": -3.80, "samples": 37.5},
    "LONG|FORTE|ALTA|UP":         {"wr": 0.55, "real": 0,  "pnl_avg":  8.20, "samples": 11.2},
    "LONG|FORTE|BASSA|DOWN":      {"wr": 0.60, "real": 0,  "pnl_avg":  2.80, "samples": 7.5},
    "LONG|FORTE|BASSA|SIDEWAYS":  {"wr": 0.65, "real": 0,  "pnl_avg":  5.70, "samples": 10},
    "LONG|FORTE|BASSA|UP":        {"wr": 0.78, "real": 0,  "pnl_avg": 15.40, "samples": 30},
    "LONG|FORTE|MEDIA|DOWN":      {"wr": 0.50, "real": 0,  "pnl_avg":  0.50, "samples": 5},
    "LONG|FORTE|MEDIA|SIDEWAYS":  {"wr": 0.60, "real": 0,  "pnl_avg":  3.20, "samples": 12.5},
    "LONG|FORTE|MEDIA|UP":        {"wr": 0.68, "real": 0,  "pnl_avg":  8.00, "samples": 22.5},
    "LONG|MEDIO|ALTA|SIDEWAYS":   {"wr": 0.28, "real": 0,  "pnl_avg": -4.20, "samples": 37.5},
    "LONG|MEDIO|ALTA|UP":         {"wr": 0.50, "real": 0,  "pnl_avg":  3.00, "samples": 8.8},
    "LONG|MEDIO|BASSA|DOWN":      {"wr": 0.45, "real": 0,  "pnl_avg": -0.25, "samples": 6.2},
    "LONG|MEDIO|BASSA|SIDEWAYS":  {"wr": 0.50, "real": 0,  "pnl_avg":  0.50, "samples": 7.5},
    "LONG|MEDIO|BASSA|UP":        {"wr": 0.65, "real": 0,  "pnl_avg":  6.30, "samples": 18.8},
    "LONG|MEDIO|MEDIA|SIDEWAYS":  {"wr": 0.45, "real": 0,  "pnl_avg": -0.70, "samples": 11.2},
    "LONG|MEDIO|MEDIA|UP":        {"wr": 0.58, "real": 0,  "pnl_avg":  3.60, "samples": 13.8},
    "SHORT|DEBOLE|ALTA|DOWN":     {"wr": 0.40, "real": 0,  "pnl_avg": -1.20, "samples": 6.2},
    "SHORT|DEBOLE|ALTA|SIDEWAYS": {"wr": 0.10, "real": 0,  "pnl_avg": -6.00, "samples": 20},
    "SHORT|DEBOLE|BASSA|SIDEWAYS":{"wr": 0.00, "real": 3,  "pnl_avg": -1.88, "samples": 2.9},
    "SHORT|DEBOLE|MEDIA|SIDEWAYS":{"wr": 0.00, "real": 3,  "pnl_avg": -2.39, "samples": 2.9},
    "SHORT|FORTE|ALTA|DOWN":      {"wr": 0.55, "real": 0,  "pnl_avg":  5.40, "samples": 10},
    "SHORT|FORTE|ALTA|SIDEWAYS":  {"wr": 0.12, "real": 0,  "pnl_avg": -7.44, "samples": 25},
    "SHORT|FORTE|MEDIA|SIDEWAYS": {"wr": 0.25, "real": 0,  "pnl_avg": -4.50, "samples": 12.5},
    "SHORT|MEDIO|ALTA|DOWN":      {"wr": 0.48, "real": 0,  "pnl_avg":  2.04, "samples": 8.8},
    "SHORT|MEDIO|ALTA|SIDEWAYS":  {"wr": 0.11, "real": 3,  "pnl_avg": -6.42, "samples": 24.3},
    "SHORT|MEDIO|MEDIA|SIDEWAYS": {"wr": 0.20, "real": 0,  "pnl_avg": -4.60, "samples": 15},
}


# ═══════════════════════════════════════════════════════════════
# CAPSULE STATIC V15 — 8 veto calibrati su BTC
# ═══════════════════════════════════════════════════════════════

CAPSULE_STATIC_V15 = [
    {
        "id":        "STATIC_LONG_DEBOLE_ALTA_DOWN",
        "condizione":"momentum=='DEBOLE' and volatilita=='ALTA' and trend=='DOWN' and direction=='LONG'",
        "wr":        0.05, "samples": 74, "hits": 0,
        "descrizione": "TRAP — WR 5% su 74 campioni BTC",
        "delta_score": -100,
    },
    {
        "id":        "STATIC_LONG_FORTE_ALTA_DOWN",
        "condizione":"momentum=='FORTE' and volatilita=='ALTA' and trend=='DOWN' and direction=='LONG'",
        "wr":        0.15, "samples": 52, "hits": 0,
        "descrizione": "PANIC — WR 15% su 52 campioni BTC",
        "delta_score": -100,
    },
    {
        "id":        "STATIC_LONG_DEBOLE_ALTA_SIDEWAYS",
        "condizione":"momentum=='DEBOLE' and volatilita=='ALTA' and trend=='SIDEWAYS' and direction=='LONG'",
        "wr":        0.19, "samples": 74, "hits": 32058,
        "descrizione": "RANGE_VOL_W — WR 19% su 74 campioni — 32k hits",
        "delta_score": -100,
    },
    {
        "id":        "STATIC_LONG_MEDIO_ALTA_SIDEWAYS",
        "condizione":"momentum=='MEDIO' and volatilita=='ALTA' and trend=='SIDEWAYS' and direction=='LONG'",
        "wr":        0.28, "samples": 41, "hits": 3602,
        "descrizione": "RANGE_VOL_M — WR 28% su 41 campioni",
        "delta_score": -100,
    },
    {
        "id":        "STATIC_LONG_FORTE_ALTA_SIDEWAYS",
        "condizione":"momentum=='FORTE' and volatilita=='ALTA' and trend=='SIDEWAYS' and direction=='LONG'",
        "wr":        0.34, "samples": 48, "hits": 0,
        "descrizione": "RANGE_VOL_F — WR 34% su 48 campioni",
        "delta_score": -50,
    },
    {
        "id":        "STATIC_SHORT_FORTE_BASSA_UP",
        "condizione":"momentum=='FORTE' and volatilita=='BASSA' and trend=='UP' and direction=='SHORT'",
        "wr":        0.05, "samples": 38, "hits": 0,
        "descrizione": "STRONG_BULL SHORT — WR 5% su 38 campioni",
        "delta_score": -100,
    },
    {
        "id":        "STATIC_SHORT_FORTE_MEDIA_UP",
        "condizione":"momentum=='FORTE' and volatilita=='MEDIA' and trend=='UP' and direction=='SHORT'",
        "wr":        0.12, "samples": 29, "hits": 0,
        "descrizione": "STRONG_MED SHORT — WR 12% su 29 campioni",
        "delta_score": -100,
    },
    {
        "id":        "STATIC_SHORT_DEBOLE_ALTA_SIDEWAYS",
        "condizione":"momentum=='DEBOLE' and volatilita=='ALTA' and trend=='SIDEWAYS' and direction=='SHORT'",
        "wr":        0.10, "samples": 21, "hits": 4064,
        "descrizione": "RANGE_VOL_W SHORT — WR 10% su 21 campioni",
        "delta_score": -100,
    },
]


# ═══════════════════════════════════════════════════════════════
# SIGNAL TRACKER V15 — pattern confermati
# ═══════════════════════════════════════════════════════════════

SIGNAL_TRACKER_V15 = {
    "RANGING|LONG|DEBOLE_<58":   {"n": 9433, "hit_60s": 0.38, "pnl_avg": -0.09, "verdict": "EVITA"},
    "RANGING|SHORT|DEBOLE_<58":  {"n": 1412, "hit_60s": 0.38, "pnl_avg": -0.18, "verdict": "EVITA"},
    "EXPLOSIVE|SHORT|DEBOLE_<58":{"n":  334, "hit_60s": 0.24, "pnl_avg": -0.12, "verdict": "EVITA"},
    "EXPLOSIVE|LONG|DEBOLE_<58": {"n":  213, "hit_60s": 0.50, "pnl_avg": -0.12, "verdict": "CAUTO"},
    "RANGING|SHORT|BASE_58-65":  {"n":   46, "hit_60s": 0.63, "pnl_avg": -0.06, "verdict": "CAUTO"},
    "EXPLOSIVE|LONG|BASE_58-65": {"n":    6, "hit_60s": 0.67, "pnl_avg": -0.41, "verdict": "EVITA"},
}


# ═══════════════════════════════════════════════════════════════
# COMPARTI TARATI SUI DATI REALI
# ═══════════════════════════════════════════════════════════════

# Soglie ottimali derivate dai dati V15:
# - RANGING ALTA VOL: quasi sempre perde → difensivo totale
# - EXPLOSIVE: pnl positivo se score alto → attacco
# - TRENDING: pochissimi dati → cauto

COMPARTI_TUNING_V15 = {
    "DIFENSIVO": {
        "soglia_base":   55,   # alta — entra solo su setup pulito
        "soglia_min":    52,
        "size_default":  0.2,
        "note": "RANGING ALTA VOL: 74 campioni WR 19% → aspetta"
    },
    "NEUTRO": {
        "soglia_base":   50,
        "soglia_min":    48,
        "size_default":  0.3,
        "note": "RANGING normale: entra solo su LONG|FORTE con WR>60%"
    },
    "ATTACCO": {
        "soglia_base":   44,   # bassa — EXPLOSIVE è raro e va colto
        "soglia_min":    40,
        "size_default":  0.5,
        "note": "EXPLOSIVE: colpisci forte e veloce"
    },
    "TRENDING_BULL": {
        "soglia_base":   46,
        "soglia_min":    42,
        "size_default":  0.4,
        "note": "LONG|FORTE|BASSA|UP: WR 78% — cavalca"
    },
    "TRENDING_BEAR": {
        "soglia_base":   52,
        "soglia_min":    48,
        "size_default":  0.3,
        "note": "SHORT: solo con fp_real >= 5 e WR >= 40%"
    },
}


# ═══════════════════════════════════════════════════════════════
# FUNZIONE DI CARICAMENTO
# ═══════════════════════════════════════════════════════════════

def carica_memoria_v15(kernel, capsule_engine, comparto_engine):
    """
    Carica tutta la memoria V15 nel sistema V16 al boot.
    """
    from capsule_engine import Capsule, CapsuleStato
    from comparto_engine import COMPARTI

    # 1. Fingerprint → SkillEntry
    if kernel.skill_entry:
        kernel.skill_entry._params["fingerprints"] = FINGERPRINT_V15
        log.info(f"[MEMORIA_V15] {len(FINGERPRINT_V15)} fingerprint caricati in SkillEntry")

    # 2. Capsule STATIC → CapsuleEngine
    for c_data in CAPSULE_STATIC_V15:
        cap = Capsule(
            id          = c_data["id"],
            skill       = "ENTRY",
            parametro   = "",
            valore      = 0,
            condizione  = c_data["condizione"],
            nato_da     = "V15_STATIC",
            vita_secs   = 999999,
            stato       = CapsuleStato.DOMINANTE,
            delta_score = c_data["delta_score"],
        )
        capsule_engine.add(cap)
    log.info(f"[MEMORIA_V15] {len(CAPSULE_STATIC_V15)} capsule STATIC caricate")

    # 3. Tuning comparti dai dati reali
    for nome, tuning in COMPARTI_TUNING_V15.items():
        if nome in COMPARTI:
            COMPARTI[nome].soglia_base  = tuning["soglia_base"]
            COMPARTI[nome].soglia_min   = tuning["soglia_min"]
            COMPARTI[nome].size_default = tuning["size_default"]
    log.info(f"[MEMORIA_V15] Comparti tarati su dati reali BTC")

    # 4. Signal Tracker → SkillEntry come contesti da evitare
    if kernel.skill_entry:
        kernel.skill_entry._params["signal_tracker"] = SIGNAL_TRACKER_V15
        log.info(f"[MEMORIA_V15] {len(SIGNAL_TRACKER_V15)} contesti Signal Tracker caricati")

    log.info("[MEMORIA_V15] ✅ Caricamento completo — V16 parte con intelligenza V15")
