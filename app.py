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

TIMEOUT = 25
PAGE_LIMIT = 100

# Máximo de páginas que vamos consultar.
# 15 páginas x 100 = até 1500 registros.
MAX_PAGES = 15


# ============================================================
# CACHE SIMPLES
# ============================================================

live_cache = {
    "matches": [],
    "timestamp": 0
}


# ============================================================
# SPORTSAPI
# ============================================================

def sportsapi_get(endpoint, params=None, retries=2):

    if not SPORTS_API_KEY:
        raise RuntimeError("SPORTS_API_KEY não configurada")

    url = f"{SPORTS_API_BASE}{endpoint}"

    last_error = None

    for attempt in range(retries + 1):

        try:

            response = requests.get(
                url,
                headers={
                    "X-API-Key": SPORTS_API_KEY,
                    "Accept": "application/json"
                },
                params=params,
                timeout=TIMEOUT
            )

            response.raise_for_status()

            return response.json()

        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.HTTPError
        ) as error:

            last_error = error

            # Pequena espera antes de tentar novamente
            if attempt < retries:
                time.sleep(1.5)

    raise last_error


# ============================================================
# FUNÇÕES AUXILIARES
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
            "teamName"
        ]
    )


def normalize_status(match):

    display = str(
        first_value(
            match,
            [
                "gameTimeDisplay",
                "exibiçãoHorárioDoJogo",
                "exibiçãoHorárioDeJogo",
                "exibicaoHorarioDoJogo",
                "exibicaoHorarioDeJogo"
            ],
            ""
        )
    ).strip().lower()

    status = str(
        first_value(
            match,
            [
                "status",
                "estado"
            ],
            ""
        )
    ).strip().lower()

    # ----------------------------------------
    # PARTIDA ENCERRADA
    # ----------------------------------------

    finished_words = [
        "fim de jogo",
        "finalizado",
        "finalizada",
        "encerrado",
        "encerrada",
        "finished",
        "full time",
        "full-time",
        "ft"
    ]

    for word in finished_words:

        if display == word:
            return "finished"

    if status in [
        "finished",
        "finalizado",
        "finalizada"
    ]:
        return "finished"

    # ----------------------------------------
    # CANCELADA
    # ----------------------------------------

    if status in [
        "cancelled",
        "canceled",
        "cancelado",
        "cancelada"
    ]:
        return "cancelled"

    # ----------------------------------------
    # ADIADA
    # ----------------------------------------

    if status in [
        "postponed",
        "adiado",
        "adiada"
    ]:
        return "postponed"

    # ----------------------------------------
    # AGENDADA
    # ----------------------------------------

    if status in [
        "scheduled",
        "agendado",
        "agendada"
    ]:
        return "scheduled"

    # ----------------------------------------
    # SINAIS REAIS DE JOGO AO VIVO
    # ----------------------------------------

    live_words = [
        "intervalo",
        "half time",
        "halftime",
        "ht",
        "1º tempo",
        "2º tempo",
        "primeiro tempo",
        "segundo tempo"
    ]

    for word in live_words:

        if word in display:
            return "live"

    # Exemplo:
    # 23'
    # 45+2'
    # 90 + 5
    minute_pattern = r"\b\d{1,3}(?:\s*\+\s*\d{1,2})?\s*['’]?\b"

    if re.search(minute_pattern, display):

        # Evita tratar horário 20:30 como minuto
        if ":" not in display:
            return "live"

    # Alguns feeds não fornecem minuto,
    # então usamos o status como último sinal.
    if status in [
        "live",
        "ao vivo",
        "aovivo",
        "inprogress",
        "in progress"
    ]:

        # Só aceitamos se não houver indicação
        # explícita de jogo encerrado.
        if display:
            return "live"

    return "unknown"


def normalize_match(match):

    if not isinstance(match, dict):
        return None

    home = first_value(
        match,
        [
            "homeTeam",
            "timeCasa",
            "mandante"
        ],
        {}
    )

    away = first_value(
        match,
        [
            "awayTeam",
            "timeVisitante",
            "visitante"
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

    if isinstance(league, dict):

        league_name = first_value(
            league,
            [
                "name",
                "nome",
                "shortName"
            ]
        )

    else:
        league_name = league

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
            "exibicaoHorarioDeJogo"
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
        "league": league_name,
        "home_score": home_score,
        "away_score": away_score,
        "game_time": display,
        "status": normalize_status(match)
    }


# ============================================================
# EXTRAIR LISTA DE JOGOS
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

    candidates = [
        data.get("total"),
        data.get("count"),
        data.get("totalCount")
    ]

    if isinstance(data.get("pagination"), dict):

        candidates.append(
            data["pagination"].get("total")
        )

    for value in candidates:

        try:
            if value is not None:
                return int(value)

        except (TypeError, ValueError):
            pass

    return None


# ============================================================
# BUSCA PAGINADA DE JOGOS AO VIVO
# ============================================================

def fetch_real_live_matches():

    real_live = []

    seen_ids = set()

    received = 0

    source_total = None

    pages_checked = 0

    errors = []

    for page in range(MAX_PAGES):

        offset = page * PAGE_LIMIT

        try:

            data = sportsapi_get(
                "/games",
                {
                    "sport": "football",
                    "status": "live",
                    "limit": PAGE_LIMIT,
                    "offset": offset
                }
            )

        except Exception as error:

            errors.append({
                "offset": offset,
                "error": str(error)
            })

            # Se uma página falhar, não derruba
            # todo o endpoint.
            continue

        pages_checked += 1

        matches = extract_matches(data)

        if source_total is None:
            source_total = extract_total(data)

        if not matches:
            break

        received += len(matches)

        for raw_match in matches:

            normalized = normalize_match(raw_match)

            if not normalized:
                continue

            if normalized["status"] != "live":
                continue

            match_id = normalized.get("id")

            # Remove duplicados
            if match_id is not None:

                unique_key = str(match_id)

            else:

                unique_key = (
                    str(normalized.get("home"))
                    + "|"
                    + str(normalized.get("away"))
                    + "|"
                    + str(normalized.get("game_time"))
                )

            if unique_key in seen_ids:
                continue

            seen_ids.add(unique_key)

            real_live.append(normalized)

        # Se a API informar o total,
        # paramos quando chegarmos ao fim.
        if source_total is not None:

            if offset + len(matches) >= source_total:
                break

        # Última página
        if len(matches) < PAGE_LIMIT:
            break

    return {
        "matches": real_live,
        "total": len(real_live),
        "received": received,
        "source_total": source_total,
        "pages_checked": pages_checked,
        "errors": errors
    }


# ============================================================
# ROTAS
# ============================================================

@app.route("/")
def home():

    return jsonify({
        "bot": "BetScope Bot",
        "status": "online",
        "version": "2.1",
        "sports_api_key":
            "configurada"
            if SPORTS_API_KEY
            else "não configurada"
    })


@app.route("/api/live")
def live_games():

    global live_cache

    try:

        result = fetch_real_live_matches()

        # Se conseguimos consultar pelo menos uma página,
        # atualizamos o cache.
        if result["pages_checked"] > 0:

            live_cache = {
                "matches": result["matches"],
                "timestamp": int(time.time() * 1000)
            }

        return jsonify({
            "cached": False,
            "matches": result["matches"],
            "total": result["total"],
            "received": result["received"],
            "source_total": result["source_total"],
            "pages_checked": result["pages_checked"],
            "errors": result["errors"],
            "timestamp": int(time.time() * 1000)
        })

    except Exception as error:

        # Se a SportsAPI cair completamente,
        # devolvemos o último resultado válido.
        return jsonify({
            "cached": True,
            "matches": live_cache["matches"],
            "total": len(live_cache["matches"]),
            "cache_timestamp": live_cache["timestamp"],
            "error": str(error)
        })


# ============================================================
# DEBUG DA PAGINAÇÃO
# ============================================================

@app.route("/api/debug/live")
def debug_live():

    try:

        result = fetch_real_live_matches()

        return jsonify({
            "status": "ok",
            "pages_checked": result["pages_checked"],
            "received": result["received"],
            "source_total": result["source_total"],
            "real_live_total": result["total"],
            "matches": result["matches"],
            "errors": result["errors"]
        })

    except Exception as error:

        return jsonify({
            "status": "error",
            "error": str(error)
        }), 500


# ============================================================
# DETALHES DE UMA PARTIDA
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

    except requests.exceptions.HTTPError as error:

        status = (
            error.response.status_code
            if error.response is not None
            else 502
        )

        return jsonify({
            "error": "SportsAPI recusou a requisição",
            "status": status,
            "details": str(error)
        }), status

    except Exception as error:

        return jsonify({
            "error": str(error)
        }), 500


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/health")
def health():

    return jsonify({
        "status": "ok",
        "bot": "BetScope Bot",
        "version": "2.1"
    })


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
