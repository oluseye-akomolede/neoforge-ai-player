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
        if (activeDirective != null && activeDirective.getStatus() == DirectiveStatus.ACTIVE) {
            activeDirective.cancel();
        }
        if (activeBehavior != null) {
            activeBehavior.stop();
        }
        activeDirective = null;
        lastDirective = null;
        activeBehavior = idleBehavior;
        pendingDirective = null;
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
                }
                activeBehavior = idleBehavior;
                activeDirective = null;
            }
            case RUNNING -> {}
        }
    }

    private void applyDirective(Directive directive) {
        if (activeBehavior != null && activeBehavior != idleBehavior) {
            activeBehavior.stop();
        }
        if (activeDirective != null && activeDirective.getStatus() == DirectiveStatus.ACTIVE) {
            activeDirective.cancel();
        }

        activeDirective = directive;
        activeBehavior = createBehavior(directive.getType());
        activeBehavior.start(bot, directive);

        AIPlayerMod.LOGGER.info("[{}] New directive: {} target={}",
                bot.getPlayer().getName().getString(), directive.getType(), directive.getTarget());
        bot.systemChat("Directive: " + directive.getType()
                + (directive.getTarget() != null ? " → " + directive.getTarget() : ""), "dark_aqua");
    }

    private Behavior createBehavior(DirectiveType type) {
        return switch (type) {
            case MINE -> new MineBehavior();
            case GOTO -> new GotoBehavior();
            case FOLLOW -> new FollowBehavior();
            case CRAFT -> new CraftBehavior();
            case SMELT -> new SmeltBehavior();
            case ENCHANT -> new EnchantBehavior();
            case BREW -> new BrewBehavior();
            case COMBAT -> new CombatBehavior();
            case CHANNEL -> new ChannelBehavior();
            case IDLE -> idleBehavior;
            default -> idleBehavior;
        };
    }

    public Map<String, Object> toMap() {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("state", activeBehavior != null ? activeBehavior.describeState() : "idle");
        map.put("self_preservation", selfPreservation.isFleeing() ? "fleeing" : "ok");
        if (activeDirective != null) {
            map.put("directive", activeDirective.toMap());
        } else if (lastDirective != null) {
            map.put("directive", lastDirective.toMap());
        }
        if (activeBehavior != null) {
            map.put("progress", activeBehavior.getProgress().toMap());
        }
        return map;
    }

    public void clearLastDirective() {
        this.lastDirective = null;
    }
}
