package com.sigmastrain.aiplayermod.brain;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.behavior.*;

import java.util.LinkedHashMap;
import java.util.Map;

public class BotBrain {
    private final BotPlayer bot;
    private final SelfPreservation selfPreservation = new SelfPreservation();

    private volatile Directive pendingDirective;
    private Directive activeDirective;
    private Directive lastDirective; // Retains completed/failed directive for agent polling
    // ...and its progress. A finishing behavior is swapped out for idle in the
    // same tick it returns SUCCESS, so by the time the agent polls (~1s later)
    // toMap() was reporting the IDLE behavior's empty report. Every directive's
    // final counters were being dropped on the floor; LOCATE's coordinates
    // would have been too.
    private ProgressReport lastProgress;
    private Behavior activeBehavior;

    private final IdleBehavior idleBehavior = new IdleBehavior();

    public BotBrain(BotPlayer bot) {
        this.bot = bot;
        this.activeBehavior = idleBehavior;
    }

    public void setDirective(Directive directive) {
        this.pendingDirective = directive;
    }

    public void cancelDirective() {
        cancelDirective(-1);
    }

    /**
     * Cancel only if the active directive matches the given id (-1 = any).
     * Guards against the D3 race: a poller's post-completion cleanup cancel
     * arriving after the NEXT directive has already been set killed fresh
     * work mid-flight.
     */
    public void cancelDirective(long expectedId) {
        if (expectedId > 0 && activeDirective != null && activeDirective.getId() != expectedId) {
            AIPlayerMod.LOGGER.info("[{}] cancelDirective({}) ignored — active id is {}",
                    bot.getPlayer().getName().getString(), expectedId, activeDirective.getId());
            return;
        }
        AIPlayerMod.LOGGER.warn("[{}] cancelDirective called — active={}, caller={}",
                bot.getPlayer().getName().getString(),
                activeDirective != null ? activeDirective.getType() : "none",
                Thread.currentThread().getStackTrace()[2]);
        if (activeDirective != null && activeDirective.getStatus() == DirectiveStatus.ACTIVE) {
            activeDirective.cancel();
        }
        if (activeBehavior != null) {
            activeBehavior.stop();
        }
        activeDirective = null;
        lastDirective = null;
        lastProgress = null;
        activeBehavior = idleBehavior;
    }

    public boolean hasActiveDirective() {
        return activeDirective != null && activeDirective.getStatus() == DirectiveStatus.ACTIVE;
    }

    public void tick() {
        Directive incoming = pendingDirective;
        if (incoming != null) {
            pendingDirective = null;
            applyDirective(incoming);
        }

        if (selfPreservation.tick(bot)) {
            return;
        }

        if (activeBehavior == null) return;

        BehaviorResult result = activeBehavior.tick(bot);
        switch (result) {
            case SUCCESS -> {
                if (activeDirective != null) {
                    activeDirective.complete();
                    AIPlayerMod.LOGGER.info("[{}] Directive {} completed",
                            bot.getPlayer().getName().getString(), activeDirective.getType());
                    bot.systemChat("Directive complete: " + activeDirective.getType(), "green");
                    lastDirective = activeDirective;
                    lastProgress = activeBehavior.getProgress();
                }
                activeBehavior = idleBehavior;
                activeDirective = null;
            }
            case FAILED -> {
                String reason = activeBehavior.getProgress().toMap().getOrDefault("failure_reason", "unknown").toString();
                if (activeDirective != null) {
                    activeDirective.fail(reason);
                    AIPlayerMod.LOGGER.warn("[{}] Directive {} failed: {}",
                            bot.getPlayer().getName().getString(), activeDirective.getType(), reason);
                    bot.systemChat("Directive failed: " + reason, "red");
                    lastDirective = activeDirective;
                    lastProgress = activeBehavior.getProgress();
                }
                activeBehavior = idleBehavior;
                activeDirective = null;
            }
            case CANCELLED -> {
                if (activeDirective != null) {
                    activeDirective.cancel();
                    AIPlayerMod.LOGGER.info("[{}] Directive {} cancelled",
                            bot.getPlayer().getName().getString(), activeDirective.getType());
                    bot.systemChat("Directive cancelled: " + activeDirective.getType(), "yellow");
                    lastDirective = activeDirective;
                    lastProgress = activeBehavior.getProgress();
                }
                activeBehavior = idleBehavior;
                activeDirective = null;
            }
            case RUNNING -> {}
        }
    }

    /**
     * Operator-initiated cancel (from the overlay's unit status window): end the
     * active directive as CANCELLED — a distinct terminal outcome, RETAINED as
     * the last directive so the UI and the agent poller both see that it was
     * cancelled — and reset the bot to idle. Returns the cancelled type, or null
     * if there was nothing active to cancel.
     */
    public String cancelActiveDirective() {
        if (activeDirective == null || activeDirective.getStatus() != DirectiveStatus.ACTIVE) {
            // Nothing active; also clear any lingering pending directive.
            pendingDirective = null;
            return null;
        }
        String type = activeDirective.getType().name();
        activeDirective.cancel();
        if (activeBehavior != null) {
            lastProgress = activeBehavior.getProgress();
            activeBehavior.stop();
        }
        // Reset bot state: drop any vehicle the cancelled directive was driving.
        try { VehicleRide.release(bot.getPlayer()); } catch (Throwable ignored) {}
        lastDirective = activeDirective;
        pendingDirective = null;
        AIPlayerMod.LOGGER.info("[{}] Directive {} cancelled by operator",
                bot.getPlayer().getName().getString(), type);
        bot.systemChat("Directive cancelled: " + type, "yellow");
        activeDirective = null;
        activeBehavior = idleBehavior;
        return type;
    }

    // Package-private so a unit test can drive it without a live ServerPlayer.
    // tick()'s later stages (self-preservation, chat) dereference the entity, so
    // the failure path cannot be reached through tick() in a server-free test;
    // this is the one seam, and it is the method under test.
    void applyDirective(Directive directive) {
        if (activeBehavior != null && activeBehavior != idleBehavior) {
            activeBehavior.stop();
        }
        if (activeDirective != null && activeDirective.getStatus() == DirectiveStatus.ACTIVE) {
            activeDirective.cancel();
        }

        activeDirective = directive;
        lastProgress = null;
        Behavior created = BehaviorFactory.create(directive.getType());
        try {
            created.start(bot, directive);
        } catch (RuntimeException e) {
            // Install only a behavior whose start() succeeded. Assigning before
            // start() left a half-started behavior in place: MineBehavior with a
            // null target threw in start() before enterPhase(), so phase stayed
            // unset and every server tick re-threw in tick() -- 312 stack traces
            // in 16s, the server thread fell behind, and the bot stopped
            // answering. Fail the directive once and go idle instead.
            try {
                created.stop();
            } catch (RuntimeException ignored) {
                // A behavior whose start() failed may not have initialised what
                // stop() needs; that must not stop the bot recovering.
            }
            directive.fail("start() threw: " + e);
            activeDirective = null;
            // Retained as the last directive so the agent's next poll sees why
            // it failed, rather than a bot that looks idle with no record.
            lastDirective = directive;
            activeBehavior = idleBehavior;
            // Recovery must not depend on the entity: systemChat() dereferences
            // the player, so calling it here made the catch that exists to stop
            // a wedge throw an NPE of its own.
            AIPlayerMod.LOGGER.warn("Directive {} failed at start(), fell back to idle: {}",
                    directive.getType(), e.toString());
            if (bot != null) {
                bot.systemChat("Directive failed: " + directive.getType(), "red");
            }
            return;
        }
        activeBehavior = created;

        AIPlayerMod.LOGGER.info("[{}] New directive: {} target={}",
                bot.getPlayer().getName().getString(), directive.getType(), directive.getTarget());
        bot.systemChat("Directive: " + directive.getType()
                + (directive.getTarget() != null ? " → " + directive.getTarget() : ""), "dark_aqua");
    }

    public Map<String, Object> toMap() {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("state", activeBehavior != null ? activeBehavior.describeState() : "idle");
        map.put("self_preservation", selfPreservation.isFleeing() ? "fleeing" : "ok");
        if (activeDirective != null) {
            map.put("directive", activeDirective.toMap());
            if (activeBehavior != null) {
                map.put("progress", activeBehavior.getProgress().toMap());
            }
        } else if (lastDirective != null) {
            map.put("directive", lastDirective.toMap());
            // Report the progress that BELONGS to that directive, not idle's.
            map.put("progress", (lastProgress != null ? lastProgress : activeBehavior.getProgress()).toMap());
        } else if (activeBehavior != null) {
            map.put("progress", activeBehavior.getProgress().toMap());
        }
        return map;
    }

    public void clearLastDirective() {
        this.lastDirective = null;
        this.lastProgress = null;
    }

    // ── overlay accessors (server thread) ────────────────────────────────

    /** Active directive, or the retained terminal one — what a viewer means by "current". */
    public Directive peekDirective() {
        return activeDirective != null ? activeDirective : lastDirective;
    }

    public String stateLine() {
        return activeBehavior != null ? activeBehavior.describeState() : "idle";
    }

    public String currentPhase() {
        if (activeBehavior != null && activeBehavior != idleBehavior) {
            return activeBehavior.getProgress().getPhase();
        }
        if (lastProgress != null) return lastProgress.getPhase();
        return "idle";
    }
}
