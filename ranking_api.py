"""
SharpTimer Ranking API
-----------------------
API independiente de solo lectura sobre la BD MariaDB de SharpTimer. Es la
UNICA fuente de las consultas de ranking: el bot de Discord y la landing page
la consumen por HTTP en vez de tocar la base de datos cada uno por su lado.

Endpoints (todos GET, todos requieren header X-Api-Key):
    /top?limit=10
    /rank?q=<nombre o steamid>
    /maptop?map=<mapa>&limit=10
    /pb?map=<mapa>&q=<nombre o steamid>
    /maps
"""

import os
import time
from flask import Flask, request, jsonify, abort
import pymysql

DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_USER = os.environ.get("DB_USER", "sharptimer_user")
DB_PASSWORD = os.environ["DB_PASSWORD"]
DB_NAME = os.environ.get("DB_NAME", "sharptimer_db")
API_KEY = os.environ["API_KEY"]

app = Flask(__name__)

CACHE_SECONDS = 60
_cache = {}


def cached(key, load):
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    value = load()
    _cache[key] = (time.monotonic(), value)
    return value


def get_connection():
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME, cursorclass=pymysql.cursors.DictCursor, connect_timeout=5,
    )


def query(sql, params=()):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        conn.close()


TOTALS_CTE = """
    WITH ranked AS (
        SELECT SteamID, PlayerName, MapName, Mode,
               RANK() OVER (PARTITION BY MapName, Mode ORDER BY TimerTicks ASC) AS rnk,
               COUNT(*) OVER (PARTITION BY MapName, Mode) AS total
        FROM PlayerRecords
    ),
    totals AS (
        SELECT SteamID, MAX(PlayerName) AS PlayerName,
               ROUND(SUM(1000.0 * (total - rnk + 1) / total)) AS Points
        FROM ranked
        GROUP BY SteamID
    )
"""


def is_steamid(s: str) -> bool:
    return s.isdigit() and len(s) >= 15


@app.before_request
def check_api_key():
    if request.headers.get("X-Api-Key") != API_KEY:
        abort(401)


@app.get("/top")
def top():
    limit = request.args.get("limit", 10, type=int)
    rows = cached(f"top:{limit}", lambda: query(
        f"{TOTALS_CTE} SELECT SteamID, PlayerName, Points FROM totals ORDER BY Points DESC LIMIT %s",
        (limit,),
    ))
    return jsonify([
        {"steamId": str(r["SteamID"]), "name": r["PlayerName"], "points": int(r["Points"])}
        for r in rows
    ])


@app.get("/rank")
def rank():
    search = (request.args.get("q") or "").strip()
    if not search:
        return jsonify([])
    by_id = is_steamid(search)
    rows = cached(f"rank:{search.lower()}", lambda: query(
        f"""{TOTALS_CTE}
            SELECT PlayerName, Points, SteamID,
                   (SELECT COUNT(*) + 1 FROM totals AS t2 WHERE t2.Points > t1.Points) AS Position
            FROM totals AS t1
            WHERE {"SteamID = %s" if by_id else "PlayerName LIKE %s"}
            ORDER BY Points DESC
            LIMIT 10""",
        (search if by_id else f"%{search}%",),
    ))
    return jsonify([
        {"steamId": str(r["SteamID"]), "name": r["PlayerName"], "points": int(r["Points"]), "position": int(r["Position"])}
        for r in rows
    ])


@app.get("/maptop")
def maptop():
    map_name = (request.args.get("map") or "").strip()
    limit = request.args.get("limit", 10, type=int)
    if not map_name:
        return jsonify([])
    rows = cached(f"maptop:{map_name}:{limit}", lambda: query(
        """SELECT PlayerName, FormattedTime, TimesFinished
           FROM PlayerRecords WHERE MapName = %s ORDER BY TimerTicks ASC LIMIT %s""",
        (map_name, limit),
    ))
    return jsonify([
        {"name": r["PlayerName"], "time": r["FormattedTime"], "finishes": int(r["TimesFinished"])}
        for r in rows
    ])


@app.get("/pb")
def pb():
    map_name = (request.args.get("map") or "").strip()
    search = (request.args.get("q") or "").strip()
    if not map_name or not search:
        return jsonify([])
    by_id = is_steamid(search)
    rows = cached(f"pb:{map_name}:{search.lower()}", lambda: query(
        f"""WITH ranked AS (
                SELECT SteamID, PlayerName, FormattedTime, TimesFinished,
                       RANK() OVER (ORDER BY TimerTicks ASC) AS Position,
                       COUNT(*) OVER () AS TotalPlayers
                FROM PlayerRecords WHERE MapName = %s
            )
            SELECT PlayerName, SteamID, FormattedTime, TimesFinished, Position, TotalPlayers
            FROM ranked
            WHERE {"SteamID = %s" if by_id else "PlayerName LIKE %s"}
            ORDER BY Position ASC
            LIMIT 10""",
        (map_name, search if by_id else f"%{search}%"),
    ))
    return jsonify([
        {
            "name": r["PlayerName"], "steamId": str(r["SteamID"]), "time": r["FormattedTime"],
            "finishes": int(r["TimesFinished"]), "position": int(r["Position"]), "total": int(r["TotalPlayers"]),
        }
        for r in rows
    ])


@app.get("/maps")
def maps():
    rows = cached("maps", lambda: query(
        """SELECT MapName, COUNT(DISTINCT SteamID) AS Jugadores
           FROM PlayerRecords GROUP BY MapName ORDER BY MapName ASC"""
    ))
    return jsonify([{"map": r["MapName"], "players": int(r["Jugadores"])} for r in rows])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8088")))
