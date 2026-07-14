"""Score-based team tactics and coach instruction formatting."""

from __future__ import annotations

STRATEGY_MID_AGGRESSIVE = "MID_AGGRESSIVE"
STRATEGY_ATTACK = "ATTACK"
STRATEGY_BALANCED = "BALANCED"
STRATEGY_DEFENCE = "DEFENCE"

TACTICAL_OBEDIENCE_PROMPT = """## Team Strategy, Match Events & Coach Instructions
Each state update includes TACTICS derived from the live score, match phase (kickoff/goal events), and coach messages in `teamChat`.
- **Coach instructions have highest priority** — follow them immediately on every tick.
- **Match events** (kickoff, just scored/conceded) override routine positioning — act before the opponent settles.
- **Team strategy** is set automatically from the score (default: mid-aggressive).
- When instructions conflict, prefer: coach > match event > team strategy.
- Apply all sections to your command choice every tick."""

_STANCE = {
    STRATEGY_MID_AGGRESSIVE: "SET_STANCE stance=0 (Balanced) with aggressive pressing and forward runs",
    STRATEGY_ATTACK: "SET_STANCE stance=1 (Attack) — push high, shoot often, take risks",
    STRATEGY_BALANCED: "SET_STANCE stance=0 (Balanced) — controlled possession, measured risk",
    STRATEGY_DEFENCE: "SET_STANCE stance=2 (Defend) — protect the lead, compact shape",
}

_POSITION_GUIDANCE: dict[str, dict[str, str]] = {
    "GK": {
        STRATEGY_MID_AGGRESSIVE: "Distribute quickly; hold the line; intercept loose balls in the box.",
        STRATEGY_ATTACK: "Distribute forward aggressively (KICK to midfielders/forwards); step slightly off line only for clear threats.",
        STRATEGY_BALANCED: "Safe distribution; stay between ball and goal center; avoid risky rushes.",
        STRATEGY_DEFENCE: "Conservative positioning; short safe distribution; never chase into midfield.",
    },
    "DEF": {
        STRATEGY_MID_AGGRESSIVE: "Press in your half; tight MARK on dangerous opponents; occasional forward PASS when safe.",
        STRATEGY_ATTACK: "Step up the pitch; press ball carrier early; support attacks with forward passes.",
        STRATEGY_BALANCED: "Hold defensive shape; zonal coverage; recycle possession with simple passes.",
        STRATEGY_DEFENCE: "Deep line; tight MARK; clear danger; do not push into opponent's half.",
    },
    "MID1": {
        STRATEGY_MID_AGGRESSIVE: "Hold central midfield (player 2); recycle possession; PASS to MID2(4) or FWD(3); PRESS in the middle third; shield DEF(1).",
        STRATEGY_ATTACK: "Push slightly higher; quick outlet passes to MID2(4) and FWD(3); support buildup — leave finishing to MID2 and FWD.",
        STRATEGY_BALANCED: "Control tempo from deep; safe passes between DEF(1) and attack; do not overcommit forward.",
        STRATEGY_DEFENCE: "Anchor deep; break up play; track back before pressing; PASS back to DEF(1) when under pressure.",
    },
    "MID2": {
        STRATEGY_MID_AGGRESSIVE: "Play as second striker (player 4) behind FWD(3); THROUGH balls to FWD; shoot from ~28 units; high PRESS in opponent half.",
        STRATEGY_ATTACK: "Maximum creativity; shoot often; sprint into channels; combine with FWD(3) for 2v1; PRESS_BALL at 0.85+.",
        STRATEGY_BALANCED: "Support FWD(3) with forward runs; selective through balls; press only in the attacking third.",
        STRATEGY_DEFENCE: "Drop to the midfield line alongside MID1(2); retain possession; press only when the ball is nearby.",
    },
    "MID": {
        STRATEGY_MID_AGGRESSIVE: "Link defense and attack; PRESS in midfield; THROUGH passes to forwards; shoot from ~25 units.",
        STRATEGY_ATTACK: "Push into attacking third; aggressive THROUGH passes and shots; high PRESS_BALL intensity (0.85+).",
        STRATEGY_BALANCED: "Control tempo; recycle possession; support both defense and attack without overcommitting.",
        STRATEGY_DEFENCE: "Sit deeper; shield the back line; prefer safe passes; track back before pressing.",
    },
    "FWD1": {
        STRATEGY_MID_AGGRESSIVE: "Attack the goal; SHOOT in range; high press; make runs into space.",
        STRATEGY_ATTACK: "Maximum aggression; shoot from up to 35 units; sprint into channels; press at 0.9+ intensity.",
        STRATEGY_BALANCED: "Hold attacking shape; combine with midfield; shoot only on clear chances.",
        STRATEGY_DEFENCE: "Drop slightly deeper; hold ball when leading; press only in your defensive half.",
    },
}


# Per-runtime score tracking to detect goals within a single agent process.
_last_score_by_team: dict[int, tuple[int, int]] = {}

_KICKOFF_ATTACK_GUIDANCE: dict[str, str] = {
    "GK": "Stay on line; be ready to distribute immediately if you receive the ball.",
    "DEF": "Hold a compact line 10–15 units ahead of goal; offer a safe PASS outlet to MID1(2).",
    "MID1": "Stand central near the ball; offer the first PASS outlet — recycle to MID2(4) or FWD(3) quickly.",
    "MID2": "Push 10–15 units ahead of the ball; be the primary forward option after kickoff.",
    "FWD1": "Stretch high and wide; hold the last line — ready for a THROUGH ball from MID1(2) or MID2(4).",
}

_KICKOFF_DEFEND_GUIDANCE: dict[str, str] = {
    "GK": "Hold the line; track the ball laterally; do not rush out.",
    "DEF": "Stay compact between ball and goal; tight MARK on the kickoff receiver.",
    "MID1": "PRESS the kickoff receiver at intensity 0.8; cut the pass to MID2(4).",
    "MID2": "PRESS_BALL at 0.85 on the ball carrier; win it high if possible.",
    "FWD1": "Press the deepest outlet (block pass to FWD); PRESS_BALL intensity 0.75.",
}

_GOAL_EVENT_GUIDANCE: dict[str, dict[str, str]] = {
    "TEAM_SCORED": {
        "GK": "We scored — expect kickoff soon; stay composed, quick distribution when play resumes.",
        "DEF": "We scored — reset shape immediately; compact line before kickoff.",
        "MID1": "We scored — take a breath, then hold central shape for the restart.",
        "MID2": "We scored — use the reset window to push high before opponents organize.",
        "FWD1": "We scored — stay high for the restart; be ready to press their kickoff.",
    },
    "OPP_SCORED": {
        "GK": "We conceded — refocus; expect kickoff from center; stay between ball and goal.",
        "DEF": "We conceded — tighten marking; do not chase out of shape on the restart.",
        "MID1": "We conceded — sit deeper; shield DEF(1); win the ball back with discipline.",
        "MID2": "We conceded — press aggressively on their kickoff; force a mistake.",
        "FWD1": "We conceded — press their kickoff receiver; block the first forward pass.",
    },
}


def _normalize_play_mode(play_mode) -> str:
    return str(play_mode or "").upper().replace(" ", "_").replace("-", "_")


def _ball_at_center(ball: dict, threshold: float = 8.0) -> bool:
    pos = ball.get("position", {})
    return abs(pos.get("x", 99)) < threshold and abs(pos.get("y", 99)) < threshold


def detect_score_event(game_state: dict, team_id: int) -> str | None:
    """Detect if we scored or conceded since the last tick (per agent runtime)."""
    game_time = float(game_state.get("gameTime", 0) or 0)
    if game_time < 5:
        _last_score_by_team.pop(team_id, None)

    score = game_state.get("score", {})
    home = int(score.get("home", 0) or 0)
    away = int(score.get("away", 0) or 0)
    prev = _last_score_by_team.get(team_id)
    _last_score_by_team[team_id] = (home, away)

    if prev is None:
        return None

    ph, pa = prev
    my_prev = ph if team_id == 0 else pa
    opp_prev = pa if team_id == 0 else ph
    my_now = home if team_id == 0 else away
    opp_now = away if team_id == 0 else home

    if my_now > my_prev:
        return "TEAM_SCORED"
    if opp_now > opp_prev:
        return "OPP_SCORED"
    return None


def detect_match_phase(game_state: dict, team_id: int) -> str:
    """Classify the current match phase for kickoff and restart windows."""
    play_mode = _normalize_play_mode(game_state.get("playMode"))
    mode_team = game_state.get("modeTeamId")
    ball = game_state.get("ball", {})

    kickoff_modes = ("KICKOFF", "KICK_OFF", "CENTER_KICK", "CENTER", "RESTART", "GOAL_KICK")
    if any(token in play_mode for token in kickoff_modes) or play_mode == "KICK":
        if mode_team is not None and int(mode_team) == team_id:
            return "KICKOFF_ATTACK"
        if mode_team is not None:
            return "KICKOFF_DEFEND"
        return "KICKOFF"

    if _ball_at_center(ball) and mode_team is not None:
        if int(mode_team) == team_id:
            return "KICKOFF_ATTACK"
        return "KICKOFF_DEFEND"

    if "GOAL" in play_mode and "GOALKEEPER" not in play_mode:
        return "POST_GOAL"

    return "OPEN_PLAY"


def build_match_event_context(
    game_state: dict,
    team_id: int,
    position_label: str,
) -> str | None:
    """Build match-phase guidance for kickoff windows and goal events."""
    phase = detect_match_phase(game_state, team_id)
    score_event = detect_score_event(game_state, team_id)
    pos_key = position_label if position_label in _KICKOFF_ATTACK_GUIDANCE else "MID1"

    lines: list[str] = []

    if score_event:
        guidance = _GOAL_EVENT_GUIDANCE[score_event].get(
            pos_key, _GOAL_EVENT_GUIDANCE[score_event]["MID1"]
        )
        label = "WE SCORED" if score_event == "TEAM_SCORED" else "WE CONCEDED"
        lines.append(f"Goal event: {label} — {guidance}")

    if phase == "KICKOFF_ATTACK":
        lines.append(
            "Kickoff phase: WE kick off — "
            + _KICKOFF_ATTACK_GUIDANCE.get(pos_key, _KICKOFF_ATTACK_GUIDANCE["MID1"])
        )
    elif phase in ("KICKOFF_DEFEND", "KICKOFF"):
        lines.append(
            "Kickoff phase: OPPONENT kicks off — press immediately, "
            + _KICKOFF_DEFEND_GUIDANCE.get(pos_key, _KICKOFF_DEFEND_GUIDANCE["MID1"])
        )
    elif phase == "POST_GOAL":
        lines.append(
            "Post-goal reset: all players return to start — set shape fast before play resumes."
        )

    if not lines:
        return None

    block = ["=== MATCH EVENTS (HIGH PRIORITY) ===", *lines, ""]
    return "\n".join(block)


def get_score_diff(score: dict, team_id: int) -> int:
    """Return goal difference from this team's perspective (positive = leading)."""
    home = int(score.get("home", 0) or 0)
    away = int(score.get("away", 0) or 0)
    if team_id == 0:
        return home - away
    return away - home


def resolve_strategy(goal_diff: int) -> str:
    """Pick team-wide tactic from score difference."""
    if goal_diff <= -2:
        return STRATEGY_ATTACK
    if goal_diff == 1:
        return STRATEGY_BALANCED
    if goal_diff >= 2:
        return STRATEGY_DEFENCE
    return STRATEGY_MID_AGGRESSIVE


def _normalize_chat_entry(entry) -> str | None:
    if entry is None:
        return None
    if isinstance(entry, str):
        text = entry.strip()
        return text or None
    if isinstance(entry, dict):
        for key in ("message", "text", "instruction", "content", "body"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def extract_coach_messages(team_chat) -> list[str]:
    """Normalize teamChat payloads into plain instruction strings."""
    if not team_chat:
        return []
    if isinstance(team_chat, str):
        text = team_chat.strip()
        return [text] if text else []
    if not isinstance(team_chat, list):
        return []

    messages: list[str] = []
    for entry in team_chat:
        text = _normalize_chat_entry(entry)
        if text:
            messages.append(text)
    return messages


def _strategy_label(strategy: str) -> str:
    labels = {
        STRATEGY_MID_AGGRESSIVE: "Mid-Aggressive (default)",
        STRATEGY_ATTACK: "Attack",
        STRATEGY_BALANCED: "Balanced",
        STRATEGY_DEFENCE: "Defence",
    }
    return labels.get(strategy, strategy)


def _score_context(goal_diff: int) -> str:
    if goal_diff > 0:
        return f"leading by {goal_diff}"
    if goal_diff < 0:
        return f"losing by {abs(goal_diff)}"
    return "level"


def build_altenar_tactical_context(
    game_state: dict,
    team_id: int,
    position_label: str,
    team_chat=None,
) -> str:
    """Build the mandatory tactics block for Altenar prod agents."""
    score = game_state.get("score", {})
    goal_diff = get_score_diff(score, team_id)
    strategy = resolve_strategy(goal_diff)
    coach_messages = extract_coach_messages(team_chat)

    pos_key = position_label if position_label in _POSITION_GUIDANCE else "MID1"
    position_guidance = _POSITION_GUIDANCE[pos_key].get(
        strategy, _POSITION_GUIDANCE[pos_key][STRATEGY_MID_AGGRESSIVE]
    )
    stance_hint = _STANCE[strategy]

    match_event_block = build_match_event_context(game_state, team_id, position_label)

    lines = []
    if match_event_block:
        lines.append(match_event_block.rstrip())
    lines.extend([
        "=== TEAM TACTICS (MANDATORY) ===",
        f"Strategy: {_strategy_label(strategy)} | Score context: {_score_context(goal_diff)} (diff={goal_diff:+d})",
        f"Team-wide: {stance_hint}",
        f"Your role ({position_label}): {position_guidance}",
    ])

    lines.append("")
    lines.append("=== COACH INSTRUCTIONS (HIGHEST PRIORITY) ===")
    if coach_messages:
        for i, msg in enumerate(coach_messages, 1):
            lines.append(f"{i}. {msg}")
        lines.append("Follow the latest coach instruction above when choosing your command.")
    else:
        lines.append("(none this tick — follow team strategy)")

    lines.append("")
    return "\n".join(lines)
