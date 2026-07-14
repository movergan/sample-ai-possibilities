"""Score-based team tactics and coach instruction formatting."""

from __future__ import annotations

STRATEGY_MID_AGGRESSIVE = "MID_AGGRESSIVE"
STRATEGY_ATTACK = "ATTACK"
STRATEGY_BALANCED = "BALANCED"
STRATEGY_DEFENCE = "DEFENCE"

TACTICAL_OBEDIENCE_PROMPT = """## Team Strategy & Coach Instructions
Each state update includes a TACTICS section derived from the live score and coach messages in `teamChat`.
- **Coach instructions have highest priority** — follow them immediately on every tick.
- **Team strategy** is set automatically from the score (default: mid-aggressive).
- When coach instructions and team strategy conflict, prefer the most recent coach instruction.
- Apply both to your command choice every tick."""

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

    pos_key = position_label if position_label in _POSITION_GUIDANCE else "MID"
    position_guidance = _POSITION_GUIDANCE[pos_key].get(
        strategy, _POSITION_GUIDANCE[pos_key][STRATEGY_MID_AGGRESSIVE]
    )
    stance_hint = _STANCE[strategy]

    lines = [
        "=== TEAM TACTICS (MANDATORY) ===",
        f"Strategy: {_strategy_label(strategy)} | Score context: {_score_context(goal_diff)} (diff={goal_diff:+d})",
        f"Team-wide: {stance_hint}",
        f"Your role ({position_label}): {position_guidance}",
    ]

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
