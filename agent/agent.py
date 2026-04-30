#!/usr/bin/env python3
"""
AI Player Agent — connects ollama to the NeoForge AI Player Mod.
Supports multiple bots from a single process, each with its own
observe → think → act loop running in a separate thread.
"""

import json
import os
import re
import threading
import time
import sys
import api
import brain
import memory as mem_module
import prompts
import semantic_memory as sem
import planner
import sessions
import taskboard
import transmute_db
import container_db
import openai_brain
import waypoints
import mc_items
import terrain_db
from config import (
    TICK_DELAY, BUSY_POLL_DELAY,
    OBSERVE_ENTITY_RADIUS, OBSERVE_BLOCK_RADIUS,
    MAX_CHAT_HISTORY, MAX_CONVERSATION, OLLAMA_URL, PG_DSN,
    DASHBOARD_ENABLED, DASHBOARD_PORT,
)
from dashboard import start_dashboard
from dashboard.state import shared_state

# Chat command patterns (regex, processed before planner)
_CMD_REMEMBER = re.compile(
    r"@(all|\w+)\s+remember:\s*(.+)", re.IGNORECASE | re.DOTALL
)
_CMD_AREA = re.compile(
    r"@(all|\w+)\s+area:\s*(.+)", re.IGNORECASE | re.DOTALL
)
_CMD_FORGET = re.compile(
    r"@(all|\w+)\s+forget:\s*(.+)", re.IGNORECASE | re.DOTALL
)

# Shared state across all bot runners (set in run())
_task_board = None
_transmute = None  # TransmuteDB instance
_transmute_tags = {}  # normalized_alias -> registry_id (built at startup)
_container_db = None  # ContainerDB instance
_all_runners = {}  # name -> BotRunner
_terrain = None  # TerrainDB instance
_orchestration_lock = threading.Lock()
_orchestrated_messages = {}  # message_text -> coordinator bot name
_ALL_BOTS_RE = re.compile(r"\b(all\s+bots?|every\s*one|every\s+bot|everybody)\b", re.IGNORECASE)
_COUNT_IN_STEP_RE = re.compile(r"(\d+)\s*x\s+|\((\d+)\)|\s(\d+)$")

CHAT_POLL_INTERVAL = 0.25


class BotRunner:
    """Runs the observe/think/act loop for a single bot in its own thread."""

    def __init__(self, profile):
        self.profile = profile
        self.name = profile["name"]
        self.model = profile.get("model", "llama3.1:8b")
        self.specializations = profile.get("specializations", ["general"])
        self.chat_history = []
        self.conversation_history = []
        self.memory_entries = []
        self.system_prompt = ""
        self.semantic_mem = None
        self._last_action_results = []
        self._new_messages = []
        self._thread = None
        self._chat_thread = None
        self._stop_event = threading.Event()
        self._chat_event = threading.Event()
        self._plan_steps = []
        self._plan_step_idx = 0
        self._plan_instruction = ""
        self._l1_failed_steps = set()
        self._l3_retries = 0
        self._l4_escalations = 0
        self._last_failure_context = ""
        self._awaiting_taskboard = False
        self._current_task_id = None
        self._following_player = None
        self._cached_inventory = []  # updated on each observe tick
        self._terrain_tick = 0
        self._lock = threading.Lock()
        self._memory_file = os.path.join(
            os.path.dirname(__file__), f"memory_{self.name.lower()}.json"
        )

    def start(self):
        api.spawn(self.name)
        time.sleep(0.5)
        try:
            api.stop(self.name)
        except Exception:
            pass
        self.memory_entries = mem_module.load_from(self._memory_file)

        try:
            self.semantic_mem = sem.SemanticMemory(self.name, OLLAMA_URL, PG_DSN)
            self.semantic_mem.connect()
            stats = self.semantic_mem.stats()
            print(f"[{self.name}] Semantic memory: {stats['total']} memories ({stats['cached']} cached)")
        except Exception as e:
            print(f"[{self.name}] Semantic memory unavailable: {e}")
            self.semantic_mem = None

        self.system_prompt = prompts.build_system_prompt(self.profile, self.memory_entries)
        self._stop_event.clear()
        self._chat_event.clear()
        self._thread = threading.Thread(target=self._loop, name=f"bot-{self.name}", daemon=True)
        self._chat_thread = threading.Thread(target=self._chat_poll_loop, name=f"chat-{self.name}", daemon=True)
        self._thread.start()
        self._chat_thread.start()
        print(f"[{self.name}] Started (model={self.model})")

    def stop(self):
        self._stop_event.set()
        self._chat_event.set()
        try:
            api.stop(self.name)
            api.despawn(self.name)
        except Exception:
            pass
        if self._thread:
            self._thread.join(timeout=10)
        if self._chat_thread:
            self._chat_thread.join(timeout=5)
        if self.semantic_mem:
            self.semantic_mem.close()
        print(f"[{self.name}] Stopped")

    def _chat_poll_loop(self):
        """Fast-polling thread that watches for incoming chat and signals the main loop."""
        while not self._stop_event.is_set():
            try:
                inbox = api.chat_inbox(self.name)
                msgs = inbox.get("messages", [])
                if msgs:
                    with self._lock:
                        for msg in msgs:
                            entry = f"{msg['sender']}: {msg['message']}"
                            self.chat_history.append(entry)
                            if len(self.chat_history) > MAX_CHAT_HISTORY:
                                self.chat_history.pop(0)
                            self._new_messages.append(entry)
                    self._chat_event.set()
            except Exception:
                pass
            self._stop_event.wait(CHAT_POLL_INTERVAL)

    def _handle_chat_commands(self, new_messages):
        """Process special chat commands (remember, area, forget) before the planner.

        Returns a filtered list of messages with consumed commands removed.
        """
        if not new_messages:
            return new_messages
        remaining = []
        for msg in new_messages:
            parts = msg.split(": ", 1)
            if len(parts) < 2:
                remaining.append(msg)
                continue
            sender, text = parts
            if sender == self.name or sender in _all_runners:
                remaining.append(msg)
                continue

            consumed = False

            # @all remember: <knowledge> or @BotName remember: <knowledge>
            m = _CMD_REMEMBER.match(text)
            if m:
                target, content = m.group(1), m.group(2).strip()
                if target.lower() == "all" or target.lower() == self.name.lower():
                    self._inject_knowledge(content, sender)
                    consumed = True

            # @all area: <description> or @BotName area: <x1,y1,z1 to x2,y2,z2>
            if not consumed:
                m = _CMD_AREA.match(text)
                if m:
                    target, content = m.group(1), m.group(2).strip()
                    if target.lower() == "all" or target.lower() == self.name.lower():
                        self._set_work_area(content, sender)
                        consumed = True

            # @all forget: <query> or @BotName forget: <query>
            if not consumed:
                m = _CMD_FORGET.match(text)
                if m:
                    target, content = m.group(1), m.group(2).strip()
                    if target.lower() == "all" or target.lower() == self.name.lower():
                        self._forget_knowledge(content, sender)
                        consumed = True

            if not consumed:
                remaining.append(msg)

        return remaining

    def _inject_knowledge(self, content, sender):
        """Store player-provided knowledge in semantic memory."""
        category = "knowledge"
        if any(w in content.lower() for w in ["at ", "near ", "location", "coords"]):
            category = "location"
        elif any(w in content.lower() for w in ["always ", "never ", "rule", "instruction"]):
            category = "instruction"

        self.memory_entries = mem_module.add_to(
            self.memory_entries, content, self._memory_file
        )
        if self.semantic_mem:
            try:
                mid = self.semantic_mem.store(content, category=category)
                self.semantic_mem.store_shared(
                    f"(from player {sender}) {content}", category=category
                )
                print(f"[{self.name}/knowledge] Stored [{category}]: {content[:80]} (id={mid})")
            except Exception as e:
                print(f"[{self.name}/knowledge] Store error: {e}")
        api.chat(self.name, f"Got it, I'll remember that.")

    def _set_work_area(self, content, sender):
        """Parse and store a work area designation."""
        area_text = f"[instruction] My designated work area: {content}"
        self.memory_entries = mem_module.add_to(
            self.memory_entries, area_text, self._memory_file
        )
        if self.semantic_mem:
            try:
                mid = self.semantic_mem.store(area_text, category="instruction")
                print(f"[{self.name}/area] Set work area: {content[:80]} (id={mid})")
            except Exception as e:
                print(f"[{self.name}/area] Store error: {e}")
        self.system_prompt = prompts.build_system_prompt(self.profile, self.memory_entries)
        api.chat(self.name, f"Work area set: {content[:60]}")

    def _forget_knowledge(self, query, sender):
        """Remove matching knowledge from memory."""
        removed = 0
        self.memory_entries = [
            m for m in self.memory_entries
            if query.lower() not in m.lower()
        ]
        mem_module.save_to(self.memory_entries, self._memory_file)
        if self.semantic_mem:
            try:
                results = self.semantic_mem.recall(query, limit=3)
                for r in results:
                    if r.get("similarity", 0) > 0.7:
                        self.semantic_mem.delete(r["id"])
                        removed += 1
            except Exception as e:
                print(f"[{self.name}/forget] Error: {e}")
        print(f"[{self.name}/forget] Removed {removed} memories matching: {query[:60]}")
        api.chat(self.name, f"Forgot {removed} thing(s) about '{query[:40]}'.")

    def _consume_message(self, msg):
        """Remove a processed message from chat_history so the LLM doesn't replay it."""
        with self._lock:
            try:
                self.chat_history.remove(msg)
            except ValueError:
                pass

    def _maybe_plan(self, new_messages):
        """If new messages contain a player instruction, run the planner."""
        if not new_messages:
            return
        for msg in reversed(new_messages):
            parts = msg.split(": ", 1)
            if len(parts) < 2:
                continue
            sender, text = parts
            if sender == self.name:
                continue
            text_lower = text.lower().strip()
            if len(text_lower) < 5:
                continue
            skip_words = ["hello", "hi ", "hey", "thanks", "thank you", "yes", "no", "ok"]
            if any(text_lower.startswith(w) for w in skip_words):
                continue

            # Determine if this came from another bot (not a real player)
            from_bot = sender in _all_runners

            # Player commands always override current work
            if not from_bot:
                if self._plan_steps and self._plan_step_idx < len(self._plan_steps):
                    self._store_plan_outcome(success=False, failure_reason=f"Overridden by player: {text[:60]}")
                self._plan_steps = []
                self._plan_step_idx = 0
                self._plan_instruction = ""
                self._l1_failed_steps = set()
                self._following_player = None
                if self._current_task_id and _task_board:
                    try:
                        _task_board.release(self._current_task_id)
                    except Exception:
                        pass
                    self._current_task_id = None
                self._awaiting_taskboard = False
                try:
                    api.cancel_directive(self.name)
                except Exception:
                    pass

            # If a bot sent us a task board notification, claim the task and
            # use pre-planned steps if available (skips re-decomposition).
            if from_bot and "Task #" in text and "for you:" in text:
                try:
                    task_id_str = text.split("Task #")[1].split()[0].rstrip(":")
                    tb_task_id = int(task_id_str)
                    if _task_board:
                        task_data = _task_board.get(tb_task_id)
                        if task_data and task_data.get("status") in ("done", "in_progress", "failed"):
                            self._consume_message(msg)
                            continue
                        _task_board.start(tb_task_id)
                        self._current_task_id = tb_task_id
                        if task_data and task_data.get("plan_steps"):
                            self._plan_steps = task_data["plan_steps"]
                            self._plan_step_idx = 0
                            self._plan_instruction = task_data.get("description", text)
                            self.conversation_history.clear()
                            step_list = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(self._plan_steps))
                            print(f"[{self.name}/taskboard] Claimed task #{tb_task_id} with pre-planned steps:\n{step_list}")
                            api.system_chat(self.name, f"Task #{tb_task_id}: {len(self._plan_steps)} steps", "yellow")
                            self._consume_message(msg)
                            return
                except (ValueError, IndexError):
                    pass
                text = text.split("for you:", 1)[1].strip()

            # Short-circuit: navigation and control commands → skip planner entirely
            _follow_phrases = ["follow me", "follow us", "keep following"]
            _goto_phrases = ["come to me", "come here", "get over here", "come over here",
                             "get to me", "walk to me", "run to me", "tp to me",
                             "to my location", "to me", "come to my"]
            _stop_phrases = ["stop following", "go idle", "stand still", "stay here", "stay put",
                             "halt", "wait here", "stop what you"]
            _stop_exact = ["stop"]
            is_follow = not from_bot and any(p in text_lower for p in _follow_phrases)
            is_goto = not from_bot and any(p in text_lower for p in _goto_phrases)
            is_stop = not from_bot and (
                any(p in text_lower for p in _stop_phrases)
                or any(text_lower.strip() == p for p in _stop_exact)
            )
            if is_follow or is_goto or is_stop:
                api.stop(self.name)
                self._consume_message(msg)
                if is_follow or is_goto:
                    api.set_directive(self.name, "FOLLOW", target=sender,
                                     extra={"distance": "3.0"})
                    self._following_player = sender
                    api.chat(self.name, f"On my way, {sender}!")
                    print(f"[{self.name}/nav] FOLLOW directive for {sender} (shortcut)")
                else:
                    self._following_player = None
                    api.chat(self.name, f"Standing by.")
                    print(f"[{self.name}/nav] Direct stop (shortcut)")
                return

            # Recall relevant memories to give the planner context
            memory_context = ""
            if self.semantic_mem:
                try:
                    memory_context = self.semantic_mem.recall_for_prompt(text, limit=6)
                except Exception as e:
                    print(f"[{self.name}/planner] memory recall error: {e}")

            # Bot-to-bot messages: NEVER orchestrate (prevents delegation loops).
            # Only use orchestrator for real player instructions when multiple bots available.
            if not from_bot and len(_all_runners) > 1 and _task_board:
                # Only ONE bot orchestrates per player message — the rest wait for task board.
                # If the message addresses a bot by name, that bot MUST be coordinator.
                msg_key = text.strip().lower()[:100]
                addressed_bot = None
                for name in _all_runners:
                    if name.lower() in msg_key:
                        addressed_bot = name
                        break

                with _orchestration_lock:
                    coordinator = _orchestrated_messages.get(msg_key)
                    if coordinator is None:
                        if addressed_bot and addressed_bot != self.name:
                            # Another bot is addressed — defer to them
                            _orchestrated_messages[msg_key] = addressed_bot
                            is_coordinator = False
                            coordinator = addressed_bot
                        else:
                            _orchestrated_messages[msg_key] = self.name
                            is_coordinator = True
                        if len(_orchestrated_messages) > 50:
                            oldest = list(_orchestrated_messages.keys())[:25]
                            for k in oldest:
                                _orchestrated_messages.pop(k, None)
                    else:
                        is_coordinator = (coordinator == self.name)

                if not is_coordinator:
                    print(f"[{self.name}/orchestrator] Skipping — {coordinator} is coordinating this task")
                    try:
                        api.stop(self.name)
                        api.system_chat(self.name, f"Waiting for tasks from {coordinator}...", "gray")
                    except Exception:
                        pass
                    if self._plan_steps and self._plan_step_idx < len(self._plan_steps):
                        self._store_plan_outcome(success=False, failure_reason=f"Interrupted: {text[:60]}")
                    self._plan_steps = []
                    self._plan_step_idx = 0
                    self._plan_instruction = ""
                    self._awaiting_taskboard = True
                    self._consume_message(msg)
                    self.conversation_history.clear()
                    return

                print(f"[{self.name}/orchestrator] Coordinating: {text[:80]}")
                api.system_chat(self.name, f"Orchestrating: {text[:60]}...", "gold")
                shared_state.push_event({"bot": self.name, "type": "orchestrate", "message": text[:120]})
                profiles = [r.profile for r in _all_runners.values()]
                tc = _transmute.get_context_string() if _transmute else ""
                inv_context = self._gather_all_inventories()
                orch_steps = planner.orchestrate(self.model, text, profiles, memory_context, tc, inv_context, sender=sender)

                # If the user addressed this bot by name, keep all "any" steps
                text_lower = text.lower()
                user_addressed_me = self.name.lower() in text_lower

                # "All bots" enforcement: if the user wants every bot to do the SAME task,
                # ensure every bot gets a step with evenly-split counts.
                # Skip if the LLM already assigned diverse roles to many bots (role-based instruction).
                all_bot_names = list(_all_runners.keys())
                num_bots = len(all_bot_names)
                specific_assigns = {s.get("assign") for s in orch_steps if s.get("assign", "any") != "any" and s.get("assign") in _all_runners}
                unique_steps = {re.sub(r'\d+', '', s.get("step", "")).strip().lower() for s in orch_steps}
                is_role_based = len(specific_assigns) >= 3 and len(unique_steps) >= 3
                if _ALL_BOTS_RE.search(text) and num_bots > 1 and not is_role_based:

                    # Extract total count from the user instruction (e.g. "50" from "channel 50 ...")
                    instr_count_match = re.search(r"\b(\d+)\s*x?\s+", text)
                    total_from_instruction = int(instr_count_match.group(1)) if instr_count_match else None

                    # Use a template step from the LLM output
                    template_step = orch_steps[0] if orch_steps else {"step": text, "specialization": "any"}
                    step_text = template_step["step"]

                    # Calculate per-bot share
                    per_bot = total_from_instruction // num_bots if total_from_instruction else None
                    remainder = total_from_instruction % num_bots if total_from_instruction else 0

                    # Inject count into step text — find where to put "Nx " or replace existing count
                    def _inject_count(step, count):
                        if count is None:
                            return step
                        existing = _COUNT_IN_STEP_RE.search(step)
                        if existing:
                            g = existing.group(1) or existing.group(2) or existing.group(3)
                            return step[:existing.start()] + step[existing.start():existing.end()].replace(g, str(count), 1) + step[existing.end():]
                        # No count in step — insert "Nx " after the action verb
                        verb_match = re.match(r"(\w+\s+)", step)
                        if verb_match:
                            return step[:verb_match.end()] + f"{count}x " + step[verb_match.end():]
                        return f"{count}x {step}"

                    new_steps = []
                    for i, bot_name in enumerate(all_bot_names):
                        bot_count = per_bot + (1 if i < remainder else 0) if per_bot else None
                        new_steps.append({
                            "step": _inject_count(step_text, bot_count),
                            "assign": bot_name,
                            "specialization": template_step.get("specialization", "any"),
                        })
                    orch_steps = new_steps
                    print(f"[{self.name}/orchestrator] All-bots redistribution: {num_bots} bots, {per_bot}/ea" +
                          (f" (+1 for first {remainder})" if remainder else "") +
                          f": {[(s['assign'], s['step'][:50]) for s in orch_steps]}")

                # Inject grid-slicing info for coordinated WIDE_SEARCH steps
                ws_count = sum(1 for s in orch_steps if re.search(r"wide\s+search", s["step"], re.IGNORECASE))
                if ws_count > 1:
                    ws_idx = 0
                    for s in orch_steps:
                        if re.search(r"wide\s+search", s["step"], re.IGNORECASE):
                            s["step"] = f"{s['step']} [grid {ws_idx}/{ws_count}]"
                            ws_idx += 1
                    print(f"[{self.name}/orchestrator] Injected grid slicing for {ws_count} WIDE_SEARCH steps")

                my_steps = []
                # Group steps by assigned bot for batch delegation
                bot_steps = {}  # bot_name -> [(step_desc, spec), ...]
                for s in orch_steps:
                    assigned = s.get("assign", "any")
                    step_desc = s["step"]
                    spec = s.get("specialization", "any")

                    keep = (assigned == self.name
                            or assigned not in _all_runners
                            or (assigned == "any" and user_addressed_me))
                    if keep:
                        my_steps.append(step_desc)
                    else:
                        bot_steps.setdefault(assigned, []).append((step_desc, spec))

                # Post one task per bot with pre-planned steps (skips decompose)
                delegated = []
                for assigned, steps_specs in bot_steps.items():
                    step_descs = [s[0] for s in steps_specs]
                    spec = steps_specs[0][1]  # use first step's specialization
                    summary = f"{text[:60]} ({len(step_descs)} steps)"
                    task_id = _task_board.post(
                        description=summary,
                        created_by=self.name,
                        specialization=spec,
                        assigned_to=assigned if assigned != "any" else None,
                        plan_steps=step_descs,
                    )
                    BotRunner.send_bot_message(
                        self.name, assigned,
                        f"Task #{task_id} for you: {summary}"
                    )
                    delegated.append((assigned, summary))
                    step_list = ", ".join(s[:40] for s in step_descs)
                    print(f"[{self.name}/orchestrator] Delegated to {assigned} (task #{task_id}, {len(step_descs)} steps): {step_list}")
                    shared_state.push_event({"bot": self.name, "type": "delegated", "to": assigned, "task_id": task_id, "steps": step_descs[:5]})

                # Broadcast orchestration summary to chat
                for assigned, desc in delegated:
                    api.system_chat(self.name, f"{assigned} -> {desc[:50]}", "aqua")
                if my_steps:
                    self._plan_steps = my_steps
                    self._plan_step_idx = 0
                    self._plan_instruction = text
                    self._l4_escalations = 0
                    self.conversation_history.clear()
                    step_list = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(my_steps))
                    print(f"[{self.name}/orchestrator] My steps ({len(my_steps)}):\n{step_list}")
                    for i, s in enumerate(my_steps):
                        api.system_chat(self.name, f"#{i+1}: {s[:50]}", "dark_aqua")
                else:
                    print(f"[{self.name}/orchestrator] All steps delegated to other bots")
                self._consume_message(msg)
            else:
                print(f"[{self.name}/planner] Decomposing: {text[:80]}")
                if memory_context and memory_context != "No relevant memories.":
                    print(f"[{self.name}/planner] Using {memory_context.count(chr(10))+1} memories as context")
                tc = _transmute.get_context_string() if _transmute else ""
                inv_context = self._get_my_inventory_summary()
                steps = planner.decompose(self.model, text, memory_context, tc, inv_context, sender=sender)
                self._plan_steps = steps
                self._plan_step_idx = 0
                self._plan_instruction = text
                self._l4_escalations = 0
                self.conversation_history.clear()
                step_list = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(steps))
                print(f"[{self.name}/planner] Plan ({len(steps)} steps):\n{step_list}")
                shared_state.push_event({"bot": self.name, "type": "plan_created", "instruction": text[:100], "steps": [s[:80] for s in steps]})
                self._consume_message(msg)
            return

    def _plan_context(self):
        """Build the plan section for the observation prompt."""
        if not self._plan_steps:
            return ""
        lines = []
        total = len(self._plan_steps)
        idx = self._plan_step_idx
        lines.append(f"## Active plan (from: \"{self._plan_instruction[:60]}\")")
        for i, step in enumerate(self._plan_steps):
            if i < idx:
                marker = "[DONE]"
            elif i == idx:
                marker = "[CURRENT <-- FOCUS ON THIS]"
            else:
                marker = "[TODO]"
            lines.append(f"  {i+1}. {marker} {step}")
        lines.append(f"\nYou are on step {idx+1} of {total}. Complete ONLY the current step.")
        lines.append('When the current step is COMPLETE, include "step_done": true in your response to advance to the next step.')
        return "\n".join(lines)

    def _advance_plan(self, response, tick_results=None):
        """Check if the LLM signaled step completion."""
        if not self._plan_steps:
            return
        if response.get("step_done"):
            # Block advancement if all actions failed or no actions were taken
            if tick_results is not None:
                ok_count = sum(1 for r in tick_results if r.startswith("OK "))
                fail_count = sum(1 for r in tick_results if r.startswith(("FAILED ", "ERROR ", "SKIPPED ")))
                if ok_count == 0 and fail_count > 0:
                    step = self._plan_steps[self._plan_step_idx]
                    print(f"[{self.name}/planner] Blocked step_done — all actions failed (step: \"{step}\")")
                    try:
                        api.system_chat(self.name, f"Step blocked: actions failed", "red")
                    except Exception:
                        pass
                    return
                actions = response.get("actions", [])
                if not actions and not tick_results:
                    step = self._plan_steps[self._plan_step_idx]
                    print(f"[{self.name}/planner] Blocked step_done — no actions taken (step: \"{step}\")")
                    return
            old_step = self._plan_steps[self._plan_step_idx]
            self._plan_step_idx += 1
            if self._plan_step_idx >= len(self._plan_steps):
                print(f"[{self.name}/planner] Plan COMPLETE! All {len(self._plan_steps)} steps done.")
                try:
                    api.system_chat(self.name, f"Plan complete! ({len(self._plan_steps)} steps done)", "green")
                except Exception:
                    pass
                shared_state.push_event({"bot": self.name, "type": "plan_complete", "steps": len(self._plan_steps)})
                self._store_plan_outcome(success=True)
                if self._current_task_id:
                    self._complete_task_board_task()
                else:
                    try:
                        api.xp_give(self.name, levels=2)
                    except Exception:
                        pass
                self._plan_steps = []
                self._plan_step_idx = 0
                self._plan_instruction = ""
            else:
                new_step = self._plan_steps[self._plan_step_idx]
                print(f"[{self.name}/planner] Step done: \"{old_step}\" -> now: \"{new_step}\" ({self._plan_step_idx+1}/{len(self._plan_steps)})")
                shared_state.push_event({"bot": self.name, "type": "step_done", "completed": old_step[:80], "next": new_step[:80], "progress": f"{self._plan_step_idx}/{len(self._plan_steps)}"})
                try:
                    api.system_chat(self.name, f"Step {self._plan_step_idx}/{len(self._plan_steps)}: {new_step[:50]}", "dark_aqua")
                except Exception:
                    pass
                self.conversation_history.clear()

    def _store_plan_outcome(self, success, failure_reason=""):
        """Store plan outcome in semantic memory for future planning."""
        if not self.semantic_mem or not self._plan_instruction:
            return
        try:
            steps_str = " -> ".join(self._plan_steps)
            if success:
                content = (
                    f"[knowledge] Plan succeeded: \"{self._plan_instruction[:80]}\". "
                    f"Steps that worked: {steps_str}"
                )
            else:
                completed = self._plan_steps[:self._plan_step_idx]
                failed_step = self._plan_steps[self._plan_step_idx] if self._plan_step_idx < len(self._plan_steps) else "unknown"
                content = (
                    f"[knowledge] Plan failed at step {self._plan_step_idx+1}: \"{failed_step}\". "
                    f"Original task: \"{self._plan_instruction[:80]}\". "
                    f"Reason: {failure_reason or 'unknown'}. "
                    f"Completed steps: {' -> '.join(completed) if completed else 'none'}"
                )
            mid = self.semantic_mem.store(content, category="knowledge")
            print(f"[{self.name}/planner] Stored plan outcome (id={mid})")
        except Exception as e:
            print(f"[{self.name}/planner] Failed to store outcome: {e}")

    def _check_task_board(self):
        """If idle (no plan), check the shared task board for pending tasks."""
        if self._plan_steps or not _task_board or self._following_player:
            return
        try:
            task = _task_board.claim(self.name, self.specializations + ["any"])
            if task:
                self._current_task_id = task["id"]
                self._awaiting_taskboard = False
                desc = task["description"]
                _task_board.start(task["id"])
                print(f"[{self.name}/taskboard] Claimed task #{task['id']}: {desc[:60]}")
                shared_state.push_event({"bot": self.name, "type": "task_claimed", "task_id": task["id"], "description": desc[:80]})
                try:
                    api.system_chat(self.name, f"Claimed task: {desc[:50]}", "yellow")
                except Exception:
                    pass

                if task.get("plan_steps"):
                    self._plan_steps = task["plan_steps"]
                    self._plan_step_idx = 0
                    self._plan_instruction = desc
                    self._l4_escalations = 0
                    self.conversation_history.clear()
                    step_list = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(self._plan_steps))
                    print(f"[{self.name}/taskboard] Pre-planned ({len(self._plan_steps)} steps):\n{step_list}")
                else:
                    memory_context = ""
                    if self.semantic_mem:
                        try:
                            memory_context = self.semantic_mem.recall_all_for_prompt(desc, limit=6)
                        except Exception:
                            pass
                    print(f"[{self.name}/planner] Decomposing task board task: {desc[:80]}")
                    tc = _transmute.get_context_string() if _transmute else ""
                    inv_context = self._get_my_inventory_summary()
                    steps = planner.decompose(self.model, desc, memory_context, tc, inv_context)
                    self._plan_steps = steps
                    self._plan_step_idx = 0
                    self._plan_instruction = desc
                    self._l4_escalations = 0
                    self.conversation_history.clear()
                    step_list = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(steps))
                    print(f"[{self.name}/planner] Plan ({len(steps)} steps):\n{step_list}")
        except Exception as e:
            print(f"[{self.name}/taskboard] Error checking board: {e}")

    def _complete_task_board_task(self):
        """Mark the current task board task as done and reward XP."""
        if self._current_task_id and _task_board:
            try:
                _task_board.complete(self._current_task_id, "Plan completed successfully")
                print(f"[{self.name}/taskboard] Task #{self._current_task_id} completed")
                # Reward XP for completing a task
                try:
                    api.xp_give(self.name, levels=5)
                    print(f"[{self.name}] +5 XP levels (task completion reward)")
                except Exception:
                    pass
            except Exception as e:
                print(f"[{self.name}/taskboard] Error completing task: {e}")
            self._current_task_id = None

    def _fail_task_board_task(self, reason=""):
        """Mark the current task board task as failed."""
        if self._current_task_id and _task_board:
            try:
                _task_board.fail(self._current_task_id, reason)
                print(f"[{self.name}/taskboard] Task #{self._current_task_id} failed: {reason}")
            except Exception as e:
                print(f"[{self.name}/taskboard] Error failing task: {e}")
            self._current_task_id = None

    @staticmethod
    def send_bot_message(from_bot, to_bot, message):
        """Send a message from one bot to another via inject_chat."""
        if to_bot in _all_runners:
            target = _all_runners[to_bot]
            with target._lock:
                entry = f"{from_bot}: {message}"
                target.chat_history.append(entry)
                if len(target.chat_history) > MAX_CHAT_HISTORY:
                    target.chat_history.pop(0)
                target._new_messages.append(entry)
            target._chat_event.set()
            print(f"[{from_bot} -> {to_bot}] {message}")
            return True
        return False

    def _share_discovery(self, content, category):
        """Auto-share location and knowledge discoveries to shared memory."""
        if not self.semantic_mem:
            return
        shareable = category in ("location", "knowledge")
        if not shareable:
            return
        try:
            shared_content = f"[{category}] (from {self.name}) {content}"
            self.semantic_mem.store_shared(shared_content, category=category)
        except Exception:
            pass

    # ── Step classifier: maps plan step text → L1 directive or None (LLM path) ──

    _MINE_PATTERNS = re.compile(
        r"(?:find\s+(?:and\s+)?)?mine\s+(?:(?:nearby|some|more)\s+)?"
        r"(?:(\d+)x?\s+)?(?:minecraft:)?(\S+?)(?:\s+(?:\(.*?(\d+).*?\)|x\s*(\d+)|at\s+least\s+(\d+)))?(?:\s+\(.*\))?$",
        re.IGNORECASE,
    )
    _CRAFT_PATTERNS = re.compile(
        r"craft\s+(?:(?:and\s+\w+\s+)?)?(?:(\d+)x?\s+)?(?:minecraft:)?(\S+?)(?:\s+x\s*(\d+)|\s*\((\d+)\))?\s*$",
        re.IGNORECASE,
    )
    _SMELT_PATTERNS = re.compile(
        r"smelt\s+(?:(\d+)x?\s+)?(?:minecraft:)?(\S+?)(?:\s+(?:into|to)\s+.+)?(?:\s+x\s*(\d+)|\s*\((\d+)\))?\s*$",
        re.IGNORECASE,
    )
    _GOTO_PATTERNS = re.compile(
        r"(?:go\s+to|goto|travel\s+to|walk\s+to|navigate\s+to)\s+(.+)",
        re.IGNORECASE,
    )
    _TELEPORT_PATTERNS = re.compile(
        r"(?:teleport|tp|warp|dimension.?travel)\s+(?:to\s+)?(?:(?:the\s+)?(nether|end|overworld)|(\S+?))\s*"
        r"(?:(?:at\s+)?(-?\d+)[,\s]+(-?\d+)[,\s]+(-?\d+))?",
        re.IGNORECASE,
    )
    _DIMENSION_ALIASES = {
        "nether": "minecraft:the_nether",
        "the_nether": "minecraft:the_nether",
        "the nether": "minecraft:the_nether",
        "end": "minecraft:the_end",
        "the_end": "minecraft:the_end",
        "the end": "minecraft:the_end",
        "overworld": "minecraft:overworld",
    }
    _ENCHANT_PATTERNS = re.compile(
        r"enchant\s+(?:(?:the|my|a)\s+)?(?:minecraft:)?(\S+?)(?:\s+(?:with|using|at|option)\s+.*)?$",
        re.IGNORECASE,
    )
    _BREW_PATTERNS = re.compile(
        r"(?:brew|make|create)\s+(?:(?:a\s+|some\s+)?(?:potion\s+of\s+|potions?\s+of\s+)?)?"
        r"(?:minecraft:)?(\S+?)(?:\s+(?:potion|potions))?(?:\s+x\s*(\d+))?$",
        re.IGNORECASE,
    )
    _CHANNEL_PATTERNS = re.compile(
        r"(?:channel|conjure|summon|transmute)\s+(?:(\d+)x?\s+)?(.+?)(?:\s+x\s*(\d+)|\s*\((\d+)\))?\s*$",
        re.IGNORECASE,
    )
    _SEND_ITEM_PATTERNS = re.compile(
        r"send(?:_item)?\s+(?:(\d+)x?\s+)?(\S+?)\s+(?:to\s+)?(\w+)(?:\s+x\s*(\d+))?\s*$",
        re.IGNORECASE,
    )
    _SEND_ITEM_ARROW = re.compile(
        r"SEND_ITEM\s+(?:(\d+)x?\s+)?(\S+?)>(\w+)\s*$",
        re.IGNORECASE,
    )
    _BUILD_PATTERNS = re.compile(
        r"(?:build|construct|create|make)\s+(?:a\s+)?(\w+)(?:\s+(?:with|using|from)\s+(?:minecraft:)?(\S+))?",
        re.IGNORECASE,
    )
    _VALID_BLUEPRINTS = {"shelter", "wall", "tower", "platform"}
    _FARM_PATTERNS = re.compile(
        r"(?:farm|plant|grow)\s+(?:a\s+)?(?:minecraft:)?(\w+)(?:\s+farm)?(?:\s+(?:with|using|from)\s+(?:minecraft:)?(\S+))?\s*$",
        re.IGNORECASE,
    )
    _VALID_CROPS = {"wheat", "carrot", "potato", "beetroot", "carrots", "potatoes", "wheat_seeds", "beetroot_seeds"}
    _CONTAINER_PLACE_PATTERNS = re.compile(
        r"(?:place|put|create|conjure|set\s*up)\s+(?:a\s+)?(?:container|chest|storage|box)",
        re.IGNORECASE,
    )
    _CONTAINER_SEARCH_PATTERNS = re.compile(
        r"(?:search|check|inspect|look\s+(?:in|through)|scan)\s+(?:(?:the\s+)?containers?|chests?|storage)|CONTAINER_SEARCH\s+\S+",
        re.IGNORECASE,
    )
    _CONTAINER_STORE_PATTERNS = re.compile(
        r"(?:store|deposit|stash|put)\s+(?:(\d+)x?\s+)?(?:minecraft:)?(\S+)\s+(?:in|into)\s+(?:a\s+)?(?:container|chest|storage)|CONTAINER_STORE\s+(?:(\d+)x?\s+)?(?:minecraft:)?(\S+)",
        re.IGNORECASE,
    )
    _CONTAINER_WITHDRAW_PATTERNS = re.compile(
        r"(?:withdraw|retrieve|take|grab|get)\s+(?:(\d+)x?\s+)?(?:minecraft:)?(\S+?)\s+(?:from\s+)?(?:container|chest|storage)|CONTAINER_WITHDRAW\s+(?:(\d+)x?\s+)?(?:minecraft:)?(\S+)",
        re.IGNORECASE,
    )

    DIRECTIVE_POLL_INTERVAL = 2.0

    @staticmethod
    def _resolve_transmute_target(raw):
        """Resolve a natural-language item name to a transmute registry ID.
        Uses the tag index (display names + generated aliases) for fuzzy matching."""
        if not _transmute:
            return None
        if _transmute.is_known(raw):
            return raw
        normalized = raw.lower().replace(" ", "_").rstrip("s")
        if _transmute_tags:
            if normalized in _transmute_tags:
                return _transmute_tags[normalized]
            raw_lower = raw.lower().replace(" ", "_")
            if raw_lower in _transmute_tags:
                return _transmute_tags[raw_lower]
            raw_nospace = raw.lower()
            if raw_nospace in _transmute_tags:
                return _transmute_tags[raw_nospace]
        all_items = _transmute.get_all()
        for prefix in ("create:", "minecraft:", "mekanism:", "thermal:", "ae2:"):
            candidate = prefix + normalized
            if candidate in all_items:
                return candidate
        for key in all_items:
            bare = key.split(":", 1)[-1] if ":" in key else key
            if bare == normalized or bare == raw.lower().replace(" ", "_"):
                return key
        return None

    _FILLER_WORDS = re.compile(
        r"\b(harvested|mined|smelted|gathered|collected|obtained|crafted|some|the|a)\s+",
        re.IGNORECASE,
    )
    _TRAILING_COUNT = re.compile(r"(\S)\s+(\d+)\s*$")
    _CRAFT_AND_PLACE_SUFFIX = re.compile(
        r"(craft\s+)(?:(?:and\s+\w+\s+)?)((?:minecraft:)?\S+)\s+and\s+place\s+(?:it)?",
        re.IGNORECASE,
    )

    def _normalize_step_text(self, text):
        """Normalize planner output into a format L1 regexes can parse."""
        # "Craft minecraft:furnace and place it" → "Craft and place minecraft:furnace"
        m = self._CRAFT_AND_PLACE_SUFFIX.search(text)
        if m:
            text = f"{m.group(1)}and place {m.group(2)}"

        # Strip filler adjectives: "harvested wheat" → "wheat"
        text = self._FILLER_WORDS.sub("", text)

        # Normalize multi-word item names to underscores using known items
        words = text.split()
        i = 0
        while i < len(words) - 1:
            pair = f"{words[i]} {words[i+1]}".lower()
            underscore = pair.replace(" ", "_")
            is_known = (
                underscore in mc_items.ALL_VALID_ITEMS
                or (_transmute_tags and pair in _transmute_tags)
                or (_transmute_tags and underscore in _transmute_tags)
            )
            if is_known:
                words[i] = words[i] + "_" + words[i+1]
                words.pop(i + 1)
            else:
                i += 1
        text = " ".join(words)

        # Trailing bare count: "Channel item 10" → "Channel item (10)"
        m = self._TRAILING_COUNT.search(text)
        if m and m.group(1) not in ("x", ")"):
            text = text[:m.end(1)] + " (" + m.group(2) + ")"

        return text.strip()

    def _classify_step(self, step_text):
        """Try to map a plan step to an L1 directive dict. Returns None if LLM path needed."""
        text = self._normalize_step_text(step_text.strip())

        # Mine
        m = self._MINE_PATTERNS.search(text)
        if m:
            count_pre = int(m.group(1)) if m.group(1) else None
            target = m.group(2).rstrip(",.")
            count_post = None
            for g in (m.group(3), m.group(4), m.group(5)):
                if g:
                    count_post = int(g)
                    break
            count = count_pre or count_post or 10
            return {"type": "MINE", "target": target, "count": count, "radius": 128}

        # Craft (including "craft and place")
        m = self._CRAFT_PATTERNS.search(text)
        if m:
            count_pre = int(m.group(1)) if m.group(1) else None
            target = m.group(2).rstrip(",.")
            if not target.startswith("minecraft:"):
                target = "minecraft:" + target
            count_post = int(m.group(3)) if m.group(3) else (int(m.group(4)) if m.group(4) else None)
            count = count_pre or count_post or 1
            return {"type": "CRAFT", "target": target, "count": count}

        # Smelt
        m = self._SMELT_PATTERNS.search(text)
        if m:
            count_pre = int(m.group(1)) if m.group(1) else None
            target = m.group(2).rstrip(",.")
            if not target.startswith("minecraft:"):
                target = "minecraft:" + target
            count_post = int(m.group(3)) if m.group(3) else (int(m.group(4)) if m.group(4) else None)
            count = count_pre or count_post or 1
            return {"type": "SMELT", "target": target, "count": count}

        # Enchant
        m = self._ENCHANT_PATTERNS.search(text)
        if m:
            target = m.group(1).rstrip(",.")
            if not target.startswith("minecraft:"):
                target = "minecraft:" + target
            extra = {}
            # Check for option level in text
            opt_match = re.search(r"option\s*(\d)", text)
            if opt_match:
                extra["option"] = opt_match.group(1)
            elif "best" in text.lower() or "max" in text.lower():
                extra["option"] = "2"
            elif "cheap" in text.lower() or "basic" in text.lower():
                extra["option"] = "0"
            else:
                extra["option"] = "2"
            return {"type": "ENCHANT", "target": target, "extra": extra}

        # Brew
        m = self._BREW_PATTERNS.search(text)
        if m:
            target = m.group(1).rstrip(",.")
            count = int(m.group(2)) if m.group(2) else 3
            return {"type": "BREW", "target": target, "count": count}

        # Channel from transmute registry (modded/discovered items)
        m = self._CHANNEL_PATTERNS.search(text)
        if m:
            count_pre = int(m.group(1)) if m.group(1) else None
            raw_target = m.group(2).rstrip(",. ")
            count_post = int(m.group(3)) if m.group(3) else (int(m.group(4)) if m.group(4) else None)
            count = count_pre or count_post or 1
            target = self._resolve_transmute_target(raw_target)
            if target:
                return {"type": "CHANNEL", "target": target, "count": count}

        # Send item to another bot (natural language: "send 10 iron_ingot to Forge")
        m = self._SEND_ITEM_PATTERNS.search(text)
        if not m:
            m = self._SEND_ITEM_ARROW.search(text)
        if m:
            count_pre = int(m.group(1)) if m.group(1) else None
            item = m.group(2).rstrip(",.")
            target_bot = m.group(3)
            count_post = int(m.group(4)) if m.lastindex >= 4 and m.group(4) else None
            count = count_pre or count_post or 1
            if not item.startswith("minecraft:") and ":" not in item:
                item = "minecraft:" + item
            return {"type": "SEND_ITEM", "target": f"{item}>{target_bot}", "count": count}

        # Build a structure
        m = self._BUILD_PATTERNS.search(text)
        if m:
            blueprint = m.group(1).lower()
            if blueprint in self._VALID_BLUEPRINTS:
                material = m.group(2) if m.group(2) else None
                extra = {}
                if material:
                    if ":" not in material:
                        material = "minecraft:" + material
                    extra["material"] = material
                return {"type": "BUILD", "target": blueprint, "extra": extra}

        # Farm crops
        m = self._FARM_PATTERNS.search(text)
        if m:
            crop = m.group(1).lower()
            if crop in self._VALID_CROPS or crop == "farm":
                if crop == "farm":
                    crop = "wheat"
                material = m.group(2) if m.group(2) else None
                extra = {}
                if material:
                    if ":" not in material:
                        material = "minecraft:" + material
                    extra["material"] = material
                return {"type": "FARM", "target": crop, "extra": extra}

        # Also catch "build farm" -> FARM directive (not BUILD)
        if m is None:
            m = self._BUILD_PATTERNS.search(text)
            if m and m.group(1).lower() == "farm":
                material = m.group(2) if m.group(2) else None
                extra = {}
                if material:
                    if ":" not in material:
                        material = "minecraft:" + material
                    extra["material"] = material
                return {"type": "FARM", "target": "wheat", "extra": extra}

        # Container place
        if self._CONTAINER_PLACE_PATTERNS.search(text):
            return {"type": "CONTAINER_PLACE"}

        # Container search
        m = self._CONTAINER_SEARCH_PATTERNS.search(text)
        if m:
            item_match = re.search(r"(?:for|find)\s+(?:(\d+)x?\s+)?(?:minecraft:)?(\S+)", text, re.IGNORECASE)
            if not item_match:
                item_match = re.search(r"CONTAINER_SEARCH\s+(?:(\d+)x?\s+)?(?:minecraft:)?(\S+)", text, re.IGNORECASE)
            params = {"type": "CONTAINER_SEARCH", "count": 5}
            if item_match:
                item = item_match.group(2).rstrip(",.")
                if ":" not in item:
                    item = "minecraft:" + item
                params["target"] = item
            return params

        # Container store
        m = self._CONTAINER_STORE_PATTERNS.search(text)
        if m:
            count_str = m.group(1) or m.group(3)
            item_str = m.group(2) or m.group(4)
            if item_str:
                item_str = item_str.rstrip(",.")
                if ":" not in item_str:
                    item_str = "minecraft:" + item_str
                count = int(count_str) if count_str else 64
                return {"type": "CONTAINER_STORE", "target": item_str, "count": count}

        # Container withdraw
        m = self._CONTAINER_WITHDRAW_PATTERNS.search(text)
        if m:
            count_str = m.group(1) or m.group(3)
            item_str = m.group(2) or m.group(4)
            if item_str:
                item_str = item_str.rstrip(",.")
                if ":" not in item_str:
                    item_str = "minecraft:" + item_str
                count = int(count_str) if count_str else 64
                return {"type": "CONTAINER_WITHDRAW", "target": item_str, "count": count}

        # Combat mode
        combat_match = re.search(
            r"(?:engage|enter|start|activate)\s+combat\s+(?:mode)?(?:\s+(\d+)s)?",
            text, re.IGNORECASE)
        if combat_match or re.search(r"combat\s+mode", text, re.IGNORECASE):
            duration = int(combat_match.group(1)) if combat_match and combat_match.group(1) else 300
            return {"type": "COMBAT", "count": duration, "radius": 128}

        # Attack specific target
        attack_match = re.search(
            r"(?:attack|fight|kill|hunt)\s+(?:all\s+)?(?:nearby\s+)?(?:minecraft:)?(\S+?)(?:\s+(\d+)s)?$",
            text, re.IGNORECASE)
        if attack_match:
            target = attack_match.group(1).rstrip(",.")
            duration = int(attack_match.group(2)) if attack_match.group(2) else 300
            return {"type": "COMBAT", "target": target, "count": duration, "radius": 128}

        # Follow player
        follow_match = re.search(
            r"(?:follow|come\s+to|goto_player|go\s+to\s+player)\s+(\S+)",
            text, re.IGNORECASE)
        if follow_match:
            target = follow_match.group(1).rstrip(",.")
            return {"type": "FOLLOW", "target": target}

        # Teleport to dimension / coordinates
        m = self._TELEPORT_PATTERNS.search(text)
        if m:
            dim_name = (m.group(1) or m.group(2) or "").lower().strip()
            dimension = self._DIMENSION_ALIASES.get(dim_name, dim_name if ":" in dim_name else None)
            x = float(m.group(3)) if m.group(3) else 0.0
            y = float(m.group(4)) if m.group(4) else 70.0
            z = float(m.group(5)) if m.group(5) else 0.0
            if dimension:
                return {
                    "type": "TELEPORT", "x": x, "y": y, "z": z,
                    "extra": {"dimension": dimension},
                }

        # Wide search
        ws_match = re.search(
            r"wide\s+search\s+(?:for\s+)?(?:minecraft:)?(\S+?)(?:\s+\(entity\))?(?:\s+\[grid\s+(\d+)/(\d+)\])?$",
            text, re.IGNORECASE)
        if ws_match:
            target = ws_match.group(1).rstrip(",.")
            search_type = "entity" if "(entity)" in text.lower() else "block"
            extra = {"search_type": search_type, "radius": "512"}
            if ws_match.group(2) is not None:
                extra["bot_index"] = ws_match.group(2)
                extra["bot_count"] = ws_match.group(3)
            return {
                "type": "WIDE_SEARCH",
                "target": target,
                "extra": extra,
            }

        # Goto coordinates (x, y, z pattern)
        coord_match = re.search(r"(-?\d+)[,\s]+(-?\d+)[,\s]+(-?\d+)", text)
        if coord_match and any(w in text.lower() for w in ("go to", "goto", "travel", "navigate", "walk")):
            return {
                "type": "GOTO",
                "x": float(coord_match.group(1)),
                "y": float(coord_match.group(2)),
                "z": float(coord_match.group(3)),
            }

        return None

    def _get_my_inventory_summary(self):
        """Format this bot's cached inventory for the planner."""
        items = self._cached_inventory
        if not items:
            return ""
        lines = []
        for it in items:
            if it.get("item"):
                lines.append(f"{it['item']} x{it['count']}")
        if not lines:
            return ""
        return f"{self.name}: {', '.join(lines[:20])}"

    def _gather_all_inventories(self):
        """Gather inventory summaries from all bot runners (uses cached snapshots)."""
        summaries = []
        for name, runner in _all_runners.items():
            items = runner._cached_inventory
            if not items:
                summaries.append(f"- {name}: empty")
                continue
            lines = []
            for it in items[:15]:
                if it.get("item"):
                    lines.append(f"{it['item']} x{it['count']}")
            if lines:
                summaries.append(f"- {name}: {', '.join(lines)}")
            else:
                summaries.append(f"- {name}: empty")
        return "\n".join(summaries) if summaries else ""

    L2_MAX_RETRIES = 3

    def _run_directive(self, directive_params):
        """L2 layer: send directive to L1 brain, poll, retry with adjustments on failure."""
        original_params = dict(directive_params)
        retries = 0

        while retries <= self.L2_MAX_RETRIES and not self._stop_event.is_set():
            params = dict(directive_params)
            dtype = params.pop("type")

            try:
                resp = api.set_directive(self.name, dtype, **params)
                status_msg = resp.get('status', 'unknown')
                print(f"[{self.name}/L1] Directive sent: {dtype} {params} -> {status_msg}")
                shared_state.push_event({"bot": self.name, "type": "directive_started", "directive": dtype, "target": params.get("target", ""), "count": params.get("count", ""), "retry": retries})
                if retries == 0:
                    api.system_chat(self.name, f"L1: {dtype} {params.get('target', '')}", "dark_aqua")
            except Exception as e:
                print(f"[{self.name}/L1] Failed to send directive: {e}")
                return {"success": False, "reason": str(e)}

            result = self._poll_directive()
            if result.get("reason") == "interrupted_by_chat":
                return result
            if result["success"]:
                # Store location memory on success
                self._store_success_memory(dtype, params, result.get("progress", {}))
                return result

            # L1 failed — L2 analyzes and retries
            reason = result.get("reason", "unknown")
            retries += 1
            if retries > self.L2_MAX_RETRIES:
                break

            adjusted = self._l2_adjust(dtype, params, reason)
            if adjusted is None:
                print(f"[{self.name}/L2] No adjustment possible for: {reason}")
                break

            directive_params = adjusted
            print(f"[{self.name}/L2] Retry {retries}/{self.L2_MAX_RETRIES}: {adjusted}")
            shared_state.push_event({"bot": self.name, "type": "l2_retry", "retry": retries, "reason": reason[:80]})
            api.system_chat(self.name, f"L2 retry {retries}: {reason[:30]}", "yellow")

        return {"success": False, "reason": result.get("reason", "unknown")}

    def _poll_directive(self):
        """Poll the brain until directive completes, fails, or is interrupted."""
        self._directive_missing_count = 0
        _last_poll_error_time = 0
        _ever_saw_directive = False
        while not self._stop_event.is_set():
            with self._lock:
                if self._new_messages:
                    new_player_msgs = [
                        m for m in self._new_messages
                        if ": " in m and m.split(": ", 1)[0] not in _all_runners
                    ]
                    if new_player_msgs:
                        print(f"[{self.name}/L1] Interrupted by chat, cancelling directive")
                        try:
                            api.cancel_directive(self.name)
                        except Exception:
                            pass
                        return {"success": False, "reason": "interrupted_by_chat"}

            try:
                brain_state = api.get_brain(self.name)
            except Exception as e:
                print(f"[{self.name}/L1] Poll error: {e}")
                _last_poll_error_time = time.time()
                self._stop_event.wait(self.DIRECTIVE_POLL_INTERVAL)
                continue

            directive_info = brain_state.get("directive")
            if not directive_info:
                self._directive_missing_count += 1
                recently_had_errors = (time.time() - _last_poll_error_time) < 30
                if recently_had_errors:
                    if self._directive_missing_count >= 3:
                        self._directive_missing_count = 0
                        print(f"[{self.name}/L1] Directive lost after connection errors (server restart?)")
                        shared_state.push_event({"bot": self.name, "type": "directive_lost", "reason": "server_restart"})
                        return {"success": False, "reason": "directive_lost_server_restart"}
                    self._stop_event.wait(1.0)
                    continue
                if not _ever_saw_directive:
                    if self._directive_missing_count >= 5:
                        self._directive_missing_count = 0
                        print(f"[{self.name}/L1] Directive never appeared (rejected or instant-cleared)")
                        return {"success": False, "reason": "directive_never_started"}
                    self._stop_event.wait(1.0)
                    continue
                if self._directive_missing_count >= 3:
                    self._directive_missing_count = 0
                    print(f"[{self.name}/L1] Directive cleared (assumed completed)")
                    return {"success": True, "progress": brain_state.get("progress", {})}
                self._stop_event.wait(1.0)
                continue
            else:
                self._directive_missing_count = 0
                _ever_saw_directive = True

            status = directive_info.get("status", "")
            if status == "COMPLETED":
                progress = brain_state.get("progress", {})
                print(f"[{self.name}/L1] Directive COMPLETED: {progress.get('counters', {})}")
                shared_state.push_event({"bot": self.name, "type": "directive_done", "status": "completed", "counters": progress.get("counters", {})})
                try:
                    api.cancel_directive(self.name)
                except Exception:
                    pass
                return {"success": True, "progress": progress}
            elif status in ("FAILED", "CANCELLED"):
                reason = directive_info.get("failure_reason", status.lower())
                print(f"[{self.name}/L1] Directive {status}: {reason}")
                shared_state.push_event({"bot": self.name, "type": "directive_done", "status": status.lower(), "reason": reason[:100]})
                try:
                    api.cancel_directive(self.name)
                except Exception:
                    pass
                return {"success": False, "reason": reason}

            progress = brain_state.get("progress", {})
            phase = progress.get("phase", "unknown")
            counters = progress.get("counters", {})
            state_desc = brain_state.get("state", "")
            print(f"[{self.name}/L1] {state_desc} (phase={phase}, counters={counters})")
            self._stop_event.wait(self.DIRECTIVE_POLL_INTERVAL)

        return {"success": False, "reason": "agent_stopped"}

    def _l2_adjust(self, dtype, params, reason):
        """L2 error analysis: adjust directive parameters based on failure reason."""
        reason_lower = reason.lower()

        # Mining: expand radius or try alternative block names
        if dtype == "MINE":
            if "could not find" in reason_lower:
                target = params.get("target", "")
                # Try alternative names
                alternatives = {
                    "log": ["oak_log", "birch_log", "spruce_log", "dark_oak_log"],
                    "oak_log": ["birch_log", "spruce_log", "jungle_log"],
                    "iron_ore": ["deepslate_iron_ore"],
                    "gold_ore": ["deepslate_gold_ore"],
                    "diamond_ore": ["deepslate_diamond_ore"],
                    "copper_ore": ["deepslate_copper_ore"],
                    "coal_ore": ["deepslate_coal_ore"],
                }
                if target in alternatives:
                    alt = alternatives[target]
                    # Pick next alternative we haven't tried
                    new_target = alt[0] if alt else None
                    if new_target:
                        return {"type": "MINE", "target": new_target,
                                "count": params.get("count", 1), "radius": 1024}
                # Just increase radius on retry
                current_radius = params.get("radius", 128)
                if current_radius < 1024:
                    return {"type": "MINE", "target": target,
                            "count": params.get("count", 1), "radius": 1024}

        # Crafting: most failures will be handled by L1 channeling now
        # But if recipe truly doesn't exist, no point retrying
        if dtype == "CRAFT":
            if "invalid item" in reason_lower or "no recipe" in reason_lower:
                return None  # Unrecoverable

        # Smelting: if furnace issues, L1 handles. Nothing to adjust here.
        if dtype == "SMELT":
            return None

        # Enchanting: L1 handles lapis channeling + meditation.
        # If table not found after full escalation, unrecoverable.
        if dtype == "ENCHANT":
            if "no enchantable item" in reason_lower:
                return None  # Nothing to enchant
            return None

        # Brewing: L1 handles ingredient channeling.
        # Unknown potion is unrecoverable.
        if dtype == "BREW":
            if "unknown potion" in reason_lower:
                return None
            return None

        # Channel: item not in registry is unrecoverable at L2.
        if dtype == "CHANNEL":
            if "not in transmute registry" in reason_lower:
                return None
            if "unknown item" in reason_lower:
                return None
            return None

        # Send item: if bot not found or item missing, unrecoverable.
        if dtype == "SEND_ITEM":
            return None

        # Build: out of materials might be recoverable if we mine more,
        # but that's a plan-level concern, not L2.
        if dtype == "BUILD":
            return None

        # Farm: crop/build failures are unrecoverable at L2.
        if dtype == "FARM":
            return None

        # Container ops: failures are unrecoverable at L2.
        if dtype in ("CONTAINER_PLACE", "CONTAINER_SEARCH", "CONTAINER_STORE", "CONTAINER_WITHDRAW"):
            return None

        return None

    def _store_success_memory(self, dtype, params, progress):
        """Store a brief memory on L1 success (location/event)."""
        if not self.semantic_mem:
            return
        try:
            if dtype == "MINE":
                target = params.get("target", "unknown")
                count = progress.get("counters", {}).get("blocks_mined", 0)
                if count > 0:
                    # Get bot position for location context
                    status = api.status(self.name)
                    pos = status.get("position", {})
                    text = f"Mined {count}x {target} near ({pos.get('x',0):.0f}, {pos.get('y',0):.0f}, {pos.get('z',0):.0f})"
                    self.semantic_mem.store(text, category="location")
            elif dtype == "CRAFT":
                target = params.get("target", "unknown")
                self.semantic_mem.store(f"Successfully crafted {target}", category="event")
        except Exception as e:
            print(f"[{self.name}/mem] store error after success: {e}")

        # Sync container registry changes to Postgres
        if dtype in ("CONTAINER_PLACE", "CONTAINER_SEARCH", "CONTAINER_STORE", "CONTAINER_WITHDRAW") and _container_db:
            try:
                _container_db.sync_from_mod()
            except Exception as e:
                print(f"[{self.name}/containers] sync error: {e}")

    # Known vanilla Minecraft items for primitive validation
    _VALID_MINE_TARGETS = {
        "oak_log", "birch_log", "spruce_log", "jungle_log", "acacia_log", "dark_oak_log",
        "cherry_log", "mangrove_log", "stone", "cobblestone", "deepslate", "cobbled_deepslate",
        "iron_ore", "deepslate_iron_ore", "gold_ore", "deepslate_gold_ore",
        "diamond_ore", "deepslate_diamond_ore", "coal_ore", "deepslate_coal_ore",
        "copper_ore", "deepslate_copper_ore", "lapis_ore", "deepslate_lapis_ore",
        "redstone_ore", "deepslate_redstone_ore", "emerald_ore", "deepslate_emerald_ore",
        "sand", "gravel", "dirt", "clay", "obsidian", "netherrack", "quartz_ore",
        "ancient_debris", "log", "logs", "ore",
    }

    def _validate_primitives(self, steps):
        """Filter out nonsensical L3 output — invalid items, bad coordinates, etc."""
        valid = []
        for step in steps:
            step_lower = step.lower()
            # Reject modded items
            if "mysticalagriculture" in step_lower or "essence" in step_lower:
                print(f"[{self.name}/L3-val] Rejected modded item: {step[:60]}")
                continue
            # Reject nonsense GOTO to origin/negative-y
            if "go to" in step_lower and "coordinates" in step_lower:
                import re
                coords = re.findall(r'[-\d.]+', step)
                if len(coords) >= 3:
                    x, y, z = float(coords[0]), float(coords[1]), float(coords[2])
                    if abs(x) + abs(y) + abs(z) < 5:
                        print(f"[{self.name}/L3-val] Rejected near-origin GOTO: {step[:60]}")
                        continue
                    if y < -64:
                        print(f"[{self.name}/L3-val] Rejected below-void GOTO: {step[:60]}")
                        continue
            # Reject items that don't exist (cobblestone_pickaxe etc.)
            if "craft" in step_lower:
                item = step_lower.split("craft")[-1].strip().replace("minecraft:", "")
                _NONEXISTENT = {"cobblestone_pickaxe", "cobblestone_sword", "cobblestone_axe",
                                "cobblestone_shovel", "cobblestone_hoe"}
                if any(bad in item for bad in _NONEXISTENT):
                    print(f"[{self.name}/L3-val] Rejected nonexistent item: {step[:60]}")
                    continue
            # Reject SEND_ITEM to non-existent bots
            if "send_item" in step_lower or ("send" in step_lower and ">" in step):
                known_bots = set(_all_runners.keys()) if _all_runners else set()
                bot_found = any(bn.lower() in step_lower for bn in known_bots)
                if not bot_found and known_bots:
                    print(f"[{self.name}/L3-val] Rejected SEND_ITEM to unknown bot: {step[:60]}")
                    continue
            valid.append(step)
        return valid if valid else None

    def _build_l3_prompt(self, failed_step, inv, failure_context=""):
        bot_names = ", ".join(sorted(_all_runners.keys())) if _all_runners else "none"
        failure_section = ""
        if failure_context:
            failure_section = f"""
FAILURE CONTEXT: {failure_context}
IMPORTANT: Use the failure context above to understand WHY the step failed. If the step was a CHANNEL/conjure action, output a CHANNEL primitive — do NOT replace it with MINE steps unless channeling is truly impossible. If parsing failed, reformat the same action as a valid primitive."""
        return f"""A Minecraft bot's plan step failed. Break it into smaller primitives.

PRIMITIVES you can use:
- {{"type": "MINE", "target": "<block>", "count": <n>}} — mine blocks
- {{"type": "CRAFT", "target": "minecraft:<item>", "count": <n>}} — craft items
- {{"type": "SMELT", "target": "<item>", "count": <n>}} — smelt in furnace
- {{"type": "GOTO", "x": <x>, "y": <y>, "z": <z>}} — walk to coordinates
- {{"type": "SEND_ITEM", "target": "<item_id>><bot_name>", "count": <n>}} — send items to another bot (ONLY use these bot names: {bot_names})
- {{"type": "BUILD", "target": "<blueprint>"}} — build a structure (shelter/wall/tower/platform)
- {{"type": "FARM", "target": "<crop>"}} — build and harvest a crop farm (wheat/carrot/potato/beetroot)
- {{"type": "CHANNEL", "target": "<modid:item>", "count": <n>}} — conjure/duplicate a discovered item using XP (for modded items that can't be crafted normally)
- {{"type": "CONTAINER_STORE", "target": "<item>", "count": <n>}} — store items from inventory into a container (auto-finds or conjures one)
- {{"type": "CONTAINER_WITHDRAW", "target": "<item>", "count": <n>}} — withdraw items from containers into inventory (auto-searches all containers)
- {{"type": "TELEPORT", "x": <x>, "y": <y>, "z": <z>, "extra": {{"dimension": "<dim>"}}}} — teleport to another dimension (minecraft:the_nether, minecraft:the_end, minecraft:overworld)

VALID MINE targets: cobblestone, stone, oak_log, birch_log, spruce_log, iron_ore, coal_ore, copper_ore, gold_ore, diamond_ore, lapis_ore, redstone_ore, emerald_ore, deepslate_iron_ore, deepslate_gold_ore, deepslate_diamond_ore, deepslate_lapis_ore, deepslate_redstone_ore, deepslate_emerald_ore, deepslate_coal_ore, deepslate_copper_ore, sand, gravel, clay, dirt, obsidian, netherrack, ancient_debris, quartz_ore, sugar_cane, bamboo, kelp, cactus
VALID CRAFT targets: stick, oak_planks, crafting_table, furnace, chest, wooden_pickaxe, wooden_axe, wooden_sword, wooden_shovel, stone_pickaxe, stone_axe, stone_sword, stone_shovel, iron_pickaxe, iron_axe, iron_sword, iron_shovel, diamond_pickaxe, diamond_sword, bucket, torch, ladder, iron_ingot, gold_ingot, copper_ingot, bread, bowl, paper, book, shears, bow, arrow, shield, bed, iron_helmet, iron_chestplate, iron_leggings, iron_boots, diamond_helmet, diamond_chestplate, diamond_leggings, diamond_boots, blast_furnace, smoker, anvil, brewing_stand, enchanting_table, bookshelf, rail, powered_rail, hopper, piston, golden_apple, golden_carrot
VALID SMELT targets: raw_iron, raw_gold, raw_copper, iron_ore, gold_ore, copper_ore, cobblestone, sand, clay_ball, oak_log, ancient_debris, potato, beef, raw_beef, porkchop, raw_porkchop, chicken, raw_chicken, mutton, raw_mutton, rabbit, raw_rabbit, cod, raw_cod, salmon, raw_salmon

FAILED STEP: "{failed_step}"
CURRENT INVENTORY: [{inv}]{failure_section}

Think about what sub-steps are needed. For example:
- To craft a stone_pickaxe: mine cobblestone, mine oak_log, then craft
- To smelt iron: mine iron_ore, craft a furnace, then smelt
- To mine underground: go to a cave entrance (y=40-60), then mine
- To channel/conjure a modded item: use CHANNEL with the exact modid:item_name

Respond with ONLY a JSON array. Example:
[{{"type": "MINE", "target": "cobblestone", "count": 8}}, {{"type": "MINE", "target": "oak_log", "count": 2}}, {{"type": "CRAFT", "target": "minecraft:furnace", "count": 1}}]"""

    def _l3_regenerate(self, failed_step, observation):
        """L3: Ask LLM to generate replacement L1 primitives for a failed step."""
        inv = ""
        try:
            inv_data = api.inventory(self.name)
            items = inv_data.get("inventory", [])
            inv = ", ".join(f"{it['item']} x{it['count']}" for it in items if it.get("item")) if items else "empty"
        except Exception:
            inv = "unknown"

        failure_ctx = getattr(self, '_last_failure_context', '')
        prompt = self._build_l3_prompt(failed_step, inv, failure_context=failure_ctx)

        try:
            response = brain.raw_generate(self.model, prompt)
            text = response.strip()
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                primitives = json.loads(text[start:end])
                if isinstance(primitives, list) and len(primitives) > 0:
                    valid, rejected = mc_items.validate_primitives(primitives)
                    if rejected:
                        reasons = ", ".join(r for _, r in rejected[:3])
                        print(f"[{self.name}/L3] Rejected {len(rejected)} primitives: {reasons}")
                    if not valid:
                        print(f"[{self.name}/L3] All primitives rejected")
                        return None
                    print(f"[{self.name}/L3] Got {len(valid)} valid primitives")
                    steps = []
                    known_bots = set(_all_runners.keys()) if _all_runners else set()
                    for p in valid:
                        ptype = p.get("type", "").upper()
                        target = p.get("target", "")
                        count = p.get("count", 1)
                        if ptype == "SEND_ITEM" and known_bots:
                            bot_in_target = any(bn in target for bn in known_bots)
                            if not bot_in_target:
                                print(f"[{self.name}/L3] Skipping SEND_ITEM to unknown bot: {target}")
                                continue
                        if ptype == "MINE":
                            steps.append(f"Find and mine {target} (at least {count})")
                        elif ptype == "CRAFT":
                            count_str = f"{count}x " if count > 1 else ""
                            steps.append(f"Craft {count_str}{target}")
                        elif ptype == "SMELT":
                            count_str = f"{count}x " if count > 1 else ""
                            steps.append(f"Smelt {count_str}{target} into ingots")
                        elif ptype == "CHANNEL":
                            count_str = f"{count}x " if count > 1 else ""
                            steps.append(f"Channel {count_str}{target}")
                        elif ptype == "CONTAINER_STORE":
                            steps.append(f"Store {count}x {target} into container")
                        elif ptype == "CONTAINER_WITHDRAW":
                            steps.append(f"Withdraw {count}x {target} from container")
                        elif ptype == "GOTO":
                            steps.append(f"Go to coordinates ({p.get('x',0)}, {p.get('y',0)}, {p.get('z',0)})")
                        elif ptype == "TELEPORT":
                            dim = p.get("extra", {}).get("dimension", "minecraft:overworld")
                            steps.append(f"Teleport to {dim} at ({p.get('x',0)}, {p.get('y',0)}, {p.get('z',0)})")
                        else:
                            steps.append(f"{ptype} {target}")
                    return steps if steps else None
            print(f"[{self.name}/L3] Could not parse response: {text[:100]}")
            return None
        except Exception as e:
            print(f"[{self.name}/L3] LLM call failed: {e}")
            return None

    def _l4_regenerate(self, failed_step, observation):
        """L4: Escalate to OpenAI API for primitive generation."""
        if not openai_brain.is_available():
            return None

        inv = ""
        try:
            inv_data = api.inventory(self.name)
            items = inv_data.get("inventory", [])
            inv = ", ".join(f"{it['item']} x{it['count']}" for it in items if it.get("item")) if items else "empty"
        except Exception:
            inv = "unknown"

        failure_ctx = getattr(self, '_last_failure_context', '')
        prompt = self._build_l3_prompt(failed_step, inv, failure_context=failure_ctx)

        try:
            response = openai_brain.generate_primitives(prompt)
            if not response:
                return None
            text = response.strip()
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                primitives = json.loads(text[start:end])
                if isinstance(primitives, list) and len(primitives) > 0:
                    valid, rejected = mc_items.validate_primitives(primitives)
                    if rejected:
                        reasons = ", ".join(r for _, r in rejected[:3])
                        print(f"[{self.name}/L4] Rejected {len(rejected)} primitives: {reasons}")
                    if not valid:
                        print(f"[{self.name}/L4] All primitives rejected")
                        return None
                    print(f"[{self.name}/L4] Got {len(valid)} valid primitives")
                    steps = []
                    known_bots = set(_all_runners.keys()) if _all_runners else set()
                    for p in valid:
                        ptype = p.get("type", "").upper()
                        target = p.get("target", "")
                        count = p.get("count", 1)
                        if ptype == "SEND_ITEM" and known_bots:
                            bot_in_target = any(bn in target for bn in known_bots)
                            if not bot_in_target:
                                print(f"[{self.name}/L4] Skipping SEND_ITEM to unknown bot: {target}")
                                continue
                        if ptype == "MINE":
                            steps.append(f"Find and mine {target} (at least {count})")
                        elif ptype == "CRAFT":
                            count_str = f"{count}x " if count > 1 else ""
                            steps.append(f"Craft {count_str}{target}")
                        elif ptype == "SMELT":
                            count_str = f"{count}x " if count > 1 else ""
                            steps.append(f"Smelt {count_str}{target} into ingots")
                        elif ptype == "CHANNEL":
                            count_str = f"{count}x " if count > 1 else ""
                            steps.append(f"Channel {count_str}{target}")
                        elif ptype == "CONTAINER_STORE":
                            steps.append(f"Store {count}x {target} into container")
                        elif ptype == "CONTAINER_WITHDRAW":
                            steps.append(f"Withdraw {count}x {target} from container")
                        elif ptype == "GOTO":
                            steps.append(f"Go to coordinates ({p.get('x',0)}, {p.get('y',0)}, {p.get('z',0)})")
                        elif ptype == "TELEPORT":
                            dim = p.get("extra", {}).get("dimension", "minecraft:overworld")
                            steps.append(f"Teleport to {dim} at ({p.get('x',0)}, {p.get('y',0)}, {p.get('z',0)})")
                        else:
                            steps.append(f"{ptype} {target}")
                    return steps if steps else None
            print(f"[{self.name}/L4] Could not parse response: {text[:100]}")
            return None
        except Exception as e:
            print(f"[{self.name}/L4] OpenAI call failed: {e}")
            return None

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                self._wait_for_idle_or_chat(timeout=10)
                obs, new_msgs = self._observe()

                new_msgs = self._handle_chat_commands(new_msgs)

                # Check for system reset signal
                if any("RESET: All tasks cleared" in m for m in new_msgs):
                    print(f"[{self.name}/reset] Received reset signal — clearing all state")
                    self._plan_steps = []
                    self._plan_step_idx = 0
                    self._plan_instruction = ""
                    self._l1_failed_steps = set()
                    self._current_task_id = None
                    self._awaiting_taskboard = False
                    self._following_player = None
                    self.conversation_history.clear()
                    if _task_board:
                        try:
                            _task_board.clear_all()
                        except Exception:
                            pass
                    with _orchestration_lock:
                        _orchestrated_messages.clear()
                    try:
                        api.cancel_directive(self.name)
                        api.stop(self.name)
                    except Exception:
                        pass
                    new_msgs = [m for m in new_msgs if "RESET:" not in m]
                    continue

                self._maybe_plan(new_msgs)

                if not self._plan_steps:
                    self._check_task_board()

                if self._awaiting_taskboard and not self._plan_steps:
                    self._stop_event.wait(TICK_DELAY)
                    continue

                # ── L1 directive path: try to classify current step ──
                l1_handled = False
                if self._plan_steps and self._plan_step_idx < len(self._plan_steps):
                    current_step = self._plan_steps[self._plan_step_idx]
                    # Skip L1 if this step already failed L1 (avoid infinite retry)
                    if current_step not in getattr(self, '_l1_failed_steps', set()):
                        directive = self._classify_step(current_step)
                        if directive is None:
                            self._last_failure_context = f"L1 could not parse this step into a known directive type. The step text did not match any recognized pattern (MINE, CRAFT, SMELT, CHANNEL, FOLLOW, BUILD, FARM, COMBAT, SEND_ITEM, CONTAINER_STORE, CONTAINER_WITHDRAW, GOTO, TELEPORT). Rephrase as a valid primitive."
                        if directive is not None:
                            print(f"[{self.name}/L1] Step \"{current_step}\" -> directive {directive['type']}")
                            api.system_chat(self.name, f"L1 step: {current_step[:50]}", "dark_aqua")
                            shared_state.push_event({"bot": self.name, "type": "l1_directive", "directive": directive["type"], "step": current_step[:80]})
                            result = self._run_directive(directive)

                            if result.get("reason") == "interrupted_by_chat":
                                continue

                            if result["success"]:
                                l1_handled = True
                                old_step = self._plan_steps[self._plan_step_idx]
                                self._plan_step_idx += 1
                                # Clear failed steps set on success (new step context)
                                if hasattr(self, '_l1_failed_steps'):
                                    self._l1_failed_steps.discard(old_step)
                                self._l3_retries = 0
                                self._last_failure_context = ""
                                if self._plan_step_idx >= len(self._plan_steps):
                                    print(f"[{self.name}/planner] Plan COMPLETE! All {len(self._plan_steps)} steps done.")
                                    api.system_chat(self.name, f"Plan complete! ({len(self._plan_steps)} steps done)", "green")
                                    self._store_plan_outcome(success=True)
                                    if self._current_task_id:
                                        self._complete_task_board_task()
                                    else:
                                        try:
                                            api.xp_give(self.name, levels=2)
                                        except Exception:
                                            pass
                                    self._plan_steps = []
                                    self._plan_step_idx = 0
                                    self._plan_instruction = ""
                                    self._l1_failed_steps = set()
                                else:
                                    new_step = self._plan_steps[self._plan_step_idx]
                                    print(f"[{self.name}/planner] L1 step done: \"{old_step}\" -> now: \"{new_step}\" ({self._plan_step_idx+1}/{len(self._plan_steps)})")
                                    api.system_chat(self.name, f"Step {self._plan_step_idx}/{len(self._plan_steps)}: {new_step[:50]}", "dark_aqua")
                                    self.conversation_history.clear()
                            else:
                                reason = result.get("reason", "unknown")
                                print(f"[{self.name}/L1] Directive failed: {reason} — falling back to LLM for this step")
                                api.system_chat(self.name, f"L1 failed: {reason[:40]}, using LLM", "yellow")
                                self._last_failure_context = f"L1 directive {directive['type']} failed with reason: {reason}. The bot tried to execute this as a {directive['type']} directive but the game-side behavior failed. Consider an alternative approach or fix the parameters."
                                # Mark step as L1-failed so we don't retry it
                                if not hasattr(self, '_l1_failed_steps'):
                                    self._l1_failed_steps = set()
                                self._l1_failed_steps.add(current_step)

                if l1_handled:
                    continue

                # ── If no plan, don't burn LLM cycles — just wait for work ──
                if not self._plan_steps:
                    self._stop_event.wait(TICK_DELAY)
                    continue

                # ── L3: LLM primitive regeneration (only when L1+L2 both failed) ──
                MAX_L3_RETRIES = 3

                current_step = self._plan_steps[self._plan_step_idx]

                if self._l3_retries >= MAX_L3_RETRIES:
                    # L4 escalation: try OpenAI before giving up
                    if not hasattr(self, '_l4_escalations'):
                        self._l4_escalations = 0
                    MAX_L4_ESCALATIONS = 2
                    l4_resolved = False
                    if openai_brain.is_available() and self._l4_escalations < MAX_L4_ESCALATIONS:
                        self._l4_escalations += 1
                        print(f"[{self.name}/L4] Escalating to OpenAI ({self._l4_escalations}/{MAX_L4_ESCALATIONS}): \"{current_step[:60]}\"")
                        api.system_chat(self.name, f"L4 escalation: {current_step[:40]}", "light_purple")
                        l4_prims = self._l4_regenerate(current_step, obs)
                        if l4_prims:
                            l4_prims = self._validate_primitives(l4_prims)
                        if l4_prims:
                            remaining = self._plan_steps[self._plan_step_idx + 1:]
                            self._plan_steps = (l4_prims + remaining)[:12]
                            self._plan_step_idx = 0
                            self._l3_retries = 0
                            self._l1_failed_steps = set()
                            self._last_failure_context = ""
                            api.system_chat(self.name, f"L4: {len(l4_prims)} new steps", "light_purple")
                            l4_resolved = True
                    if not l4_resolved:
                        print(f"[{self.name}] All tiers exhausted, skipping: \"{current_step[:60]}\"")
                        api.system_chat(self.name, f"Giving up on: {current_step[:40]}", "red")
                        self._plan_step_idx += 1
                        self._l3_retries = 0
                        self._l1_failed_steps = set()
                        self._last_failure_context = ""
                        if self._plan_step_idx >= len(self._plan_steps):
                            self._store_plan_outcome(success=False, failure_reason=f"All tiers failed on: {current_step}")
                            self._plan_steps = []
                            self._plan_step_idx = 0
                            self._plan_instruction = ""
                    self._stop_event.wait(TICK_DELAY)
                    continue

                self._l3_retries += 1
                print(f"[{self.name}/L3] Attempt {self._l3_retries}/{MAX_L3_RETRIES} for: \"{current_step[:60]}\"")
                api.system_chat(self.name, f"L3 ({self._l3_retries}/{MAX_L3_RETRIES}): {current_step[:40]}", "gold")

                new_primitives = self._l3_regenerate(current_step, obs)

                if new_primitives:
                    # Validate primitives before accepting
                    new_primitives = self._validate_primitives(new_primitives)

                if new_primitives:
                    print(f"[{self.name}/L3] Got {len(new_primitives)} valid primitives")
                    remaining = self._plan_steps[self._plan_step_idx + 1:]
                    self._plan_steps = (new_primitives + remaining)[:12]
                    self._plan_step_idx = 0
                    self._l1_failed_steps = set()
                    self._last_failure_context = ""
                    api.system_chat(self.name, f"L3: {len(new_primitives)} new steps", "gold")
                else:
                    print(f"[{self.name}/L3] No valid primitives, skipping step")
                    api.system_chat(self.name, f"Skipping failed step: {current_step[:40]}", "red")
                    self._plan_step_idx += 1
                    self._l3_retries = 0
                    self._l1_failed_steps = set()
                    self._last_failure_context = ""
                    if self._plan_step_idx >= len(self._plan_steps):
                        self._store_plan_outcome(success=False, failure_reason=f"L3 failed on: {current_step}")
                        self._plan_steps = []
                        self._plan_step_idx = 0
                        self._plan_instruction = ""

                self._stop_event.wait(TICK_DELAY)

            except Exception as e:
                print(f"[{self.name}/error] {e}")
                self._stop_event.wait(TICK_DELAY * 2)

    def _wait_for_idle_or_chat(self, timeout=10):
        """Wait for actions to finish, but interrupt immediately if chat arrives."""
        start = time.time()
        while time.time() - start < timeout:
            if self._stop_event.is_set():
                return
            if self._chat_event.is_set():
                self._chat_event.clear()
                return
            state = api.actions(self.name)
            is_idle = state.get("queued", 0) == 0 and state.get("current", "idle") == "idle"
            if is_idle:
                return
            self._stop_event.wait(BUSY_POLL_DELAY)

    def _observe(self):
        status = api.status(self.name)
        inv = api.inventory(self.name)
        ents = api.entities(self.name, OBSERVE_ENTITY_RADIUS)
        blks = api.blocks(self.name, OBSERVE_BLOCK_RADIUS)
        action_state = api.actions(self.name)

        self._cached_inventory = inv.get("inventory", [])

        with self._lock:
            chat_snapshot = list(self.chat_history)
            new_messages = list(self._new_messages[-5:])
            self._new_messages.clear()
            action_results = list(self._last_action_results)
            self._last_action_results = []

        obs = prompts.build_observation(
            status, inv, ents, blks, action_state, chat_snapshot, new_messages, action_results
        )

        shared_state.push_bot_snapshot(self.name, {
            "name": self.name,
            "model": self.model,
            "specializations": self.specializations,
            "status": status,
            "inventory": inv.get("inventory", []),
            "entities": ents.get("entities", []),
            "plan": {
                "instruction": self._plan_instruction or (f"Following {self._following_player}" if self._following_player else ""),
                "steps": list(self._plan_steps),
                "step_idx": self._plan_step_idx,
            },
            "awaiting_taskboard": self._awaiting_taskboard,
            "current_task_id": self._current_task_id,
            "l3_retries": self._l3_retries,
            "l4_escalations": self._l4_escalations,
        })

        self._terrain_tick += 1
        if _terrain and self._terrain_tick >= 15:
            self._terrain_tick = 0
            try:
                scan = api.surface_scan(self.name, radius=12)
                blocks = scan.get("blocks", [])
                dim = scan.get("dimension", "minecraft:overworld")
                if blocks:
                    _terrain.store_scan(blocks, dim)
            except Exception:
                pass

            if _container_db:
                try:
                    result = api.nearby_containers(self.name, radius=8)
                    found = result.get("containers", [])
                    dim = result.get("dimension", "minecraft:overworld")
                    for c in found:
                        x, y, z = c["x"], c["y"], c["z"]
                        if not _container_db.exists_at(x, y, z, dim):
                            cid = _container_db.register(x, y, z, dim, f"discovered:{self.name}")
                            api.raw_post("/containers", {"id": cid, "x": x, "y": y, "z": z, "dimension": dim, "placed_by": f"discovered:{self.name}"})
                            print(f"[{self.name}/containers] Discovered {c.get('block', 'chest')} at {x},{y},{z} [{dim}] -> #{cid}")
                            shared_state.push_event({"bot": self.name, "type": "container_found", "block": c.get("block", "chest"), "x": x, "y": y, "z": z, "dimension": dim})
                except Exception:
                    pass

        if _transmute and self._terrain_tick == 7 and self.name == list(_all_runners.keys())[0]:
            try:
                global _transmute_tags
                synced = _transmute.sync_from_mod()
                if synced > 0:
                    _transmute_tags = _build_transmute_tags()
                    print(f"[agent] Transmute registry refreshed: {synced} new items, {len(_transmute_tags)} aliases")
            except Exception:
                pass

        return obs, new_messages

    def _execute_actions(self, actions):
        results = []
        for act in actions:
            if not isinstance(act, dict):
                print(f"  [{self.name}] -> skipping malformed action: {act!r}")
                results.append(f"SKIPPED malformed action (expected dict, got {type(act).__name__})")
                continue
            name = act.get("action", "")
            if not name:
                print(f"  [{self.name}] -> skipping empty action name")
                results.append("SKIPPED empty action name")
                continue
            params = act.get("params") or {}
            if not isinstance(params, dict):
                print(f"  [{self.name}] -> skipping action {name}: params is not a dict")
                results.append(f"SKIPPED {name}: params must be a dict")
                continue

            if name in ("open_container", "take", "deposit"):
                session_results = self._run_container_session(params)
                results.extend(session_results)
                continue

            if name == "craft_session":
                session_results = self._run_craft_session(params)
                results.extend(session_results)
                continue

            try:
                resp = self._execute_one(name, params)
                error = None
                if isinstance(resp, dict):
                    error = resp.get("error")
                if error:
                    results.append(f"FAILED {name}({params}): {error}")
                    print(f"  [{self.name}] -> {name}: FAILED {error}")
                    self._learn_from_error(name, params, error)
                else:
                    # For query actions, include response data so the bot can see it
                    if name in ("xp_status", "find_blocks", "find_entities", "shop_list", "list_waypoints") and isinstance(resp, dict):
                        import json
                        data_str = json.dumps(resp, default=str)
                        if len(data_str) > 500:
                            data_str = data_str[:500] + "..."
                        results.append(f"OK {name}: {data_str}")
                    else:
                        results.append(f"OK {name}")
                    print(f"  [{self.name}] -> {name}: ok")
            except Exception as e:
                error_msg = str(e)
                results.append(f"ERROR {name}({params}): {error_msg}")
                print(f"  [{self.name}] -> {name}: ERROR {error_msg}")
                self._learn_from_error(name, params, error_msg)

        with self._lock:
            self._last_action_results = results

    def _find_nonempty_container(self):
        container_types = ["chest", "barrel", "trapped_chest", "shulker_box"]
        for ctype in container_types:
            found = api.find_blocks(self.name, ctype, 16, 5)
            for blk in found.get("blocks", []):
                pos = blk["position"]
                bx, by, bz = int(pos["x"]), int(pos["y"]), int(pos["z"])
                contents = api.container(self.name, bx, by, bz)
                if contents.get("items"):
                    return bx, by, bz, len(contents["items"])
        return None

    def _run_container_session(self, params):
        x, y, z = params.get("x", 0), params.get("y", 0), params.get("z", 0)

        needs_search = (x == 0 and y == 0 and z == 0)
        if not needs_search:
            contents = api.container(self.name, x, y, z)
            if not contents.get("items"):
                print(f"  [{self.name}] Container at ({x}, {y}, {z}) is empty, searching for non-empty one")
                needs_search = True

        if needs_search:
            best = self._find_nonempty_container()
            if best:
                x, y, z = best[0], best[1], best[2]
                print(f"  [{self.name}] Auto-detected non-empty container at ({x}, {y}, {z}) with {best[3]} items")
            else:
                print(f"  [{self.name}] No non-empty container found nearby")
                return ["FAILED open_container: no non-empty container found nearby"]
        with self._lock:
            recent_chat = [m for m in self.chat_history if not m.startswith(f"{self.name}:")]
            instruction = recent_chat[-1] if recent_chat else ""
        print(f"  [{self.name}] Entering container session at ({x}, {y}, {z})")
        session = sessions.ContainerSession(self.name, self.model, x, y, z, instruction=instruction)
        try:
            results = session.run()
        except Exception as e:
            results = [f"ERROR container session: {e}"]
            print(f"  [{self.name}] Container session error: {e}")
        print(f"  [{self.name}] Container session ended: {len(results)} result(s)")
        return results

    def _run_craft_session(self, params):
        goal = params.get("goal", "")
        print(f"  [{self.name}] Entering craft session: {goal}")
        session = sessions.CraftSession(self.name, self.model, goal)
        try:
            results = session.run()
        except Exception as e:
            results = [f"ERROR craft session: {e}"]
            print(f"  [{self.name}] Craft session error: {e}")
        print(f"  [{self.name}] Craft session ended: {len(results)} result(s)")
        return results

    def _goto_player(self, p):
        target = p.get("target", "")
        if not target:
            return {"error": "goto_player requires a target param (player name)"}
        ents = api.entities(self.name, 64.0)
        for ent in ents.get("entities", []):
            if ent.get("name", "").lower() == target.lower():
                pos = ent.get("position", {})
                x, y, z = pos.get("x", 0), pos.get("y", 0), pos.get("z", 0)
                print(f"  [{self.name}] goto_player: found {target} at ({x}, {y}, {z})")
                return api.goto(self.name, x, y, z, p.get("distance", 2.0), p.get("sprint", True))
        return api.follow(self.name, target, p.get("distance", 3.0), 64.0)

    def _learn_from_error(self, action, params, error):
        """Store action errors in semantic memory so the bot doesn't repeat mistakes."""
        if not self.semantic_mem:
            return
        try:
            lesson = f"Action '{action}' with params {params} failed: {error}"
            self.semantic_mem.store(lesson, category="knowledge",
                                   metadata={"type": "error", "action": action})
            print(f"  [{self.name}/sem] learned from error")
        except Exception:
            pass

    def _execute_one(self, name, p):
        bot = self.name
        match name:
            case "goto" if "target" in p:
                return self._goto_player(p)
            case "goto":
                return api.goto(bot, p["x"], p["y"], p["z"], p.get("distance", 2.0), p.get("sprint", True))
            case "goto_player":
                return self._goto_player(p)
            case "fly_to":
                return api.fly_to(bot, p["x"], p["y"], p["z"], p.get("distance", 2.0), p.get("speed", 0.5))
            case "look":
                return api.look(bot, p["x"], p["y"], p["z"])
            case "teleport":
                return api.teleport(bot, p["x"], p["y"], p["z"], p.get("dimension"))
            case "follow":
                return api.follow(bot, p["target"], p.get("distance", 3.0), p.get("radius", 32.0))
            case "attack":
                return api.attack(bot, p["target"], p.get("radius", 16.0))
            case "combat_mode":
                return api.combat_mode(bot, p.get("radius", 24.0), p.get("hostile_only", True), p.get("target"))
            case "mine":
                return api.mine(bot, p["x"], p["y"], p["z"])
            case "place":
                return api.place(bot, p["x"], p["y"], p["z"])
            case "craft":
                return api.craft(bot, p["item"], p.get("count", 1))
            case "equip":
                return api.equip(bot, p["slot"])
            case "use":
                return api.use_item(bot)
            case "drop":
                return api.drop(bot, p["slot"], p.get("count", 64))
            case "collect":
                return api.collect(bot, p.get("radius", 16.0))
            case "swap":
                return api.swap(bot, p["from"], p["to"])
            case "find_blocks":
                return api.find_blocks(bot, p["block"], p.get("radius", 32), p.get("max", 10))
            case "find_entities":
                return api.find_entities(bot, p["target"], p.get("radius", 32.0))
            case "wide_search":
                target = p.get("target", "")
                if not target:
                    return {"error": "wide_search requires a target"}
                pos = api.status(bot).get("position", {})
                sx = p.get("x", pos.get("x", 0))
                sy = p.get("y", pos.get("y", 64))
                sz = p.get("z", pos.get("z", 0))
                extra = {
                    "search_type": p.get("search_type", "block"),
                    "bot_index": str(p.get("bot_index", 0)),
                    "bot_count": str(p.get("bot_count", 1)),
                    "radius": str(p.get("radius", 512)),
                }
                return api.set_directive(bot, "WIDE_SEARCH", target=target, x=sx, y=sy, z=sz, extra=extra)
            case "container":
                return api.container(bot, p["x"], p["y"], p["z"])
            case "container_insert":
                return api.container_insert(bot, p["x"], p["y"], p["z"], p["slot"], p.get("count", 64))
            case "container_extract":
                return api.container_extract(bot, p["x"], p["y"], p["z"], slot=p.get("slot"), item=p.get("item"), count=p.get("count", 64))
            case "list_recipes":
                return api.list_recipes(bot, p.get("filter", ""), p.get("craftable_only", False))
            case "craft_chain":
                return api.craft_chain(bot, p["item"], p.get("count", 1))
            case "chat":
                msg = p["message"]
                with self._lock:
                    self.chat_history.append(f"{bot}: {msg}")
                    if len(self.chat_history) > MAX_CHAT_HISTORY:
                        self.chat_history.pop(0)
                return api.chat(bot, msg)
            case "stop":
                return api.stop(bot)
            case "bot_message":
                to_bot = p.get("target", "")
                msg = p.get("message", "")
                if not to_bot or not msg:
                    return {"error": "bot_message requires target and message"}
                ok = BotRunner.send_bot_message(self.name, to_bot, msg)
                return {"status": "sent"} if ok else {"error": f"Bot '{to_bot}' not found"}
            case "delegate":
                desc = p.get("task", "")
                spec = p.get("specialization", "any")
                target_bot = p.get("target")
                if not desc:
                    return {"error": "delegate requires a task description"}
                if not _task_board:
                    return {"error": "Task board not available"}
                # Prevent re-delegation loops: if bot is working on a task board task, don't delegate
                if self._current_task_id:
                    return {"error": "You are working on a delegated task — complete it yourself, do not re-delegate"}
                steps = None
                if target_bot and target_bot in _all_runners:
                    spec = None
                task_id = _task_board.post(
                    description=desc,
                    created_by=self.name,
                    specialization=spec if not target_bot else None,
                    priority=1,
                )
                if target_bot and target_bot in _all_runners:
                    BotRunner.send_bot_message(
                        self.name, target_bot,
                        f"I've posted task #{task_id} for you: {desc}"
                    )
                print(f"[{self.name}/delegate] Posted task #{task_id}: {desc[:60]} (spec={spec}, target={target_bot})")
                return {"status": "delegated", "task_id": task_id}
            case "anvil":
                return api.anvil(bot, p["input_slot"], p.get("material_slot", -1), p.get("name"))
            case "smithing":
                return api.smithing(bot, p["template_slot"], p["base_slot"], p["addition_slot"])
            case "brew":
                return api.brew(bot, p["ingredient_slot"], p["bottle_slots"], p.get("fuel_slot", -1))
            case "enchant":
                return api.enchant(bot, p["item_slot"], p["lapis_slot"], p.get("option", 2))
            case "xp_status":
                return api.xp_status(bot)
            case "meditate":
                return api.meditate(bot, p.get("levels", 10))
            case "conjure":
                return api.conjure(bot, p["item"], p.get("count", 1))
            case "repair":
                return api.repair(bot, p["slot"])
            case "smelt":
                return api.smelt(bot, p["input_slot"], p["fuel_slot"], p.get("count", 1))
            case "trade":
                return api.trade(bot, p.get("trade_index", -1), p.get("times", 1))
            case "shop_list":
                return api.shop_list(bot)
            case "shop_buy":
                return api.shop_buy(bot, p["item"], p.get("count", 1))
            case "send_item":
                return api.send_item(bot, p["slot"], p["target"], p.get("count", 64))
            case "set_waypoint":
                wp_name = p["name"]
                # Get bot's current position from status
                st = api.status(bot)
                pos = st.get("position", {})
                dim = st.get("dimension")
                waypoints.set_waypoint(wp_name, pos.get("x", 0), pos.get("y", 0), pos.get("z", 0), dim, bot)
                return {"status": "waypoint_set", "name": wp_name}
            case "delete_waypoint":
                ok = waypoints.delete_waypoint(p["name"])
                return {"status": "deleted" if ok else "not_found"}
            case "list_waypoints":
                return {"waypoints": waypoints.list_waypoints()}
            case "goto_waypoint":
                wp = waypoints.get_waypoint(p["name"])
                if not wp:
                    return {"error": f"Waypoint '{p['name']}' not found. Use list_waypoints to see available waypoints."}
                if wp.get("dimension"):
                    api.teleport(bot, wp["x"], wp["y"], wp["z"], wp["dimension"])
                else:
                    api.goto(bot, wp["x"], wp["y"], wp["z"], p.get("distance", 2.0), p.get("sprint", True))
                return {"status": "navigating", "waypoint": wp["name"], "target": {"x": wp["x"], "y": wp["y"], "z": wp["z"]}}
            case _:
                return {"error": f"Unknown action: {name}"}


def _parse_memory_category(text):
    """Extract category from '[category] content' format."""
    text = text.strip()
    if text.startswith("["):
        end = text.find("]")
        if end > 0:
            cat = text[1:end].lower().strip()
            if cat in ("location", "instruction", "knowledge", "event"):
                return cat
    return "knowledge"


def _strip_category_prefix(text):
    """Remove '[category] ' prefix if present."""
    text = text.strip()
    if text.startswith("["):
        end = text.find("]")
        if end > 0:
            return text[end + 1:].strip()
    return text


def load_profiles():
    """Load all profile JSON files from the profiles directory."""
    profiles_dir = os.path.join(os.path.dirname(__file__), "profiles")
    profiles = []
    for fname in sorted(os.listdir(profiles_dir)):
        if fname.endswith(".json"):
            with open(os.path.join(profiles_dir, fname)) as f:
                profiles.append(json.load(f))
    return profiles


def _build_transmute_tags():
    """Build a reverse index: normalized alias -> registry_id.
    Sources: mod display names (ground truth) + generated aliases from registry IDs."""
    tags = {}
    if not _transmute:
        return tags
    all_items = _transmute.get_all()

    # Source 1: display names from the mod API
    try:
        resp = api.transmute_names()
        names = resp.get("names", {})
        for reg_id, display_name in names.items():
            dn = display_name.lower().strip()
            tags[dn] = reg_id
            tags[dn.replace(" ", "_")] = reg_id
            tags[dn.rstrip("s")] = reg_id
            tags[dn.replace(" ", "_").rstrip("s")] = reg_id
    except Exception as e:
        print(f"[agent] Could not fetch display names from mod: {e}")

    # Source 2: auto-generated aliases from registry IDs
    for reg_id in all_items:
        bare = reg_id.split(":", 1)[-1] if ":" in reg_id else reg_id
        human = bare.replace("_", " ")
        for alias in (bare, human, bare.rstrip("s"), human.rstrip("s")):
            a = alias.lower()
            if a not in tags:
                tags[a] = reg_id
    return tags


def run():
    print(f"[agent] Checking ollama at {OLLAMA_URL}...")
    ok, models = brain.check_ollama(OLLAMA_URL)
    if ok:
        print(f"[agent] Ollama models: {', '.join(models)}")
    else:
        print(f"[error] Cannot reach ollama: {models}")

    print(f"[agent] Connecting to mod API...")
    max_retries = 60
    for attempt in range(1, max_retries + 1):
        try:
            h = api.health()
            print(f"[agent] Mod API: {h}")
            break
        except Exception as e:
            if attempt == max_retries:
                print(f"[error] Cannot reach mod API after {max_retries} attempts: {e}")
                sys.exit(1)
            print(f"[agent] Mod API not ready (attempt {attempt}/{max_retries}), retrying in 5s...")
            time.sleep(5)

    # Despawn any stale bots from a previous agent run
    try:
        existing = api.list_bots().get("bots", [])
        if existing:
            print(f"[agent] Cleaning up {len(existing)} stale bot(s): {existing}")
            for name in existing:
                api.despawn(name)
    except Exception:
        pass

    # Initialize shared task board
    global _task_board, _all_runners
    try:
        _task_board = taskboard.TaskBoard(PG_DSN)
        _task_board.connect()
        _task_board.clear_all()
        print(f"[agent] Task board: connected (cleared on restart)")
    except Exception as e:
        print(f"[agent] Task board unavailable: {e}")
        _task_board = None

    # Initialize transmute registry
    global _transmute, _transmute_tags
    try:
        _transmute = transmute_db.TransmuteDB(PG_DSN)
        _transmute.connect()
        synced = _transmute.sync_from_mod()
        print(f"[agent] Transmute registry: {len(_transmute.get_all())} items ({synced} new from mod)")
        _transmute_tags = _build_transmute_tags()
        print(f"[agent] Transmute tag index: {len(_transmute_tags)} aliases")
    except Exception as e:
        print(f"[agent] Transmute DB unavailable: {e}")
        _transmute = None

    # Initialize container registry
    global _container_db
    try:
        _container_db = container_db.ContainerDB(PG_DSN)
        _container_db.connect()
        _container_db.sync_to_mod()
        containers = _container_db.get_all()
        print(f"[agent] Container registry: {len(containers)} containers loaded")
    except Exception as e:
        print(f"[agent] Container DB unavailable: {e}")
        _container_db = None

    # Initialize L4 (OpenAI) escalation layer
    try:
        openai_brain.init()
        if openai_brain.is_available():
            print(f"[agent] L4 (OpenAI) available: model={os.getenv('OPENAI_MODEL', 'gpt-4o-mini')}")
        else:
            print("[agent] L4 (OpenAI) disabled or no API key")
    except Exception as e:
        print(f"[agent] L4 (OpenAI) init failed: {e}")

    waypoints.load()
    wp_count = len(waypoints.list_waypoints())
    if wp_count:
        print(f"[agent] Waypoints: {wp_count} loaded for this server")

    global _terrain
    try:
        _terrain = terrain_db.TerrainDB(PG_DSN)
        _terrain.connect()
        stats = _terrain.stats()
        total = sum(stats.values())
        print(f"[agent] Terrain DB: {total} blocks mapped ({', '.join(f'{k}: {v}' for k, v in stats.items()) or 'empty'})")
    except Exception as e:
        print(f"[agent] Terrain DB unavailable: {e}")
        _terrain = None

    if DASHBOARD_ENABLED:
        start_dashboard(
            DASHBOARD_PORT, api, sys.modules[__name__],
            _task_board, _transmute, _container_db, waypoints, _terrain,
        )

    profiles = load_profiles()
    print(f"[agent] Found {len(profiles)} bot profile(s): {[p['name'] for p in profiles]}")

    runners = []
    SPAWN_STAGGER_DELAY = 5.0
    for i, profile in enumerate(profiles):
        runner = BotRunner(profile)
        _all_runners[runner.name] = runner
        runner.start()
        runners.append(runner)
        if i < len(profiles) - 1:
            print(f"[agent] Staggering next bot spawn ({SPAWN_STAGGER_DELAY}s)...")
            time.sleep(SPAWN_STAGGER_DELAY)

    print(f"[agent] All {len(runners)} bots started (tick={TICK_DELAY}s)")
    print("=" * 50)

    transmute_sync_counter = 0
    try:
        while True:
            time.sleep(1)
            transmute_sync_counter += 1
            if _transmute and transmute_sync_counter >= 60:
                transmute_sync_counter = 0
                _transmute.sync_from_mod()
    except KeyboardInterrupt:
        print("\n[agent] Shutting down all bots...")
        for runner in runners:
            runner.stop()
        if _task_board:
            _task_board.close()


if __name__ == "__main__":
    run()
