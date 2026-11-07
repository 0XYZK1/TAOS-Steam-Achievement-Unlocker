"""Optional online sources: owned games, community XML and store search."""

import xml.etree.ElementTree as ET

import requests

from taos.config import HTTP_TIMEOUT_LONG, HTTP_TIMEOUT_SHORT

session = requests.Session()
session.headers["User-Agent"] = "TAOS/2.0"


def fetch_owned_games(api_key: str, steam_id64: str) -> list[dict]:
    if not api_key or not steam_id64:
        return []

    url = (
        "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"
        f"?key={api_key}&steamid={steam_id64}"
        "&include_appinfo=1&include_played_free_games=1"
    )
    try:
        response = session.get(url, timeout=HTTP_TIMEOUT_LONG)
        if response.status_code != 200:
            return []
        games = response.json().get("response", {}).get("games", [])
    except (requests.RequestException, ValueError):
        return []

    return [
        {"appid": int(game.get("appid", 0)), "name": game.get("name", "")}
        for game in games
    ]


def fetch_community_games(steam_id64: str) -> list[dict]:
    if not steam_id64:
        return []

    url = f"https://steamcommunity.com/profiles/{steam_id64}/games?tab=all&xml=1"
    try:
        response = session.get(url, timeout=HTTP_TIMEOUT_LONG)
        if response.status_code != 200 or "<gamesList>" not in response.text:
            return []
        root = ET.fromstring(response.text)
    except (requests.RequestException, ET.ParseError):
        return []

    games = []
    for node in root.findall(".//game"):
        app_id = node.findtext("appID")
        if app_id and app_id.isdigit():
            games.append({"appid": int(app_id), "name": node.findtext("name") or ""})
    return games


def fetch_schema(app_id: int, api_key: str) -> list[dict]:
    if not api_key:
        return []

    url = (
        "https://api.steampowered.com/ISteamUserStats/GetSchemaForGame/v2/"
        f"?key={api_key}&appid={app_id}"
    )
    try:
        response = session.get(url, timeout=HTTP_TIMEOUT_SHORT)
        if response.status_code != 200:
            return []
        items = (
            response.json()
            .get("game", {})
            .get("availableGameStats", {})
            .get("achievements", [])
        )
    except (requests.RequestException, ValueError):
        return []

    return [
        {
            "id": item.get("name"),
            "title": item.get("displayName", item.get("name")),
            "description": item.get("description", ""),
            "icon": item.get("icon", ""),
            "icon_gray": item.get("icongray", item.get("icon", "")),
            "hidden": bool(item.get("hidden", 0)),
            "unlocked": False,
        }
        for item in items
    ]


def fetch_player_states(app_id: int, api_key: str, steam_id64: str) -> dict[str, bool]:
    if not api_key or not steam_id64:
        return {}

    url = (
        "https://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v1/"
        f"?key={api_key}&steamid={steam_id64}&appid={app_id}"
    )
    try:
        response = session.get(url, timeout=HTTP_TIMEOUT_SHORT)
        if response.status_code != 200:
            return {}
        items = response.json().get("playerstats", {}).get("achievements", [])
    except (requests.RequestException, ValueError):
        return {}

    return {
        item["apiname"]: bool(item.get("achieved", 0))
        for item in items
        if item.get("apiname")
    }


def fetch_community_achievements(
    app_id: int,
    steam_id64: str,
) -> tuple[list[dict], dict[str, bool]]:
    if not steam_id64:
        return [], {}

    url = f"https://steamcommunity.com/profiles/{steam_id64}/stats/{app_id}/?xml=1"
    try:
        response = session.get(url, timeout=HTTP_TIMEOUT_SHORT)
        if response.status_code != 200 or "<achievements>" not in response.text:
            return [], {}
        root = ET.fromstring(response.text)
    except (requests.RequestException, ET.ParseError):
        return [], {}

    achievements = []
    states: dict[str, bool] = {}

    for node in root.findall(".//achievement"):
        unlocked = node.attrib.get("closed", "0") == "1"
        api_name = node.findtext("apiname") or f"ACH_{len(achievements)}"
        closed_icon = node.findtext("iconClosed") or ""
        open_icon = node.findtext("iconOpen") or closed_icon

        states[api_name] = unlocked
        achievements.append({
            "id": api_name,
            "title": node.findtext("name") or api_name,
            "description": node.findtext("description") or "",
            "icon": open_icon,
            "icon_gray": closed_icon,
            "hidden": False,
            "unlocked": unlocked,
        })

    return achievements, states


def search_store_games(term: str, limit: int = 12) -> list[dict]:
    term = term.strip()
    if not term:
        return []

    url = (
        "https://store.steampowered.com/api/storesearch/"
        f"?term={requests.utils.quote(term)}&l=english&cc=US"
    )
    try:
        response = session.get(url, timeout=HTTP_TIMEOUT_SHORT)
        if response.status_code != 200:
            return []
        items = response.json().get("items", [])
    except (requests.RequestException, ValueError):
        return []

    results = []
    for item in items:
        app_id = int(item.get("id", 0))
        if item.get("type") != "app" or app_id <= 0:
            continue
        results.append({
            "app_id": app_id,
            "name": item.get("name", str(app_id)),
            "image": item.get("tiny_image", ""),
        })
        if len(results) >= limit:
            break
    return results


def search_store_game(query: str) -> tuple[int, str]:
    results = search_store_games(query, limit=1)
    if not results:
        return 0, ""
    return results[0]["app_id"], results[0]["name"]


def fetch_store_name(app_id: int) -> str:
    url = f"https://store.steampowered.com/api/appdetails?appids={app_id}"
    try:
        response = session.get(url, timeout=HTTP_TIMEOUT_SHORT)
        if response.status_code == 200:
            payload = response.json().get(str(app_id), {})
            if payload.get("success"):
                return payload.get("data", {}).get("name", "")
    except (requests.RequestException, ValueError):
        pass
    return ""


def resolve_app_names(app_ids: list[int]) -> dict[int, str]:
    if not app_ids:
        return {}

    wanted = set(app_ids)
    names: dict[int, str] = {}
    try:
        response = session.get(
            "https://api.steampowered.com/ISteamApps/GetAppList/v2/",
            timeout=HTTP_TIMEOUT_LONG,
        )
        if response.status_code != 200:
            return {}
        apps = response.json().get("applist", {}).get("apps", [])
    except (requests.RequestException, ValueError):
        return {}

    for item in apps:
        app_id = int(item.get("appid", 0))
        name = item.get("name", "")
        if app_id in wanted and name:
            names[app_id] = name
    return names
