"""L4 escalation — the network asks the player, and waits.

The pyramid gained a layer: L3 plans, but when the system detects a condition
it should not resolve alone (ambiguous ids, an explicit ASK_PLAYER), the
question goes to the player's in-game inbox and the plan BLOCKS until a
ruling arrives or patience runs out. On timeout the caller falls back to
whatever it would have done before L4 existed — an AFK player degrades to
the old behavior, never to a wedged fleet.

The L5 loop lives here too: if the player rules "escalate_l5", the question
goes to DeepSeek (the player's own key), and the answer comes BACK AS A NEW
INBOX ITEM for approval.
Nothing from L5 ever travels down the chain unreviewed. That invariant is
the design (user directive), not an implementation detail.
"""
import logging
import time
import uuid

import api
import telemetry

log = logging.getLogger("aibot.escalation")

DEFAULT_TIMEOUT = 120
POLL_SECONDS = 2


LAST_DIRECTIVE: dict = {}


def record_directive(bot: str, directive: dict):
    """The dispatch path stamps every directive here so an escalation can
    SHOW the player exactly what failed — and let them edit it."""
    if isinstance(directive, dict) and directive.get("kind"):
        LAST_DIRECTIVE[bot] = dict(directive)


def ask(bot: str, kind: str, question: str, options: list | None = None,
        timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Post a question to the player's inbox and block for the ruling.

    Returns {"answered": bool, "action": str, "text": str}. Handles the
    escalate_l5 loop internally — callers only ever see a final ruling.
    """
    esc_id = uuid.uuid4().hex[:12]
    directive = LAST_DIRECTIVE.get(bot) \
        if kind in ("attempts_exhausted", "impossible_criteria", "directive_timeout") else None
    try:
        api.raw_post("/telemetry/escalation", {
            "id": esc_id, "bot": bot, "kind": kind,
            "question": question, "options": options or [],
            "directive": directive,
        })
    except Exception as e:
        log.warning("[%s] escalation post failed (%s) — proceeding without L4", bot, e)
        return {"answered": False}

    telemetry.push(bot, "ask", f"asked L4: {question}")
    ruling = _wait(bot, esc_id, timeout)

    if ruling.get("answered") and ruling.get("action") == "escalate_l5":
        # Whatever the player typed (or edited into the directive fields)
        # travels WITH the question — L5 advises on the corrected picture.
        ctx = str(ruling.get("text") or "").strip()
        q5 = question if not ctx else \
            f"{question}\n\nPlayer context (may include an edited directive): {ctx}"
        return _l5_loop(bot, kind, q5, options or [], timeout)
    return ruling


def _wait(bot: str, esc_id: str, timeout: int) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = api.raw_get(f"/telemetry/escalation?id={esc_id}")
            if r.get("answered"):
                telemetry.push(bot, "ask",
                               f"L4 ruled: {r.get('action')} {str(r.get('text'))[:80]}")
                return r
        except Exception:
            pass
        time.sleep(POLL_SECONDS)
    # Patience exhausted — withdraw so the inbox doesn't hold a dead question.
    try:
        api.raw_delete("/telemetry/escalation", {"id": esc_id})
    except Exception:
        pass
    telemetry.push(bot, "ask", "L4 did not answer in time — falling back")
    return {"answered": False}


def _l5_loop(bot: str, kind: str, question: str, options: list, timeout: int) -> dict:
    """Consult L5, then put its ANSWER in the inbox for the player to approve."""
    import l5
    suggestion = l5.consult(question, options)
    if not suggestion:
        # L5 unreachable — the question returns to the player as-is.
        return ask(bot, kind, f"(L5 unavailable) {question}", options, timeout)

    telemetry.push(bot, "ask", f"L5 suggests: {suggestion[:120]}")
    review = ask(bot, "l5_review",
                 f"L5 suggests: {suggestion} — approve?",
                 ["approve"] + options, timeout)
    if review.get("answered") and review.get("action") == "choose" \
            and review.get("text") == "approve":
        return {"answered": True, "action": "answer", "text": suggestion}
    return review
