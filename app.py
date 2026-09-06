from flask import Flask, jsonify
import os
import requests
import re

app = Flask(__name__)

# =========================================================
# CONFIGURAÇÃO
# =========================================================

SPORTS_API_KEY = os.environ.get("SPORTS_API_KEY")

SPORTS_API_BASE = os.environ.get(
    "SPORTS_API_URL",
    "https://sportsapi.com.br/api/v1"
)


# =========================================================
# SPORTS API
# =========================================================

def sportsapi_get(endpoint, params=None):
    if not SPORTS_API_KEY:
        raise RuntimeError("SPORTS_API_KEY não configurada")

    response = requests.get(
        f"{SPORTS_API_BASE}{endpoint}",
        headers={
            "X-API-Key": SPORTS_API_KEY,
            "Accept": "application/json",
        },
        params=params,
        timeout=20,
    )

    response.raise_for_status()
    return response.json()


# =========================================================
# FUNÇÕES AUXILIARES
# =========================================================

def get_display(match):
    return str(
        match.get("gameTimeDisplay")
        or match.get("exibiçãoHorárioDoJogo")
        or match.get("exibiçãoHorárioDeJogo")
        or match.get("exibiçãoDoJogo")
        or ""
    ).strip()


def get_raw_status(match):
    return str(
        match.get("status")
        or match.get("estado")
        or ""
    ).strip().lower()


def detect_minute(display):
    """
    Exemplos aceitos:
    23'
    45+2'
    67 min
    90+5
    """

    if not display:
        return None

    text = display.lower().strip()

    patterns = [
        r"\b(\d{1,3})\s*'",
        r"\b(\d{1,3})\s*min",
        r"\b(\d{1,3})\+(\d{1,2})\s*'?",
    ]

    for pattern in patterns:
        result = re.search(pattern, text)

        if result:
            try:
                return int(result.group(1))
            except Exception:
                pass

    return None


# =========================================================
# STATUS REAL
# =========================================================

def normalize_status(match):

    display = get_display(match)
    display_lower = display.lower()

    status = get_raw_status(match)

    # -------------------------
    # ENCERRADO
    # -------------------------

    finished_words = [
        "fim de jogo",
        "finalizado",
        "encerrado",
        "finished",
        "full time",
        "full-time",
        "ft",
    ]

    if any(word == display_lower for word in finished_words):
        return "finished"

    if status in [
        "finished",
        "finalizado",
        "encerrado",
    ]:
        return "finished"

    # -------------------------
    # INTERVALO
    # -------------------------

    halftime_words = [
        "intervalo",
        "half time",
        "half-time",
        "ht",
    ]

    if any(word == display_lower for word in halftime_words):
        return "live"

    # -------------------------
    # MINUTO DE JOGO
    # -------------------------

    minute = detect_minute(display)

    if minute is not None and 0 <= minute <= 130:
        return "live"

    # -------------------------
    # OUTROS STATUS
    # -------------------------

    if status in ["scheduled", "agendado"]:
        return "scheduled"

    if status in ["postponed", "adiado"]:
        return "postponed"

    if status in [
        "cancelled",
        "canceled",
        "cancelado",
    ]:
        return "cancelled"

    # IMPORTANTE:
    # não confiamos apenas em status="live"
    # porque a fonte já mostrou partidas encerradas como live.

    return "unknown"


# =========================================================
# NORMALIZAR PARTIDA
# =========================================================

def normalize_match(match):

    home = (
        match.get("homeTeam")
        or match.get("timeCasa")
        or {}
    )

    away = (
        match.get("awayTeam")
        or match.get("timeVisitante")
        or {}
    )

    league = (
        match.get("league")
        or match.get("liga")
        or {}
    )

    home_score = match.get("homeScore")

    if home_score is None:
        home_score = match.get("placarCasa")

    away_score = match.get("awayScore")

    if away_score is None:
        away_score = match.get("placarVisitante")

    if away_score is None:
        away_score = match.get("PontuaçãoFora")

    display = get_display(match)

    return {
        "id": match.get("id"),

        "status": normalize_status(match),

        "rawStatus": get_raw_status(match),

        "gameTimeDisplay": display,

        "minute": detect_minute(display),

        "homeTeam": {
            "name": (
                home.get("name")
                or home.get("nome")
                or "Mandante"
            ),
            "logo": (
                home.get("logo")
                or home.get("logotipo")
                or ""
            ),
        },

        "awayTeam": {
            "name": (
                away.get("name")
                or away.get("nome")
                or "Visitante"
            ),
            "logo": (
                away.get("logo")
                or away.get("logotipo")
                or ""
            ),
        },

        "homeScore": home_score,
        "awayScore": away_score,

        "league": {
            "name": (
                league.get("name")
                or league.get("nome")
                or "Competição"
            )
        },
    }


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    return jsonify({
        "bot": "BetScope Bot",
        "status": "online",
        "version": "2.0",
        "sports_api_key":
            "configurada"
            if SPORTS_API_KEY
            else "não configurada",
    })


# =========================================================
# AO VIVO REAL
# =========================================================

@app.route("/api/live")
def live_games():

    try:

        data = sportsapi_get(
            "/games",
            {
                "sport": "football",
                "status": "live",
                "limit": 100,
            },
        )

        raw_matches = data.get("matches", [])

        live_matches = []

        for raw_match in raw_matches:

            match = normalize_match(raw_match)

            if match["status"] == "live":
                live_matches.append(match)

        return jsonify({
            "cached": data.get("cached", False),
            "matches": live_matches,
            "source_total": data.get(
                "total",
                len(raw_matches)
            ),
            "received": len(raw_matches),
            "total": len(live_matches),
            "timestamp": data.get("timestamp"),
        })

    except requests.HTTPError as error:

        status = (
            error.response.status_code
            if error.response is not None
            else 502
        )

        return jsonify({
            "error": "SportsAPI recusou a requisição",
            "status": status,
        }), status

    except Exception as error:

        return jsonify({
            "error": str(error)
        }), 500


# =========================================================
# DIAGNÓSTICO DA FONTE
# =========================================================

@app.route("/api/debug/live")
def debug_live():

    try:

        data = sportsapi_get(
            "/games",
            {
                "sport": "football",
                "status": "live",
                "limit": 100,
            },
        )

        raw_matches = data.get("matches", [])

        sample = []

        for raw_match in raw_matches[:30]:

            normalized = normalize_match(raw_match)

            sample.append({
                "id": normalized["id"],
                "home": normalized["homeTeam"]["name"],
                "away": normalized["awayTeam"]["name"],
                "display": normalized["gameTimeDisplay"],
                "rawStatus": normalized["rawStatus"],
                "detectedStatus": normalized["status"],
                "minute": normalized["minute"],
            })

        return jsonify({
            "source_total": data.get(
                "total",
                len(raw_matches)
            ),
            "received": len(raw_matches),
            "sample": sample,
        })

    except Exception as error:

        return jsonify({
            "error": str(error)
        }), 500


# =========================================================
# DETALHES DA PARTIDA
# =========================================================

@app.route("/api/match/<match_id>")
def match_details(match_id):

    try:

        data = sportsapi_get(
            f"/games/{match_id}/details",
            {
                "sport": "football"
            },
        )

        return jsonify(data)

    except requests.HTTPError as error:

        status = (
            error.response.status_code
            if error.response is not None
            else 502
        )

        return jsonify({
            "error":
                "Não foi possível consultar a partida",
            "status": status,
        }), status

    except Exception as error:

        return jsonify({
            "error": str(error)
        }), 500


# =========================================================
# HEALTH
# =========================================================

@app.route("/health")
def health():

    return jsonify({
        "status": "ok",
        "bot": "BetScope Bot",
        "version": "2.0",
    })


# =========================================================
# SERVIDOR
# =========================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
