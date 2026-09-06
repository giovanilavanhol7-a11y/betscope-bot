from flask import Flask, jsonify, request
import os
import re
import time
from datetime import datetime, timezone
import requests

app = Flask(__name__)

SPORTS_API_KEY = os.environ.get("SPORTS_API_KEY")
SPORTS_API_BASE = os.environ.get(
    "SPORTS_API_URL",
    "https://sportsapi.com.br/api/v1"
)

CONNECT_TIMEOUT = 4
READ_TIMEOUT = 8
PAGE_LIMIT = 100

session = requests.Session()
session.headers.update({"Accept": "application/json"})

if SPORTS_API_KEY:
    session.headers.update({"X-API-Key": SPORTS_API_KEY})


# =========================================================
# SPORTS API
# =========================================================

def sportsapi_get(endpoint, params=None):
    if not SPORTS_API_KEY:
        raise RuntimeError("SPORTS_API_KEY não configurada")

    url = f"{SPORTS_API_BASE}{endpoint}"

    response = session.get(
        url,
        params=params,
        timeout=(CONNECT_TIMEOUT, READ_TIMEOUT)
    )

    response.raise_for_status()

    return response.json()


# =========================================================
# UTILIDADES
# =========================================================

def first_value(data, keys, default=None):
    if not isinstance(data, dict):
        return default

    for key in keys:
        value = data.get(key)

        if value is not None:
            return value

    return default


def clean_text(value):
    if value is None:
        return ""

    return str(value).strip().lower()


def team_name(team):
    if isinstance(team, str):
        return team

    if not isinstance(team, dict):
        return None

    return first_value(
        team,
        [
            "name",
            "nome",
            "shortName",
            "teamName",
            "nomeTime"
        ]
    )


def league_name(league):
    if isinstance(league, str):
        return league

    if not isinstance(league, dict):
        return None

    return first_value(
        league,
        [
            "name",
            "nome",
            "shortName",
            "leagueName"
        ]
    )


def today_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# =========================================================
# STATUS
# =========================================================

def normalize_status(match):

    display = clean_text(
        first_value(
            match,
            [
                "gameTimeDisplay",
                "gameTime",
                "timeDisplay"
            ],
            ""
        )
    )

    period = clean_text(
        first_value(
            match,
            [
                "period",
                "periodName",
                "currentPeriod"
            ],
            ""
        )
    )

    raw_status = clean_text(
        first_value(
            match,
            [
                "status",
                "gameStatus",
                "estado"
            ],
            ""
        )
    )

    # -----------------------------
    # FINALIZADOS
    # -----------------------------

    finished_words = [
        "fim de jogo",
        "finalizado",
        "finalizada",
        "encerrado",
        "encerrada",
        "finished",
        "full time",
        "full-time",
        "fulltime"
    ]

    if display in finished_words:
        return "finished"

    if raw_status in [
        "finished",
        "completed",
        "complete",
        "finalizado",
        "finalizada"
    ]:
        return "finished"

    # -----------------------------
    # ADIADOS
    # -----------------------------

    if display in [
        "adiado",
        "adiada",
        "postponed"
    ]:
        return "postponed"

    if raw_status in [
        "adiado",
        "adiada",
        "postponed"
    ]:
        return "postponed"

    # -----------------------------
    # SUSPENSOS
    # -----------------------------

    suspended_words = [
        "suspenso",
        "suspensa",
        "suspended",
        "interrompido",
        "interrompida",
        "interrupted"
    ]

    if display in suspended_words:
        return "suspended"

    if raw_status in suspended_words:
        return "suspended"

    # -----------------------------
    # CANCELADOS
    # -----------------------------

    cancelled_words = [
        "cancelado",
        "cancelada",
        "cancelled",
        "canceled"
    ]

    if display in cancelled_words:
        return "cancelled"

    if raw_status in cancelled_words:
        return "cancelled"

    # -----------------------------
    # ABANDONADOS
    # -----------------------------

    abandoned_words = [
        "abandonado",
        "abandonada",
        "abandoned"
    ]

    if display in abandoned_words:
        return "abandoned"

    if raw_status in abandoned_words:
        return "abandoned"

    # =====================================================
    # EVIDÊNCIA FORTE DE AO VIVO PELO PERÍODO
    # =====================================================

    live_period_words = [
        "primeiro tempo",
        "segundo tempo",
        "1º tempo",
        "2º tempo",
        "1st half",
        "2nd half",
        "first half",
        "second half",
        "intervalo",
        "half time",
        "halftime",
        "extra time",
        "prorrogação",
        "prorrogacao"
    ]

    for word in live_period_words:

        if word in period:
            return "live"

        if word in display:
            return "live"

    # =====================================================
    # MINUTO AO VIVO
    # Exemplos:
    # 23'
    # 45+2'
    # 74
    # =====================================================

    minute_pattern = r"^\s*(\d{1,3})(?:\s*\+\s*(\d{1,2}))?\s*['’]?\s*$"

    minute_match = re.match(
        minute_pattern,
        display
    )

    if minute_match:

        try:

            minute = int(
                minute_match.group(1)
            )

            if 1 <= minute <= 130:
                return "live"

        except Exception:
            pass

    # =====================================================
    # STATUS DA PRÓPRIA API
    # =====================================================

    if raw_status in [
        "live",
        "ao vivo",
        "aovivo",
        "inprogress",
        "in progress",
        "playing"
    ]:

        # Status live sem minuto/período.
        # Mantemos separado para diagnóstico.
        return "suspect_live"

    # -----------------------------
    # AGENDADOS
    # -----------------------------

    scheduled_words = [
        "scheduled",
        "agendado",
        "agendada",
        "not started",
        "notstarted",
        "não iniciado",
        "nao iniciado"
    ]

    if raw_status in scheduled_words:
        return "scheduled"

    if display in scheduled_words:
        return "scheduled"

    return "unknown"


# =========================================================
# NORMALIZAR PARTIDA
# =========================================================

def normalize_match(match):

    if not isinstance(match, dict):
        return None

    home = first_value(
        match,
        [
            "homeTeam",
            "timeCasa",
            "mandante",
            "home"
        ],
        {}
    )

    away = first_value(
        match,
        [
            "awayTeam",
            "timeVisitante",
            "visitante",
            "away"
        ],
        {}
    )

    league = first_value(
        match,
        [
            "league",
            "liga",
            "competition",
            "competicao"
        ],
        {}
    )

    match_id = first_value(
        match,
        [
            "id",
            "matchId",
            "gameId",
            "_id"
        ]
    )

    display = first_value(
        match,
        [
            "gameTimeDisplay",
            "gameTime",
            "timeDisplay"
        ]
    )

    period = first_value(
        match,
        [
            "period",
            "periodName",
            "currentPeriod"
        ]
    )

    start_time = first_value(
        match,
        [
            "startTime",
            "start_time",
            "timestamp"
        ]
    )

    home_score = first_value(
        match,
        [
            "homeScore",
            "placarCasa",
            "scoreHome"
        ]
    )

    away_score = first_value(
        match,
        [
            "awayScore",
            "placarVisitante",
            "scoreAway"
        ]
    )

    return {
        "id": match_id,
        "home": team_name(home),
        "away": team_name(away),
        "league": league_name(league),
        "home_score": home_score,
        "away_score": away_score,
        "game_time": display,
        "period": period,
        "start_time": start_time,
        "raw_status": first_value(
            match,
            ["status", "gameStatus", "estado"]
        ),
        "status": normalize_status(match)
    }


# =========================================================
# EXTRAÇÃO
# =========================================================

def extract_matches(data):

    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    for key in [
        "matches",
        "games",
        "data",
        "results"
    ]:

        value = data.get(key)

        if isinstance(value, list):
            return value

        if isinstance(value, dict):

            for subkey in [
                "matches",
                "games",
                "data",
                "results"
            ]:

                subvalue = value.get(subkey)

                if isinstance(subvalue, list):
                    return subvalue

    return []


def extract_total(data):

    if not isinstance(data, dict):
        return None

    values = [
        data.get("total"),
        data.get("count"),
        data.get("totalCount")
    ]

    pagination = data.get("pagination")

    if isinstance(pagination, dict):
        values.append(
            pagination.get("total")
        )

    for value in values:

        try:

            if value is not None:
                return int(value)

        except (TypeError, ValueError):
            pass

    return None


# =========================================================
# CONSULTA NOVA V2.4
# =========================================================

def fetch_live_today(offset=0):

    date = today_utc()

    started = time.monotonic()

    data = sportsapi_get(
        "/games",
        {
            "sport": "football",
            "date": date,
            "status": "live",
            "limit": PAGE_LIMIT,
            "offset": offset
        }
    )

    elapsed = round(
        time.monotonic() - started,
        3
    )

    raw_matches = extract_matches(data)

    buckets = {
        "live": [],
        "suspect_live": [],
        "finished": [],
        "postponed": [],
        "suspended": [],
        "cancelled": [],
        "abandoned": [],
        "scheduled": [],
        "unknown": []
    }

    for raw in raw_matches:

        match = normalize_match(raw)

        if not match:
            continue

        status = match["status"]

        if status not in buckets:
            status = "unknown"

        buckets[status].append(match)

    return {
        "date_utc": date,

        "offset": offset,

        "limit": PAGE_LIMIT,

        "received": len(raw_matches),

        "source_total": extract_total(data),

        "real_live_total":
            len(buckets["live"]),

        "suspect_live_total":
            len(buckets["suspect_live"]),

        "finished_total":
            len(buckets["finished"]),

        "postponed_total":
            len(buckets["postponed"]),

        "suspended_total":
            len(buckets["suspended"]),

        "cancelled_total":
            len(buckets["cancelled"]),

        "abandoned_total":
            len(buckets["abandoned"]),

        "scheduled_total":
            len(buckets["scheduled"]),

        "unknown_total":
            len(buckets["unknown"]),

        "matches":
            buckets["live"],

        "suspect_matches":
            buckets["suspect_live"],

        "unknown_matches":
            buckets["unknown"],

        "postponed_matches":
            buckets["postponed"],

        "suspended_matches":
            buckets["suspended"],

        "elapsed_seconds":
            elapsed
    }


# =========================================================
# ROTAS
# =========================================================

@app.route("/")
def home():

    return jsonify({
        "bot": "BetScope Bot",
        "status": "online",
        "version": "2.4",
        "sports_api_key":
            "configurada"
            if SPORTS_API_KEY
            else "não configurada",
        "date_utc": today_utc()
    })


@app.route("/health")
def health():

    return jsonify({
        "bot": "BetScope Bot",
        "status": "ok",
        "version": "2.4"
    })


# =========================================================
# LIVE PRINCIPAL
# =========================================================

@app.route("/api/live")
def live_games():

    try:

        result = fetch_live_today(0)

        return jsonify({
            "status": "ok",
            **result,
            "timestamp":
                int(time.time() * 1000)
        })

    except requests.exceptions.Timeout:

        return jsonify({
            "status": "timeout",
            "error":
                "SportsAPI não respondeu dentro de 8 segundos."
        }), 200

    except requests.exceptions.HTTPError as error:

        api_status = (
            error.response.status_code
            if error.response is not None
            else None
        )

        return jsonify({
            "status": "sports_api_error",
            "sports_api_status": api_status,
            "error":
                "Erro ao consultar jogos ao vivo."
        }), 200

    except Exception as error:

        return jsonify({
            "status": "error",
            "error": str(error)
        }), 200


# =========================================================
# DEBUG LIVE
# =========================================================

@app.route("/api/debug/live")
def debug_live():

    try:

        offset_text = request.args.get(
            "offset",
            "0"
        )

        try:
            offset = int(offset_text)

        except ValueError:
            offset = 0

        if offset < 0:
            offset = 0

        offset = (
            offset // PAGE_LIMIT
        ) * PAGE_LIMIT

        result = fetch_live_today(offset)

        next_offset = (
            offset + PAGE_LIMIT
        )

        source_total = result.get(
            "source_total"
        )

        has_next = True

        if (
            source_total is not None
            and next_offset >= source_total
        ):
            has_next = False

        if result["received"] < PAGE_LIMIT:
            has_next = False

        return jsonify({
            "status": "ok",
            **result,
            "next_offset":
                next_offset
                if has_next
                else None
        })

    except requests.exceptions.Timeout:

        return jsonify({
            "status": "timeout",
            "error":
                "SportsAPI não respondeu dentro de 8 segundos."
        }), 200

    except requests.exceptions.HTTPError as error:

        api_status = (
            error.response.status_code
            if error.response is not None
            else None
        )

        return jsonify({
            "status": "sports_api_error",
            "sports_api_status": api_status,
            "error": str(error)
        }), 200

    except Exception as error:

        return jsonify({
            "status": "error",
            "error": str(error)
        }), 200


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
            }
        )

        return jsonify(data)

    except requests.exceptions.Timeout:

        return jsonify({
            "status": "timeout",
            "error":
                "SportsAPI demorou para responder aos detalhes."
        }), 200

    except requests.exceptions.HTTPError as error:

        api_status = (
            error.response.status_code
            if error.response is not None
            else None
        )

        return jsonify({
            "status": "sports_api_error",
            "sports_api_status": api_status,
            "error":
                "Erro ao consultar detalhes da partida."
        }), 200

    except Exception as error:

        return jsonify({
            "status": "error",
            "error": str(error)
        }), 200


# =========================================================
# START
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
