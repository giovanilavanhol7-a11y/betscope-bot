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

# Não podemos deixar a SportsAPI prender o worker do Render.
CONNECT_TIMEOUT = 4
READ_TIMEOUT = 8

PAGE_LIMIT = 100

# ============================================================
# SESSÃO HTTP
# ============================================================

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
# FUNÇÕES AUXILIARES
# ============================================================

def first_value(data, keys, default=None):

    if not isinstance(data, dict):
        return default

    for key in keys:

        if key in data:

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


# ============================================================
# STATUS
# ============================================================

def normalize_status(match):

    display = str(
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
    ).strip().lower()

    status = str(
        first_value(
            match,
            [
                "status",
                "estado",
                "gameStatus"
            ],
            ""
        )
    ).strip().lower()

    # --------------------------------------------------------
    # ENCERRADO
    # --------------------------------------------------------

    finished_exact = {
        "fim de jogo",
        "finalizado",
        "finalizada",
        "encerrado",
        "encerrada",
        "finished",
        "full time",
        "full-time",
        "ft"
    }

    if display in finished_exact:
        return "finished"

    if status in {
        "finished",
        "finalizado",
        "finalizada",
        "complete",
        "completed"
    }:
        return "finished"

    # --------------------------------------------------------
    # CANCELADO
    # --------------------------------------------------------

    if status in {
        "cancelled",
        "canceled",
        "cancelado",
        "cancelada"
    }:
        return "cancelled"

    # --------------------------------------------------------
    # ADIADO
    # --------------------------------------------------------

    if status in {
        "postponed",
        "adiado",
        "adiada"
    }:
        return "postponed"

    # --------------------------------------------------------
    # AGENDADO
    # --------------------------------------------------------

    if status in {
        "scheduled",
        "agendado",
        "agendada",
        "not started",
        "notstarted"
    }:
        return "scheduled"

    # --------------------------------------------------------
    # INTERVALO
    # --------------------------------------------------------

    live_texts = [
        "intervalo",
        "half time",
        "halftime",
        "1º tempo",
        "2º tempo",
        "primeiro tempo",
        "segundo tempo"
    ]

    for text in live_texts:

        if text in display:
            return "live"

    # --------------------------------------------------------
    # MINUTO DE JOGO
    # --------------------------------------------------------

    # Exemplos:
    # 23'
    # 45'
    # 45+3'
    # 90+5

    minute_pattern = r"^\s*\d{1,3}(?:\s*\+\s*\d{1,2})?\s*['’]?\s*$"

    if re.match(minute_pattern, display):

        try:

            base_minute = int(
                re.match(r"\d{1,3}", display).group()
            )

            # Evita valores absurdos do feed.
            if 0 <= base_minute <= 130:
                return "live"

        except Exception:
            pass

    # --------------------------------------------------------
    # STATUS LIVE DA FONTE
    # --------------------------------------------------------

    if status in {
        "live",
        "ao vivo",
        "aovivo",
        "inprogress",
        "in progress",
        "playing"
    }:

        # Não confiamos cegamente no status "live".
        # A fonte já marcou partidas encerradas como live.

        if display and display not in finished_exact:
            return "live"

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
# EXTRAIR PARTIDAS
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

    possible_values = [
        data.get("total"),
        data.get("count"),
        data.get("totalCount")
    ]

    pagination = data.get("pagination")

    if isinstance(pagination, dict):
        possible_values.append(
            pagination.get("total")
        )

    for value in possible_values:

        if value is None:
            continue

        try:
            return int(value)

        except (TypeError, ValueError):
            continue

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

    real_live = []
    suspect_live = []
    finished = []
    unknown = []

    for raw_match in raw_matches:

        match = normalize_match(raw_match)

        if not match:
            continue

        status = match["status"]

        if status == "live":
            real_live.append(match)

        elif status == "suspect_live":
            suspect_live.append(match)

        elif status == "finished":
            finished.append(match)

        else:
            unknown.append(match)

    return {
        "offset": offset,
        "limit": PAGE_LIMIT,
        "received": len(raw_matches),
        "source_total": extract_total(data),
        "real_live_total": len(real_live),
        "suspect_live_total": len(suspect_live),
        "finished_total": len(finished),
        "unknown_total": len(unknown),
        "matches": real_live,
        "suspect_matches": suspect_live,
        "elapsed_seconds": elapsed
    }


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():

    return jsonify({
        "bot": "BetScope Bot",
        "status": "online",
        "version": "2.2",
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
        "version": "2.2"
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
            "matches": result["matches"],
            "timestamp": int(time.time() * 1000),
            "offset": 0
        }

        return jsonify({
            "cached": False,
            **result,
            "timestamp": int(time.time() * 1000)
        })

    except requests.exceptions.Timeout:

        return jsonify({
            "cached": True,
            "error": "SportsAPI demorou para responder",
            "matches": live_cache["matches"],
            "cache_timestamp": live_cache["timestamp"]
        }), 200

    except requests.exceptions.HTTPError as error:

        status = (
            error.response.status_code
            if error.response is not None
            else None
        )

        return jsonify({
            "cached": True,
            "error": "SportsAPI retornou erro HTTP",
            "sports_api_status": status,
            "matches": live_cache["matches"],
            "cache_timestamp": live_cache["timestamp"]
        }), 200

    except Exception as error:

        return jsonify({
            "cached": True,
            "error": str(error),
            "matches": live_cache["matches"],
            "cache_timestamp": live_cache["timestamp"]
        }), 200


# ============================================================
# DEBUG POR PÁGINA
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

        # Mantém offset em múltiplos de 100.
        offset = (
            offset // PAGE_LIMIT
        ) * PAGE_LIMIT

        result = fetch_live_page(offset)

        next_offset = offset + PAGE_LIMIT

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
            "status": "sports_api_error",
            "sports_api_status": api_status,
            "error": str(error)
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
            "error":
                "SportsAPI demorou para responder aos detalhes da partida."
        }), 200

    except requests.exceptions.HTTPError as error:

        api_status = (
            error.response.status_code
            if error.response is not None
            else None
        )

        return jsonify({
            "error":
                "SportsAPI retornou erro ao consultar a partida.",
            "sports_api_status": api_status
        }), 200

    except Exception as error:

        return jsonify({
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
