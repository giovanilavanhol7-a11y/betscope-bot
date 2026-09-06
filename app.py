from flask import Flask, jsonify
import os
import requests

app = Flask(__name__)

SPORTS_API_KEY = os.environ.get("SPORTS_API_KEY")
SPORTS_API_BASE = "https://sportsapi.com.br/api/v1"


def sportsapi_get(endpoint, params=None):
    if not SPORTS_API_KEY:
        raise RuntimeError("SPORTS_API_KEY não configurada no servidor.")

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


@app.route("/")
def home():
    return jsonify({
        "bot": "BetScope Bot",
        "status": "online",
        "sports_api_key": "configurada" if SPORTS_API_KEY else "ausente"
    })


@app.route("/api/live")
def live_games():
    try:
        data = sportsapi_get(
            "/games",
            {
                "sport": "football",
                "status": "live",
                "limit": 100
            }
        )

        return jsonify(data)

    except requests.HTTPError as error:
        status = error.response.status_code if error.response else 502

        return jsonify({
            "error": "SportsAPI recusou a requisição",
            "status": status
        }), status

    except Exception as error:
        return jsonify({
            "error": str(error)
        }), 500


@app.route("/api/match/<match_id>")
def match_details(match_id):
    try:
        data = sportsapi_get(
            f"/games/{match_id}/details",
            {"sport": "football"}
        )

        return jsonify(data)

    except requests.HTTPError as error:
        status = error.response.status_code if error.response else 502

        return jsonify({
            "error": "Não foi possível consultar a partida",
            "status": status
        }), status

    except Exception as error:
        return jsonify({
            "error": str(error)
        }), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
