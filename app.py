from flask import Flask, jsonify, request
import os
import re
import time
import requests

app = Flask(__name__)

# ============================================================
# CONFIGURAÇÃO
# ============================================================

SPORTS_API_KEY = os.environ.get("SPORTS_API_KEY")

SPORTS_API_BASE = os.environ.get(
    "SPORTS_API_URL",
    "https://sportsapi.com.br/api/v1"
)

CONNECT_TIMEOUT = 4
READ_TIMEOUT = 8
PAGE_LIMIT = 100

session = requests.Session()

session.headers.update({
    "Accept": "application/json"
})

if SPORTS_API_KEY:
    session.headers.update({
        "X-API-Key": SPORTS_API_KEY
    })


# ============================================================
# CACHE
# ============================================================

live_cache = {
    "matches": [],
    "timestamp": 0,
    "offset": None
}


# ============================================================
# SPORTSAPI
# ============================================================

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


# ============================================================
# AUXILIARES
# ============================================================

def first_value(data, keys, default=None):

    if not isinstance(data, dict):
        return default

    for key in keys:
        value = data.get(key)

        if value is not None:
            return value

    return default


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


def clean_text(value):

    if value is None:
        return ""

    return str(value).strip().lower()


# ============================================================
# NORMALIZAÇÃO DO STATUS
# ============================================================

def normalize_status(match):

    display = clean_text(
        first_value(
            match,
            [
                "gameTimeDisplay",
                "exibiçãoHorárioDoJogo",
                "exibiçãoHorárioDeJogo",
                "exibicaoHorarioDoJogo",
                "exibicaoHorarioDeJogo",
                "gameTime",
                "timeDisplay"
            ],
            ""
        )
    )

    raw_status = clean_text(
        first_value(
            match,
            [
                "status",
                "estado",
                "gameStatus"
            ],
            ""
        )
    )

    # ========================================================
    # 1. ENCERRADOS
    # ========================================================

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
        "finalizado",
        "finalizada",
        "completed",
        "complete"
    ]:
        return "finished"

    # ========================================================
    # 2. ADIADOS
    # ========================================================

    postponed_words = [
        "adiado",
        "adiada",
        "postponed"
    ]

    if display in postponed_words:
        return "postponed"

    if raw_status in postponed_words:
        return "postponed"

    # ========================================================
    # 3. SUSPENSOS
    # ========================================================

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

    # ========================================================
    # 4. CANCELADOS
    # ========================================================

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

    # ========================================================
    # 5. ABANDONADOS
    # ========================================================

    abandoned_words = [
        "abandonado",
        "abandonada",
        "abandoned"
    ]

    if display in abandoned_words:
        return "abandoned"

    if raw_status in abandoned_words:
        return "abandoned"

    # ========================================================
    # 6. AGENDADOS
    # ========================================================

    scheduled_words = [
        "agendado",
        "agendada",
        "scheduled",
        "not started",
        "notstarted",
        "não iniciado",
        "nao iniciado"
    ]

    if display in scheduled_words:
        return "scheduled"

    if raw_status in scheduled_words:
        return "scheduled"

    # ========================================================
    # 7. INTERVALO / PERÍODO DE JOGO
    # ========================================================

    live_period_words = [
        "intervalo",
        "half time",
        "halftime",
        "1º tempo",
        "2º tempo",
        "primeiro tempo",
        "segundo tempo",
        "first half",
        "second half"
    ]

    for word in live_period_words:

        if word in display:
            return "live"

    # ========================================================
    # 8. MINUTO REAL
    # ========================================================

    # Exemplos aceitos:
    # 1'
    # 23'
    # 45'
    # 45+2'
    # 67
    # 90+5

    minute_pattern = (
        r"^\s*"
        r"(\d{1,3})"
        r"(?:\s*\+\s*(\d{1,2}))?"
        r"\s*['’]?"
        r"\s*$"
    )

    minute_match = re.match(
        minute_pattern,
        display
    )

    if minute_match:

        try:

            base_minute = int(
                minute_match.group(1)
            )

            if 0 <= base_minute <= 130:
                return "live"

        except Exception:
            pass

    # ========================================================
    # 9. STATUS "LIVE" SEM PROVA
    # ========================================================

    live_source_statuses = [
        "live",
        "ao vivo",
        "aovivo",
        "inprogress",
        "in progress",
        "playing"
    ]

    if raw_status in live_source_statuses:

        # IMPORTANTE:
        # Não classificamos como LIVE apenas porque
        # a SportsAPI escreveu status=live.
        #
        # Precisamos de minuto, intervalo ou período.
        return "suspect_live"

    return "unknown"


# ============================================================
# NORMALIZAR PARTIDA
# ============================================================

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
            "exibiçãoHorárioDoJogo",
            "exibiçãoHorárioDeJogo",
            "exibicaoHorarioDoJogo",
            "exibicaoHorarioDeJogo",
            "gameTime",
            "timeDisplay"
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
        "status": normalize_status(match)
    }


# ============================================================
# EXTRAÇÃO
# ============================================================

def extract_matches(data):

    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    possible_keys = [
        "matches",
        "games",
        "data",
        "results"
    ]

    for key in possible_keys:

        value = data.get(key)

        if isinstance(value, list):
            return value

        if isinstance(value, dict):

            for subkey in possible_keys:

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


# ============================================================
# CONSULTAR UMA PÁGINA
# ============================================================

def fetch_live_page(offset=0):

    started = time.monotonic()

    data = sportsapi_get(
        "/games",
        {
            "sport": "football",
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

        "postponed_matches":
            buckets["postponed"],

        "suspended_matches":
            buckets["suspended"],

        "elapsed_seconds":
            elapsed
    }


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():

    return jsonify({
        "bot": "BetScope Bot",
        "status": "online",
        "version": "2.3",
        "sports_api_key":
            "configurada"
            if SPORTS_API_KEY
            else "não configurada"
    })


# ============================================================
# HEALTH
# ============================================================

@app.route("/health")
def health():

    return jsonify({
        "bot": "BetScope Bot",
        "status": "ok",
        "version": "2.3"
    })


# ============================================================
# LIVE
# ============================================================

@app.route("/api/live")
def live_games():

    global live_cache

    try:

        result = fetch_live_page(0)

        live_cache = {
            "matches":
                result["matches"],

            "timestamp":
                int(time.time() * 1000),

            "offset":
                0
        }

        return jsonify({
            "cached": False,
            **result,
            "timestamp":
                int(time.time() * 1000)
        })

    except requests.exceptions.Timeout:

        return jsonify({
            "cached": True,
            "status": "timeout",
            "error":
                "SportsAPI não respondeu dentro do limite.",
            "matches":
                live_cache["matches"],
            "cache_timestamp":
                live_cache["timestamp"]
        }), 200

    except requests.exceptions.HTTPError as error:

        api_status = (
            error.response.status_code
            if error.response is not None
            else None
        )

        return jsonify({
            "cached": True,
            "status": "sports_api_error",
            "sports_api_status":
                api_status,
            "matches":
                live_cache["matches"],
            "cache_timestamp":
                live_cache["timestamp"]
        }), 200

    except Exception as error:

        return jsonify({
            "cached": True,
            "status": "error",
            "error": str(error),
            "matches":
                live_cache["matches"]
        }), 200


# ============================================================
# DEBUG
# ============================================================

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

        result = fetch_live_page(offset)

        next_offset = (
            offset + PAGE_LIMIT
        )

        source_total = result.get(
            "source_total"
        )

        has_next = True

        if source_total is not None:

            if next_offset >= source_total:
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
            "status":
                "sports_api_error",

            "sports_api_status":
                api_status,

            "error":
                str(error)
        }), 200

    except Exception as error:

        return jsonify({
            "status": "error",
            "error": str(error)
        }), 200


# ============================================================
# DETALHES DA PARTIDA
# ============================================================

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
            "status":
                "sports_api_error",

            "sports_api_status":
                api_status,

            "error":
                "Erro ao consultar detalhes da partida."
        }), 200

    except Exception as error:

        return jsonify({
            "status": "error",
            "error": str(error)
        }), 200


# ============================================================
# START
# ============================================================

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
