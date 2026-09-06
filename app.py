from flask import Flask, jsonify, request
import os
import time
import requests
from datetime import datetime, timezone

app = Flask(__name__)

SPORTS_API_KEY = os.environ.get("SPORTS_API_KEY")
SPORTS_API_BASE = os.environ.get(
    "SPORTS_API_URL",
    "https://sportsapi.com.br/api/v1"
)

CONNECT_TIMEOUT = 4
READ_TIMEOUT = 10
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

def today_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


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


# =========================================================
# EXTRAIR LISTA DE PARTIDAS
# =========================================================

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

    possible = [
        data.get("total"),
        data.get("count"),
        data.get("totalCount")
    ]

    pagination = data.get("pagination")

    if isinstance(pagination, dict):
        possible.append(pagination.get("total"))

    for value in possible:

        try:

            if value is not None:
                return int(value)

        except (TypeError, ValueError):
            pass

    return None


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
            "home",
            "timeCasa",
            "mandante"
        ],
        {}
    )

    away = first_value(
        match,
        [
            "awayTeam",
            "away",
            "timeVisitante",
            "visitante"
        ],
        {}
    )

    league = first_value(
        match,
        [
            "league",
            "competition",
            "liga",
            "competicao"
        ],
        {}
    )

    return {

        "id": first_value(
            match,
            [
                "id",
                "matchId",
                "gameId",
                "_id"
            ]
        ),

        "home": team_name(home),

        "away": team_name(away),

        "league": league_name(league),

        "status": first_value(
            match,
            [
                "status",
                "gameStatus",
                "estado"
            ]
        ),

        "game_time": first_value(
            match,
            [
                "gameTimeDisplay",
                "gameTime",
                "timeDisplay"
            ]
        ),

        "start_time": first_value(
            match,
            [
                "startTime",
                "start_time",
                "date",
                "scheduledAt",
                "timestamp"
            ]
        ),

        "home_score": first_value(
            match,
            [
                "homeScore",
                "scoreHome",
                "placarCasa"
            ]
        ),

        "away_score": first_value(
            match,
            [
                "awayScore",
                "scoreAway",
                "placarVisitante"
            ]
        )
    }


# =========================================================
# BUSCAR PRÉ-JOGOS
# =========================================================

def fetch_upcoming(date=None, offset=0):

    if not date:
        date = today_utc()

    started = time.monotonic()

    data = sportsapi_get(
        "/games",
        {
            "sport": "football",
            "date": date,
            "status": "scheduled",
            "limit": PAGE_LIMIT,
            "offset": offset
        }
    )

    elapsed = round(
        time.monotonic() - started,
        3
    )

    raw_matches = extract_matches(data)

    matches = []

    for raw in raw_matches:

        match = normalize_match(raw)

        if match:
            matches.append(match)

    return {

        "date": date,

        "offset": offset,

        "limit": PAGE_LIMIT,

        "received": len(raw_matches),

        "source_total": extract_total(data),

        "matches": matches,

        "elapsed_seconds": elapsed
    }


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    return jsonify({
        "bot": "BetScope Bot",
        "mode": "pre-match",
        "sports_api_key":
            "configurada"
            if SPORTS_API_KEY
            else "não configurada",
        "status": "online",
        "version": "2.5"
    })


# =========================================================
# HEALTH
# =========================================================

@app.route("/health")
def health():

    return jsonify({
        "bot": "BetScope Bot",
        "status": "ok",
        "version": "2.5"
    })


# =========================================================
# JOGOS PRÉ-JOGO
#
# Exemplos:
#
# /api/upcoming
#
# /api/upcoming?date=2026-09-07
#
# /api/upcoming?date=2026-09-07&offset=100
# =========================================================

@app.route("/api/upcoming")
def upcoming():

    try:

        date = request.args.get(
            "date",
            today_utc()
        )

        try:

            datetime.strptime(
                date,
                "%Y-%m-%d"
            )

        except ValueError:

            return jsonify({
                "status": "error",
                "error":
                    "Data inválida. Use YYYY-MM-DD."
            }), 200

        try:

            offset = int(
                request.args.get(
                    "offset",
                    "0"
                )
            )

        except ValueError:

            offset = 0

        if offset < 0:
            offset = 0

        offset = (
            offset // PAGE_LIMIT
        ) * PAGE_LIMIT

        result = fetch_upcoming(
            date=date,
            offset=offset
        )

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
                "SportsAPI não respondeu dentro de 10 segundos."
        }), 200

    except requests.exceptions.HTTPError as error:

        api_status = (
            error.response.status_code
            if error.response is not None
            else None
        )

        return jsonify({
            "status": "sports_api_error",
            "sports_api_status":
                api_status,
            "error":
                "Erro ao consultar partidas pré-jogo."
        }), 200

    except Exception as error:

        return jsonify({
            "status": "error",
            "error": str(error)
        }), 200


# =========================================================
# DADOS BRUTOS DE UMA PARTIDA
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

        return jsonify({
            "status": "ok",
            "match_id": match_id,
            "data": data
        })

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
