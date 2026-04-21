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
import waypoints
from config import (
    TICK_DELAY, BUSY_POLL_DELAY,
    OBSERVE_ENTITY_RADIUS, OBSERVE_BLOCK_RADIUS,
    MAX_CHAT_HISTORY, MAX_CONVERSATION, OLLAMA_URL, PG_DSN,
)

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
_all_runners = {}  # name -> BotRunner
_orchestration_lock = threading.Lock()
_orchestrated_messages = {}  # message_text -> coordinator bot name

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
        self._awaiting_taskboard = False
        self._current_task_id = None
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

            # If a bot sent us a task board notification, extract the actual task
            if from_bot and "Task #" in text and "for you:" in text:
                text = text.split("for you:", 1)[1].strip()

            # Short-circuit: navigation and control commands → skip planner entirely
            _follow_phrases = ["follow me", "follow us", "keep following"]
            _goto_phrases = ["come to me", "come here", "get over here", "come over here",
                             "get to me", "walk to me", "run to me", "tp to me"]
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
                if self._plan_steps and self._plan_step_idx < len(self._plan_steps):
                    self._store_plan_outcome(success=False, failure_reason=f"Interrupted: {text[:60]}")
                self._plan_steps = []
                self._plan_step_idx = 0
                self._plan_instruction = ""
                self._awaiting_taskboard = False
                api.stop(self.name)
                self._consume_message(msg)
                if is_follow:
                    api.follow(self.name, sender, 3.0, 64.0)
                    api.chat(self.name, f"Following you, {sender}!")
                    print(f"[{self.name}/nav] Direct follow {sender} (shortcut)")
                elif is_goto:
                    self._goto_player({"target": sender})
                    api.chat(self.name, f"On my way!")
                    print(f"[{self.name}/nav] Direct goto_player {sender} (shortcut)")
                else:
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

            if self._plan_steps and self._plan_step_idx < len(self._plan_steps):
                self._store_plan_outcome(
                    success=False,
                    failure_reason=f"Interrupted by new instruction: \"{text[:60]}\""
                )

            # Bot-to-bot messages: NEVER orchestrate (prevents delegation loops).
            # Only use orchestrator for real player instructions when multiple bots available.
            if not from_bot and len(_all_runners) > 1 and _task_board:
                # Only ONE bot orchestrates per player message — the rest wait for task board
                msg_key = text.strip().lower()[:100]
                with _orchestration_lock:
                    coordinator = _orchestrated_messages.get(msg_key)
                    if coordinator is None:
                        _orchestrated_messages[msg_key] = self.name
                        is_coordinator = True
                        # Prune old entries to prevent unbounded growth
                        if len(_orchestrated_messages) > 50:
                            oldest = list(_orchestrated_messages.keys())[:25]
                            for k in oldest:
                                _orchestrated_messages.pop(k, None)
                    else:
                        is_coordinator = False

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
                profiles = [r.profile for r in _all_runners.values()]
                orch_steps = planner.orchestrate(self.model, text, profiles, memory_context)

                my_steps = []
                delegated = []
                for s in orch_steps:
                    assigned = s.get("assign", "any")
                    step_desc = s["step"]
                    spec = s.get("specialization", "any")

                    if assigned == self.name or assigned == "any" or assigned not in _all_runners:
                        my_steps.append(step_desc)
                    else:
                        task_id = _task_board.post(
                            description=step_desc,
                            created_by=self.name,
                            specialization=spec,
                        )
                        BotRunner.send_bot_message(
                            self.name, assigned,
                            f"Task #{task_id} for you: {step_desc}"
                        )
                        delegated.append((assigned, step_desc))
                        print(f"[{self.name}/orchestrator] Delegated to {assigned}: {step_desc[:60]}")

                # Broadcast orchestration summary to chat
                for assigned, desc in delegated:
                    api.system_chat(self.name, f"{assigned} -> {desc[:50]}", "aqua")
                if my_steps:
                    self._plan_steps = my_steps
                    self._plan_step_idx = 0
                    self._plan_instruction = text
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
                steps = planner.decompose(self.model, text, memory_context)
                self._plan_steps = steps
                self._plan_step_idx = 0
                self._plan_instruction = text
                self.conversation_history.clear()
                step_list = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(steps))
                print(f"[{self.name}/planner] Plan ({len(steps)} steps):\n{step_list}")
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
        if self._plan_steps or not _task_board:
            return
        try:
            task = _task_board.claim(self.name, self.specializations + ["any"])
            if task:
                self._current_task_id = task["id"]
                self._awaiting_taskboard = False
                desc = task["description"]
                _task_board.start(task["id"])
                print(f"[{self.name}/taskboard] Claimed task #{task['id']}: {desc[:60]}")
                try:
                    api.system_chat(self.name, f"Claimed task: {desc[:50]}", "yellow")
                except Exception:
                    pass

                if task.get("plan_steps"):
                    self._plan_steps = task["plan_steps"]
                    self._plan_step_idx = 0
                    self._plan_instruction = desc
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
                    steps = planner.decompose(self.model, desc, memory_context)
                    self._plan_steps = steps
                    self._plan_step_idx = 0
                    self._plan_instruction = desc
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
        r"(?:minecraft:)?(\S+?)(?:\s+(?:\(.*?(\d+).*?\)|x\s*(\d+)|at\s+least\s+(\d+)))?(?:\s+\(.*\))?$",
        re.IGNORECASE,
    )
    _CRAFT_PATTERNS = re.compile(
        r"craft\s+(?:(?:and\s+\w+\s+)?)?(?:minecraft:)?(\S+?)(?:\s+x\s*(\d+))?$",
        re.IGNORECASE,
    )
    _SMELT_PATTERNS = re.compile(
        r"smelt\s+(?:minecraft:)?(\S+?)(?:\s+(?:into|to)\s+.+)?(?:\s+x\s*(\d+))?$",
        re.IGNORECASE,
    )
    _GOTO_PATTERNS = re.compile(
        r"(?:go\s+to|goto|travel\s+to|walk\s+to|navigate\s+to)\s+(.+)",
        re.IGNORECASE,
    )
    _ENCHANT_PATTERNS = re.compile(
        r"enchant\s+(?:(?:the|my|a)\s+)?(?:minecraft:)?(\S+?)(?:\s+(?:with|using|at|option)\s+.*)?$",
        re.IGNORECASE,
    )
    _BREW_PATTERNS = re.compile(
        r"(?:brew|make|create)\s+(?:(?:a\s+|some\s+)?(?:potion\s+of\s+|potions?\s+of\s+)?)?"
        r"(?:minecraft:)?(\S+?)(?:\s+(?:potion|potions))?(?:\s+x\s*(\d+))?$",
        re.IGNORECASE,
    )

    DIRECTIVE_POLL_INTERVAL = 10.0

    def _classify_step(self, step_text):
        """Try to map a plan step to an L1 directive dict. Returns None if LLM path needed."""
        text = step_text.strip()

        # Mine
        m = self._MINE_PATTERNS.search(text)
        if m:
            target = m.group(1).rstrip(",.")
            count = None
            for g in (m.group(2), m.group(3), m.group(4)):
                if g:
                    count = int(g)
                    break
            return {"type": "MINE", "target": target, "count": count or 10, "radius": 32}

        # Craft (including "craft and place")
        m = self._CRAFT_PATTERNS.search(text)
        if m:
            target = m.group(1).rstrip(",.")
            if not target.startswith("minecraft:"):
                target = "minecraft:" + target
            count = int(m.group(2)) if m.group(2) else 1
            return {"type": "CRAFT", "target": target, "count": count}

        # Smelt
        m = self._SMELT_PATTERNS.search(text)
        if m:
            target = m.group(1).rstrip(",.")
            if not target.startswith("minecraft:"):
                target = "minecraft:" + target
            count = int(m.group(2)) if m.group(2) else 1
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

    def _run_directive(self, directive_params):
        """Send a directive to the L1 brain and poll until completion or failure."""
        dtype = directive_params.pop("type")
        try:
            resp = api.set_directive(self.name, dtype, **directive_params)
            print(f"[{self.name}/L1] Directive sent: {dtype} {directive_params} -> {resp.get('status')}")
            api.system_chat(self.name, f"L1: {dtype} {directive_params.get('target', '')}", "dark_aqua")
        except Exception as e:
            print(f"[{self.name}/L1] Failed to send directive: {e}")
            return {"success": False, "reason": str(e)}

        while not self._stop_event.is_set():
            # Check for new chat — player commands override directive
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
                self._stop_event.wait(self.DIRECTIVE_POLL_INTERVAL)
                continue

            directive_info = brain_state.get("directive")
            if not directive_info:
                return {"success": True}

            status = directive_info.get("status", "")
            if status == "COMPLETED":
                progress = brain_state.get("progress", {})
                print(f"[{self.name}/L1] Directive COMPLETED: {progress.get('counters', {})}")
                return {"success": True, "progress": progress}
            elif status in ("FAILED", "CANCELLED"):
                reason = directive_info.get("failure_reason", status.lower())
                print(f"[{self.name}/L1] Directive {status}: {reason}")
                return {"success": False, "reason": reason}

            # Still running — log phase and wait
            progress = brain_state.get("progress", {})
            phase = progress.get("phase", "unknown")
            counters = progress.get("counters", {})
            state_desc = brain_state.get("state", "")
            print(f"[{self.name}/L1] {state_desc} (phase={phase}, counters={counters})")

            self._stop_event.wait(self.DIRECTIVE_POLL_INTERVAL)

        return {"success": False, "reason": "agent_stopped"}

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                self._wait_for_idle_or_chat(timeout=10)
                obs, new_msgs = self._observe()

                new_msgs = self._handle_chat_commands(new_msgs)
                self._maybe_plan(new_msgs)

                if not self._plan_steps:
                    self._check_task_board()

                if self._awaiting_taskboard and not self._plan_steps:
                    self._stop_event.wait(TICK_DELAY)
                    continue

                # ── L1 directive path: try to classify current step ──
                if self._plan_steps and self._plan_step_idx < len(self._plan_steps):
                    current_step = self._plan_steps[self._plan_step_idx]
                    directive = self._classify_step(current_step)
                    if directive is not None:
                        print(f"[{self.name}/L1] Step \"{current_step}\" -> directive {directive['type']}")
                        api.system_chat(self.name, f"L1 step: {current_step[:50]}", "dark_aqua")
                        result = self._run_directive(directive)

                        if result.get("reason") == "interrupted_by_chat":
                            continue

                        if result["success"]:
                            old_step = self._plan_steps[self._plan_step_idx]
                            self._plan_step_idx += 1
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
                            else:
                                new_step = self._plan_steps[self._plan_step_idx]
                                print(f"[{self.name}/planner] L1 step done: \"{old_step}\" -> now: \"{new_step}\" ({self._plan_step_idx+1}/{len(self._plan_steps)})")
                                api.system_chat(self.name, f"Step {self._plan_step_idx}/{len(self._plan_steps)}: {new_step[:50]}", "dark_aqua")
                                self.conversation_history.clear()
                        else:
                            reason = result.get("reason", "unknown")
                            print(f"[{self.name}/L1] Directive failed: {reason} — falling back to LLM for this step")
                            api.system_chat(self.name, f"L1 failed: {reason[:40]}, using LLM", "yellow")
                            # Fall through to LLM path below for this tick
                        continue

                # ── L2/L3 LLM path: steps that can't be classified as directives ──
                plan_section = self._plan_context()
                if plan_section:
                    obs = plan_section + "\n\n" + obs

                sem_context = ""
                if self.semantic_mem:
                    try:
                        sem_context = self.semantic_mem.recall_all_for_prompt(obs[:500], limit=6)
                    except Exception as e:
                        print(f"[{self.name}/sem] recall error: {e}")

                prompt = prompts.build_system_prompt(self.profile, self.memory_entries, sem_context)
                response = brain.think(self.model, prompt, obs, self.conversation_history)

                thoughts = response.get("thoughts", "")
                actions = response.get("actions", [])
                chat_msg = response.get("chat")
                remember = response.get("remember")

                # Hard guardrail: no movement actions when idle (no plan)
                if not self._plan_steps and actions:
                    _move_actions = {"goto", "goto_player", "follow", "fly_to", "teleport"}
                    blocked = [a for a in actions if isinstance(a, dict) and a.get("action") in _move_actions]
                    if blocked:
                        actions = [a for a in actions if not (isinstance(a, dict) and a.get("action") in _move_actions)]
                        print(f"[{self.name}/guardrail] Blocked {len(blocked)} movement action(s) — no active plan")

                print(f"\n[{self.name}/think] {thoughts}")

                if chat_msg:
                    with self._lock:
                        self.chat_history.append(f"{self.name}: {chat_msg}")
                        if len(self.chat_history) > MAX_CHAT_HISTORY:
                            self.chat_history.pop(0)
                    api.chat(self.name, chat_msg)
                    print(f"[{self.name}/chat] {chat_msg}")

                if remember:
                    self.memory_entries = mem_module.add_to(
                        self.memory_entries, remember, self._memory_file
                    )
                    if self.semantic_mem:
                        try:
                            category = _parse_memory_category(remember)
                            clean = _strip_category_prefix(remember)
                            mid = self.semantic_mem.store(clean, category=category)
                            print(f"[{self.name}/sem] stored [{category}] id={mid}")
                            self._share_discovery(clean, category)
                        except Exception as e:
                            print(f"[{self.name}/sem] store error: {e}")

                    print(f"[{self.name}/memory] {remember}")

                self.conversation_history.append({"role": "user", "content": obs})
                self.conversation_history.append({"role": "assistant", "content": json.dumps(response)})
                while len(self.conversation_history) > MAX_CONVERSATION * 2:
                    self.conversation_history.pop(0)
                    self.conversation_history.pop(0)

                if actions:
                    self._execute_actions(actions)

                with self._lock:
                    tick_results = list(self._last_action_results)
                self._advance_plan(response, tick_results)

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

        with self._lock:
            chat_snapshot = list(self.chat_history)
            new_messages = list(self._new_messages[-5:])
            self._new_messages.clear()
            action_results = list(self._last_action_results)
            self._last_action_results = []

        obs = prompts.build_observation(
            status, inv, ents, blks, action_state, chat_snapshot, new_messages, action_results
        )
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


def run():
    print(f"[agent] Checking ollama at {OLLAMA_URL}...")
    ok, models = brain.check_ollama(OLLAMA_URL)
    if ok:
        print(f"[agent] Ollama models: {', '.join(models)}")
    else:
        print(f"[error] Cannot reach ollama: {models}")

    print(f"[agent] Connecting to mod API...")
    try:
        h = api.health()
        print(f"[agent] Mod API: {h}")
    except Exception as e:
        print(f"[error] Cannot reach mod API: {e}")
        sys.exit(1)

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
        stale = _task_board.cleanup_stale()
        if stale:
            print(f"[agent] Cleaned up {stale} stale task(s)")
        print(f"[agent] Task board: connected ({_task_board.pending_count()} pending tasks)")
    except Exception as e:
        print(f"[agent] Task board unavailable: {e}")
        _task_board = None

    waypoints.load()
    wp_count = len(waypoints.list_waypoints())
    if wp_count:
        print(f"[agent] Waypoints: {wp_count} loaded for this server")

    profiles = load_profiles()
    print(f"[agent] Found {len(profiles)} bot profile(s): {[p['name'] for p in profiles]}")

    runners = []
    for profile in profiles:
        runner = BotRunner(profile)
        _all_runners[runner.name] = runner
        runner.start()
        runners.append(runner)

    print(f"[agent] All bots started (tick={TICK_DELAY}s)")
    print("=" * 50)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[agent] Shutting down all bots...")
        for runner in runners:
            runner.stop()
        if _task_board:
            _task_board.close()


if __name__ == "__main__":
    run()
