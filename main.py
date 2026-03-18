import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests

SOFASCORE_BASE_URL = "https://api.sofascore.com/api/v1"
SOFASCORE_LIVE_URL = f"{SOFASCORE_BASE_URL}/sport/football/events/live"
STATE_FILE = os.getenv("STATE_FILE", "state.json")
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0 Safari/537.36",
)
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))
DRY_RUN = os.getenv("DRY_RUN", "0") == "1"
MAX_NOTIFICATIONS_PER_RUN = int(os.getenv("MAX_NOTIFICATIONS_PER_RUN", "4"))
MAX_CANDIDATES_PER_RUN = int(os.getenv("MAX_CANDIDATES_PER_RUN", "3"))
DEBUG_LOG = os.getenv("DEBUG_LOG", "0") == "1"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

TARGET_LEAGUES = {
    "Premier League",
    "LaLiga",
    "Serie A",
    "Bundesliga",
    "Ligue 1",
}

TOP_TEAMS = {
    "England": [
        "Arsenal",
        "Chelsea",
        "Liverpool",
        "Manchester City",
        "Manchester United",
        "Tottenham Hotspur",
    ],
    "Spain": [
        "Atlético Madrid",
        "Barcelona",
        "Real Madrid",
        "Sevilla",
    ],
    "Italy": [
        "Inter",
        "Juventus",
        "Milan",
        "Napoli",
        "Roma",
    ],
    "Germany": [
        "Bayer 04 Leverkusen",
        "Bayern München",
        "Borussia Dortmund",
        "RB Leipzig",
    ],
    "France": [
        "Lille",
        "Lyon",
        "Marseille",
        "Monaco",
        "Paris Saint-Germain",
    ],
}

TEAM_ALIASES = {
    "PSG": "Paris Saint-Germain",
    "Paris SG": "Paris Saint-Germain",
    "Paris Saint Germain": "Paris Saint-Germain",
    "Man City": "Manchester City",
    "Manchester Utd": "Manchester United",
    "Man Utd": "Manchester United",
    "Spurs": "Tottenham Hotspur",
    "Tottenham": "Tottenham Hotspur",
    "Atl. Madrid": "Atlético Madrid",
    "Atletico Madrid": "Atlético Madrid",
    "Bayern Munich": "Bayern München",
    "Leverkusen": "Bayer 04 Leverkusen",
    "Dortmund": "Borussia Dortmund",
    "Inter Milan": "Inter",
    "AC Milan": "Milan",
    "OM": "Marseille",
    "OL": "Lyon",
    "AS Monaco": "Monaco",
}

TOP_TEAM_SET = {team for teams in TOP_TEAMS.values() for team in teams}

STAT_ALIASES = {
    "shots_total": [
        "Total shots",
        "Shots total",
        "Shots",
        "Attempts on goal",
        "Goal attempts",
        "Attempts",
    ],
    "shots_on_target": [
        "Shots on target",
        "Shots on goal",
        "On target",
        "Shots on target inside box",
    ],
    "corners": [
        "Corner kicks",
        "Corners",
    ],
    "possession": [
        "Ball possession",
        "Possession",
    ],
    "dangerous_attacks": [
        "Dangerous attacks",
        "Dangerous attacks total",
    ],
}

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://www.sofascore.com/",
    }
)


@dataclass
class CandidateEvent:
    event: Dict[str, Any]
    event_id: str
    league: str
    home: str
    away: str
    minute: int
    goals: int
    score: str
    rank: int


@dataclass
class MatchSignal:
    signal_type: str
    event_id: str
    key: str
    message: str


class BotError(Exception):
    pass


def log(msg: str) -> None:
    print(msg, flush=True)


def debug(msg: str) -> None:
    if DEBUG_LOG:
        log("[DEBUG] " + msg)


def normalize_team(name: Optional[str]) -> str:
    if not name:
        return ""
    name = str(name).strip()
    return TEAM_ALIASES.get(name, name)


def parse_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        txt = str(value).strip().replace("%", "")
        if txt == "":
            return default
        return int(float(txt))
    except Exception:
        return default


def league_name_from_event(event: Dict[str, Any]) -> str:
    tournament = (event.get("tournament") or {}).get("name")
    unique_tournament = ((event.get("tournament") or {}).get("uniqueTournament") or {}).get("name")
    season_name = (event.get("season") or {}).get("name")
    for candidate in [unique_tournament, tournament, season_name]:
        if candidate:
            return str(candidate).strip()
    return "Unknown"


def status_description(event: Dict[str, Any]) -> str:
    status = event.get("status") or {}
    description = status.get("description") or status.get("type") or ""
    return str(description).strip()


def minute_from_event(event: Dict[str, Any]) -> int:
    status = event.get("status") or {}
    current = parse_int(status.get("current"), default=-1)
    if current >= 0:
        return current
    desc = status_description(event).lower()
    if desc in {"halftime", "ht"}:
        return 45
    if desc in {"finished", "ft"}:
        return 90
    return -1


def total_goals(event: Dict[str, Any]) -> int:
    home_score = parse_int((((event.get("homeScore") or {}).get("current"))), 0)
    away_score = parse_int((((event.get("awayScore") or {}).get("current"))), 0)
    return home_score + away_score


def scoreline(event: Dict[str, Any]) -> str:
    home_score = parse_int((((event.get("homeScore") or {}).get("current"))), 0)
    away_score = parse_int((((event.get("awayScore") or {}).get("current"))), 0)
    return f"{home_score}-{away_score}"


def is_top_team_match(event: Dict[str, Any]) -> Tuple[bool, str, str]:
    home = normalize_team(((event.get("homeTeam") or {}).get("name")))
    away = normalize_team(((event.get("awayTeam") or {}).get("name")))
    return home in TOP_TEAM_SET or away in TOP_TEAM_SET, home, away


def has_top_team(name_a: str, name_b: str) -> bool:
    return name_a in TOP_TEAM_SET or name_b in TOP_TEAM_SET


def is_target_league(event: Dict[str, Any]) -> bool:
    league = league_name_from_event(event)
    return league in TARGET_LEAGUES


def build_match_url(event: Dict[str, Any]) -> Optional[str]:
    slug = event.get("slug")
    custom_id = event.get("customId")
    event_id = event.get("id")
    if slug and custom_id and event_id:
        return f"https://www.sofascore.com/football/match/{slug}/{custom_id}#{event_id}"
    return None


def fetch_json(url: str) -> Dict[str, Any]:
    response = SESSION.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def fetch_live_events() -> List[Dict[str, Any]]:
    payload = fetch_json(SOFASCORE_LIVE_URL)
    events = payload.get("events") or []
    if not isinstance(events, list):
        raise BotError("Réponse inattendue de la source live.")
    return events


def fetch_event_statistics(event_id: str) -> Optional[Dict[str, Any]]:
    endpoints = [
        f"{SOFASCORE_BASE_URL}/event/{event_id}/statistics",
        f"{SOFASCORE_BASE_URL}/event/{event_id}/statistics/overall",
    ]
    for url in endpoints:
        try:
            payload = fetch_json(url)
            if payload:
                return payload
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code in (404, 410):
                continue
            raise
        except Exception:
            continue
    return None


def load_state() -> Dict[str, Any]:
    if not os.path.exists(STATE_FILE):
        return {"sent": {}, "last_run": None}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"sent": {}, "last_run": None}


def save_state(state: Dict[str, Any]) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def already_sent(state: Dict[str, Any], key: str) -> bool:
    return key in (state.get("sent") or {})


def mark_sent(state: Dict[str, Any], key: str, payload: Dict[str, Any]) -> None:
    state.setdefault("sent", {})[key] = payload


def cleanup_old_state(state: Dict[str, Any], keep_limit: int = 500) -> None:
    sent = state.get("sent") or {}
    if len(sent) <= keep_limit:
        return
    items = list(sent.items())[-keep_limit:]
    state["sent"] = dict(items)


def candidate_rank(event: Dict[str, Any], minute: int, goals: int, home: str, away: str) -> int:
    rank = 0
    if has_top_team(home, away):
        rank += 10
    if goals == 0 and 15 <= minute <= 30:
        rank += 8
    if goals <= 1 and 28 <= minute <= 65:
        rank += 6
    if home in TOP_TEAM_SET and away not in TOP_TEAM_SET:
        rank += 2
    return rank


def build_candidates(events: List[Dict[str, Any]]) -> List[CandidateEvent]:
    candidates: List[CandidateEvent] = []
    for event in events:
        if not is_target_league(event):
            continue
        is_top, home, away = is_top_team_match(event)
        if not is_top:
            continue
        minute = minute_from_event(event)
        if minute < 0:
            continue
        status_text = status_description(event).lower()
        if any(word in status_text for word in ["finished", "canceled", "cancelled", "postponed"]):
            continue
        goals = total_goals(event)
        # Pre-filter to keep API use low.
        if not ((15 <= minute <= 30 and goals == 0) or (28 <= minute <= 65 and goals <= 1)):
            continue
        league = league_name_from_event(event)
        score = scoreline(event)
        event_id = str(event.get("id") or f"{home}-{away}-{league}")
        rank = candidate_rank(event, minute, goals, home, away)
        candidates.append(
            CandidateEvent(
                event=event,
                event_id=event_id,
                league=league,
                home=home,
                away=away,
                minute=minute,
                goals=goals,
                score=score,
                rank=rank,
            )
        )
    candidates.sort(key=lambda c: (c.rank, c.minute), reverse=True)
    return candidates[:MAX_CANDIDATES_PER_RUN]


def collect_stat_pairs(node: Any, out: List[Tuple[str, Any, Any]]) -> None:
    if isinstance(node, dict):
        if "statisticsItems" in node and isinstance(node["statisticsItems"], list):
            for item in node["statisticsItems"]:
                collect_stat_pairs(item, out)
        elif {"name", "home", "away"}.issubset(node.keys()):
            out.append((str(node.get("name")), node.get("home"), node.get("away")))
        else:
            for value in node.values():
                collect_stat_pairs(value, out)
    elif isinstance(node, list):
        for item in node:
            collect_stat_pairs(item, out)


def extract_stat_map(payload: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    pairs: List[Tuple[str, Any, Any]] = []
    collect_stat_pairs(payload, pairs)
    stats: Dict[str, Dict[str, int]] = {}
    for raw_name, home_val, away_val in pairs:
        key = raw_name.strip().lower()
        stats[key] = {
            "home": parse_int(home_val, 0),
            "away": parse_int(away_val, 0),
        }
    return stats


def get_named_stat(stats: Dict[str, Dict[str, int]], aliases: List[str]) -> Tuple[int, int]:
    for alias in aliases:
        item = stats.get(alias.strip().lower())
        if item is not None:
            return item.get("home", 0), item.get("away", 0)
    return 0, 0


def summarize_stats(payload: Dict[str, Any]) -> Dict[str, Any]:
    stats = extract_stat_map(payload)
    shots_home, shots_away = get_named_stat(stats, STAT_ALIASES["shots_total"])
    sot_home, sot_away = get_named_stat(stats, STAT_ALIASES["shots_on_target"])
    corners_home, corners_away = get_named_stat(stats, STAT_ALIASES["corners"])
    poss_home, poss_away = get_named_stat(stats, STAT_ALIASES["possession"])
    danger_home, danger_away = get_named_stat(stats, STAT_ALIASES["dangerous_attacks"])

    return {
        "shots_home": shots_home,
        "shots_away": shots_away,
        "shots_total": shots_home + shots_away,
        "sot_home": sot_home,
        "sot_away": sot_away,
        "sot_total": sot_home + sot_away,
        "corners_home": corners_home,
        "corners_away": corners_away,
        "corners_total": corners_home + corners_away,
        "poss_home": poss_home,
        "poss_away": poss_away,
        "danger_home": danger_home,
        "danger_away": danger_away,
        "raw_keys": sorted(list(stats.keys())),
    }


def pick_dominant_side(candidate: CandidateEvent, summary: Dict[str, Any]) -> Tuple[str, int, int, int, int]:
    home_is_priority = candidate.home in TOP_TEAM_SET or candidate.away not in TOP_TEAM_SET
    if home_is_priority:
        side_name = candidate.home
        shots = summary["shots_home"]
        sot = summary["sot_home"]
        corners = summary["corners_home"]
        poss = summary["poss_home"]
    else:
        side_name = candidate.away
        shots = summary["shots_away"]
        sot = summary["sot_away"]
        corners = summary["corners_away"]
        poss = summary["poss_away"]
    return side_name, shots, sot, corners, poss


def evaluate_candidate(candidate: CandidateEvent, state: Dict[str, Any]) -> List[MatchSignal]:
    signals: List[MatchSignal] = []
    stats_payload = fetch_event_statistics(candidate.event_id)
    if not stats_payload:
        debug(f"Pas de stats détaillées pour {candidate.event_id}")
        return signals

    summary = summarize_stats(stats_payload)
    dominant_side, dom_shots, dom_sot, dom_corners, dom_poss = pick_dominant_side(candidate, summary)

    debug(
        f"{candidate.home} vs {candidate.away} | shots={summary['shots_total']} | "
        f"sot={summary['sot_total']} | corners={summary['corners_total']} | "
        f"possession={summary['poss_home']}-{summary['poss_away']}"
    )

    match_url = build_match_url(candidate.event)
    url_line = f"\n🔗 {match_url}" if match_url else ""

    # Over 0.5: strict to reduce spam.
    if 15 <= candidate.minute <= 30 and candidate.goals == 0:
        over05_ok = (
            summary["shots_total"] >= 7
            and summary["sot_total"] >= 2
            and (summary["corners_total"] >= 3 or dom_poss >= 55)
            and dom_shots >= 4
            and dom_sot >= 1
        )
        if over05_ok:
            key = f"o05::{candidate.event_id}"
            if not already_sent(state, key):
                message = (
                    f"🔥 OVER 0.5 ANALYSE\n"
                    f"🏆 {candidate.league}\n"
                    f"⚽ {candidate.home} vs {candidate.away}\n"
                    f"⏱ {candidate.minute}' | Score {candidate.score}\n"
                    f"📈 Tirs totaux: {summary['shots_total']} | Cadrés: {summary['sot_total']} | Corners: {summary['corners_total']}\n"
                    f"🎯 Équipe qui pousse: {dominant_side} ({dom_shots} tirs, {dom_sot} cadrés, {dom_poss}% possession)\n"
                    f"✅ Signal validé: volume offensif réel, pas juste minute + score.{url_line}"
                )
                signals.append(MatchSignal("OVER_0_5", candidate.event_id, key, message))

    # Over 1.5: still strict, but adapted to later game state.
    if 28 <= candidate.minute <= 65 and candidate.goals <= 1:
        over15_ok = (
            summary["shots_total"] >= 10
            and summary["sot_total"] >= 3
            and (summary["corners_total"] >= 4 or dom_poss >= 55)
            and dom_shots >= 5
            and dom_sot >= 2
        )
        if over15_ok:
            key = f"o15::{candidate.event_id}"
            if not already_sent(state, key):
                message = (
                    f"🚀 OVER 1.5 ANALYSE\n"
                    f"🏆 {candidate.league}\n"
                    f"⚽ {candidate.home} vs {candidate.away}\n"
                    f"⏱ {candidate.minute}' | Score {candidate.score}\n"
                    f"📈 Tirs totaux: {summary['shots_total']} | Cadrés: {summary['sot_total']} | Corners: {summary['corners_total']}\n"
                    f"🎯 Équipe qui pousse: {dominant_side} ({dom_shots} tirs, {dom_sot} cadrés, {dom_poss}% possession)\n"
                    f"✅ Signal validé: match vivant + pression offensive cohérente.{url_line}"
                )
                signals.append(MatchSignal("OVER_1_5", candidate.event_id, key, message))

    return signals


def send_telegram_message(text: str) -> None:
    if DRY_RUN:
        log("[DRY_RUN] Message Telegram simulé :\n" + text)
        return

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise BotError("TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID manquant.")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise BotError(f"Erreur Telegram: {data}")


def main() -> int:
    state = load_state()
    notifications_sent = 0

    try:
        events = fetch_live_events()
        log(f"{len(events)} match(s) live récupéré(s).")
    except Exception as exc:
        log(f"Échec récupération source live: {exc}")
        return 1

    candidates = build_candidates(events)
    if not candidates:
        log("Aucun match shortlisté pour analyse détaillée.")
    else:
        log(f"{len(candidates)} match(s) shortlisté(s) pour analyse détaillée.")
        for candidate in candidates:
            log(
                f"- {candidate.league}: {candidate.home} vs {candidate.away} "
                f"({candidate.minute}', {candidate.score})"
            )

    all_signals: List[MatchSignal] = []
    for candidate in candidates:
        try:
            all_signals.extend(evaluate_candidate(candidate, state))
        except Exception as exc:
            log(f"Analyse détaillée impossible pour {candidate.event_id}: {exc}")

    if not all_signals:
        log("Aucun signal validé après analyse détaillée.")
    else:
        log(f"{len(all_signals)} signal(s) validé(s) avant envoi Telegram.")

    for signal in all_signals:
        if notifications_sent >= MAX_NOTIFICATIONS_PER_RUN:
            log("Limite de notifications atteinte pour ce run.")
            break
        try:
            send_telegram_message(signal.message)
            notifications_sent += 1
            mark_sent(
                state,
                signal.key,
                {
                    "signal_type": signal.signal_type,
                    "event_id": signal.event_id,
                    "sent_at": int(time.time()),
                },
            )
            log(f"Signal envoyé: {signal.key}")
        except Exception as exc:
            log(f"Erreur envoi Telegram pour {signal.key}: {exc}")

    state["last_run"] = int(time.time())
    cleanup_old_state(state)
    save_state(state)

    log(f"Run terminé. Notifications envoyées: {notifications_sent}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
