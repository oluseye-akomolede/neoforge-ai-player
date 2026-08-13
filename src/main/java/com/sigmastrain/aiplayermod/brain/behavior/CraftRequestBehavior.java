package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import com.sigmastrain.aiplayermod.compat.ae2.WirelessMECrafting;

/**
 * CRAFT_REQUEST — submit an autocrafting job to the ME network and stand by
 * until the grid finishes it.
 *
 * <p>The bot is a client of the network here, not a crafter: the request
 * goes through the worn wireless terminal, the grid's CPUs do the work, and
 * the products land in network storage (pull them with ME_WITHDRAW). The
 * directive completes when the crafting link reports done — "submitted" is
 * not "crafted", and criteria that check too early deserve that failure.
 */
public class CraftRequestBehavior implements Behavior {

    private final ProgressReport progress = new ProgressReport();
    private String itemId;
    private int count;
    private int pollCooldown;
    private boolean started;
    private BotPlayer bot;
    private String startupFailure;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        this.bot = bot;
        itemId = directive.getTarget();
        count = Math.max(1, directive.getCount() > 0 ? directive.getCount() : 1);
        started = false;
        pollCooldown = 0;
        progress.setPhase("requesting");
        startupFailure = null;
        if (itemId == null || itemId.isEmpty()) {
            startupFailure = "No item specified";
            progress.setFailureReason(startupFailure);
        }
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        if (startupFailure != null) return BehaviorResult.FAILED;
        var player = bot.getPlayer();
        if (player == null) {
            progress.setFailureReason("bot has no body");
            return BehaviorResult.FAILED;
        }

        if (!started) {
            String err = WirelessMECrafting.startRequest(player, itemId, count);
            if (err != null) {
                progress.setFailureReason(err);
                progress.logEvent("craft request refused: " + err);
                return BehaviorResult.FAILED;
            }
            started = true;
            progress.setPhase("calculating");
            progress.logEvent("Requested " + count + "x " + itemId + " from the grid");
            bot.systemChat("Requesting " + count + "x " + itemId
                    + " from the ME network…", "aqua");
            return BehaviorResult.RUNNING;
        }

        // The grid works on its own clock — poll once a second, not per tick.
        if (++pollCooldown < 20) return BehaviorResult.RUNNING;
        pollCooldown = 0;

        var job = WirelessMECrafting.poll(player);
        if (job == null) {
            progress.setFailureReason("craft job vanished");
            return BehaviorResult.FAILED;
        }
        progress.setPhase(job.state().toLowerCase());

        return switch (job.state()) {
            case "CALCULATING", "CRAFTING" -> BehaviorResult.RUNNING;
            case "DONE" -> {
                progress.putResult("crafted", count);
                progress.putResult("item", itemId);
                progress.logEvent("Grid finished: " + job.detail());
                bot.systemChat("Craft complete — " + job.detail(), "green");
                yield BehaviorResult.SUCCESS;
            }
            default -> {
                progress.setFailureReason(job.detail());
                progress.logEvent("Craft failed: " + job.detail());
                yield BehaviorResult.FAILED;
            }
        };
    }

    @Override
    public void stop() {
        // An interrupted directive cancels the grid job — a directive the
        // player killed must not keep consuming network resources silently.
        if (started && bot != null && bot.getPlayer() != null) {
            WirelessMECrafting.cancel(bot.getPlayer());
        }
    }

    @Override
    public ProgressReport getProgress() {
        return progress;
    }

    @Override
    public String describeState() {
        return "craft_request " + count + "x " + itemId
                + " (" + progress.getPhase() + ")";
    }
}
