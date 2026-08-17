package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import com.sigmastrain.aiplayermod.brain.Requisitions;
import net.minecraft.core.particles.ParticleTypes;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.phys.Vec3;

/**
 * REQUISITION — the bot asks its supplier for something and waits.
 *
 * <p>{@code target}: {@code vehicle:<superbwarfare entity id or loose name>}
 * (e.g. {@code vehicle:lav_150}, {@code vehicle:LAV-150 Commando}) or an item
 * id; {@code count} for items (default 1); {@code extra.wait} = seconds to
 * wait for a supplier (default 20). This mod is economy-agnostic: it posts to
 * {@link Requisitions} and holds; hive-mod prices and fulfils the request from
 * the owner's FE reservoir and reports back. A fleet bot with no owner is
 * refused by the supplier and this fails with that reason.
 */
public class RequisitionBehavior implements Behavior {

    private static final int DEFAULT_WAIT = 20;
    private static final int MAX_WAIT = 300;

    private final ProgressReport progress = new ProgressReport();
    private String botName;
    private String kind, what;
    private int count;
    private int waitTicks, ticks;
    private boolean done, failed;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        done = false; failed = false; ticks = 0;
        botName = bot.getPlayer().getGameProfile().getName();
        String target = directive.getTarget() == null ? "" : directive.getTarget().trim();
        if (target.regionMatches(true, 0, "vehicle:", 0, 8)) {
            kind = "vehicle";
            what = target.substring(8).trim();
        } else {
            kind = "item";
            what = target;
        }
        count = Math.max(1, directive.getCount() > 0 ? directive.getCount() : 1);
        int w = DEFAULT_WAIT;
        try { w = Integer.parseInt(directive.getExtra().getOrDefault("wait", String.valueOf(DEFAULT_WAIT)).trim()); } catch (NumberFormatException ignored) {}
        waitTicks = Math.max(1, Math.min(MAX_WAIT, w)) * 20;

        if (what.isEmpty()) {
            fail(bot, "nothing to requisition (target is empty)");
            return;
        }
        long now = bot.getPlayer().serverLevel().getGameTime();
        Requisitions.post(new Requisitions.Request(botName, kind, what, count, now));
        progress.setPhase("requisitioning " + kind + " " + what);
        progress.logEvent("Requisition posted: " + kind + " " + what + (kind.equals("item") ? " x" + count : ""));
        bot.systemChat("Requisitioning " + (kind.equals("vehicle") ? "vehicle " : "") + what
                + (kind.equals("item") && count > 1 ? " x" + count : "") + "…", "aqua");
        AIPlayerMod.LOGGER.info("[{}] REQUISITION {} {} x{}", botName, kind, what, count);
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        if (done) return failed ? BehaviorResult.FAILED : BehaviorResult.SUCCESS;
        ticks++;
        ServerPlayer p = bot.getPlayer();
        if (ticks % 5 == 0 && p.level() instanceof ServerLevel sl) {
            Vec3 pos = p.position();
            sl.sendParticles(ParticleTypes.PORTAL, pos.x, pos.y + 1.0, pos.z, 4, 0.4, 0.5, 0.4, 0.05);
        }
        Requisitions.Outcome o = Requisitions.take(botName);
        if (o != null) {
            done = true;
            failed = !o.ok();
            progress.logEvent((o.ok() ? "Requisition fulfilled: " : "Requisition refused: ") + o.message());
            if (!o.detail().isEmpty()) progress.putResult("requisition", o.detail());
            if (o.ok()) {
                bot.systemChat(o.message(), "green");
                return BehaviorResult.SUCCESS;
            }
            progress.setFailureReason(o.message());
            bot.systemChat("Requisition refused: " + o.message(), "red");
            return BehaviorResult.FAILED;
        }
        if (ticks >= waitTicks) {
            Requisitions.cancel(botName);
            fail(bot, "no supplier answered the requisition (is the hive owner online?)");
            return BehaviorResult.FAILED;
        }
        return BehaviorResult.RUNNING;
    }

    private void fail(BotPlayer bot, String why) {
        done = true; failed = true;
        progress.setFailureReason(why);
        progress.logEvent("Requisition failed: " + why);
        bot.systemChat("Requisition failed: " + why, "red");
    }

    @Override
    public String describeState() {
        return done ? (failed ? "Requisition failed" : "Requisition fulfilled")
                : "Requisitioning " + kind + " " + what + " (" + (ticks / 20) + "s)";
    }

    @Override
    public ProgressReport getProgress() { return progress; }

    @Override
    public void stop() {
        if (!done && botName != null) Requisitions.cancel(botName);
    }
}
