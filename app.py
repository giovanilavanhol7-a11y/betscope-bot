from flask import Flask, jsonify
import os
import requests

app = Flask(__name__)

# =========================================================
# CONFIGURAÇÃO DA SPORTS API
# =========================================================

SPORTS_API_KEY = os.environ.get("SPORTS_API_KEY")

SPORTS_API_BASE = os.environ.get(
    "SPORTS_API_URL",
    "https://sportsapi.com.br/api/v1"
)


# =========================================================
# CONSULTA À SPORTS API
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
# NORMALIZAR STATUS DA PARTIDA
# =========================================================

def normalize_status(match):

    display = str(
        match.get("gameTimeDisplay")
        or match.get("exibiçãoHorárioDoJogo")
        or match.get("exibiçãoHorárioDeJogo")
        or match.get("exibiçãoDoJogo")
        or ""
    ).lower()

    status = str(
        match.get("status", "")
    ).lower()

    finished_words = [
        "fim de jogo",
        "finalizado",
        "finished",
        "full time",
        "ft",
    ]

    # Se estiver escrito "Fim de jogo",
    # consideramos encerrada mesmo que a API diga "live".
    if any(word in display for word in finished_words):
        return "finished"

    if status in [
        "finished",
        "finalizado",
    ]:
        return "finished"

    if status in [
        "scheduled",
        "agendado",
    ]:
        return "scheduled"

    if status in [
        "postponed",
        "adiado",
    ]:
        return "postponed"

    if status in [
        "cancelled",
        "canceled",
        "cancelado",
    ]:
        return "cancelled"

    if status in [
        "live",
        "aovivo",
        "ao vivo",
    ]:
        return "live"

    return "unknown"


# =========================================================
# NORMALIZAR DADOS DA PARTIDA
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

    home_name = (
        home.get("name")
        or home.get("nome")
        or "Mandante"
    )

    away_name = (
        away.get("name")
        or away.get("nome")
        or "Visitante"
    )

    home_logo = (
        home.get("logo")
        or home.get("logotipo")
        or ""
    )

    away_logo = (
        away.get("logo")
        or away.get("logotipo")
        or ""
    )

    league_name = (
        league.get("name")
        or league.get("nome")
        or "Competição"
    )

    home_score = match.get("homeScore")

    if home_score is None:
        home_score = match.get("placarCasa")

    away_score = match.get("awayScore")

    if away_score is None:
        away_score = match.get("placarVisitante")

    if away_score is None:
        away_score = match.get("PontuaçãoFora")

    game_time = (
        match.get("gameTimeDisplay")
        or match.get("exibiçãoHorárioDoJogo")
        or match.get("exibiçãoHorárioDeJogo")
        or match.get("exibiçãoDoJogo")
        or ""
    )

    start_time = (
        match.get("startTime")
        or match.get("horárioInicial")
        or match.get("horaInicialização")
    )

    return {
        "id": match.get("id"),
        "sport": (
            match.get("sport")
            or match.get("esporte")
            or "football"
        ),
        "status": normalize_status(match),
        "gameTimeDisplay": game_time,
        "startTime": start_time,

        "homeTeam": {
            "name": home_name,
            "logo": home_logo,
        },

        "awayTeam": {
            "name": away_name,
            "logo": away_logo,
        },

        "homeScore": home_score,
        "awayScore": away_score,

        "league": {
            "name": league_name
        },
    }


# =========================================================
# ROTA PRINCIPAL
# =========================================================

@app.route("/")
def home():

    return jsonify({
        "bot": "BetScope Bot",
        "status": "online",
        "sports_api_key": (
            "configurada"
            if SPORTS_API_KEY
            else "não configurada"
        ),
    })


# =========================================================
# PARTIDAS AO VIVO
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

            # Só entra na lista se realmente estiver AO VIVO
            if match["status"] == "live":
                live_matches.append(match)

        return jsonify({
            "cached": data.get("cached", False),
            "matches": live_matches,
            "total": len(live_matches),
            "source_total": data.get(
                "total",
                len(raw_matches)
            ),
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
# DETALHES DE UMA PARTIDA
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
            "error": "Não foi possível consultar a partida",
            "status": status,
        }), status

    except Exception as error:

        return jsonify({
            "error": str(error)
        }), 500


# =========================================================
# HEALTH CHECK
# =========================================================

@app.route("/health")
def health():

    return jsonify({
        "status": "ok",
        "bot": "BetScope Bot",
    })


# =========================================================
# INICIAR SERVIDOR
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
