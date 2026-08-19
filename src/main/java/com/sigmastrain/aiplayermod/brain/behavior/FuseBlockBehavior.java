package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.bot.AnchorManager;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.Fusion;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import com.sigmastrain.aiplayermod.compat.blockfusion.BlockFusionCompat;
import net.minecraft.core.BlockPos;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;

import java.util.Map;

/**
 * Fuse the bot with an energy block, then hand off to a continuous
 * {@link ManageFusionBehavior}. The target resolves three ways (mirroring
 * AreaLoot): directive location → {@code extra.x/y/z} (a marked block) → the
 * block the bot is looking at. Fleet bots with no hive owner still fuse here
 * (aiplayermod is economy-agnostic); hive simply won't credit them any FE.
 */
public class FuseBlockBehavior implements Behavior {

    private final ProgressReport progress = new ProgressReport();
    private boolean handedOff;
    private boolean failed;

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        handedOff = false; failed = false;
        ServerPlayer player = bot.getPlayer();
        ServerLevel level = player.serverLevel();

        BlockPos pos = resolve(bot, directive);
        if (pos == null) { fail(bot, "no block to fuse with (look at one, mark one, or give x/y/z)"); return; }
        if (!BlockFusionCompat.isEnergyBlock(level, pos)) {
            fail(bot, BlockFusionCompat.blockName(level, pos) + " is not an energy block");
            return;
        }
        BlockFusionCompat.Role role = BlockFusionCompat.roleOf(level, pos);
        if (role == BlockFusionCompat.Role.NONE) { fail(bot, "that block has no usable energy interface"); return; }

        // Role/mode overrides from the order.
        Map<String, String> extra = directive.getExtra();
        String roleHint = extra.getOrDefault("role", "");
        if (!roleHint.isEmpty()) {
            try { role = BlockFusionCompat.Role.valueOf(roleHint.toUpperCase()); } catch (IllegalArgumentException ignored) {}
        }
        Fusion.Mode mode = "output".equalsIgnoreCase(extra.getOrDefault("mode", "capacity"))
                ? Fusion.Mode.OUTPUT : Fusion.Mode.CAPACITY;

        // Step onto the block, hide, anchor its chunk so the device keeps ticking.
        bot.teleport(pos.getX() + 0.5, pos.getY() + 1.0, pos.getZ() + 0.5);
        bot.lookAt(pos.getX() + 0.5, pos.getY() + 0.5, pos.getZ() + 0.5);
        AnchorManager.enable(bot);
        bot.setFusedInvisible(true);

        String dim = level.dimension().location().toString();
        Fusion.fuse(player.getGameProfile().getName(), dim, pos, role, mode);

        String name = BlockFusionCompat.blockName(level, pos);
        progress.putResult("block", name);
        progress.putResult("role", role.name());
        progress.logEvent("Fused with " + name + " (" + role + ")");
        bot.systemChat("Fused with " + name + " — " + role.name().toLowerCase()
                + (role == BlockFusionCompat.Role.STORAGE ? " (" + mode.name().toLowerCase() + ")" : ""), "aqua");
        AIPlayerMod.LOGGER.info("[{}] FUSE {} at {} role={} mode={}",
                player.getGameProfile().getName(), name, pos.toShortString(), role, mode);

        // Hand off to the continuous manager, whose knobs L3 can tune live.
        Directive manage = Directive.builder(com.sigmastrain.aiplayermod.brain.DirectiveType.MANAGE_FUSION).build();
        bot.getBrain().setDirective(manage);
        handedOff = true;
    }

    private BlockPos resolve(BotPlayer bot, Directive directive) {
        if (directive.hasLocation()) return new BlockPos((int) directive.getX(), (int) directive.getY(), (int) directive.getZ());
        Map<String, String> e = directive.getExtra();
        try {
            if (e.containsKey("x") && e.containsKey("y") && e.containsKey("z")) {
                return new BlockPos(Integer.parseInt(e.get("x").trim()), Integer.parseInt(e.get("y").trim()), Integer.parseInt(e.get("z").trim()));
            }
        } catch (NumberFormatException ignored) {}
        return bot.blockLookingAt();
    }

    private void fail(BotPlayer bot, String why) {
        failed = true;
        progress.setFailureReason(why);
        progress.logEvent("Fuse failed: " + why);
        bot.systemChat("Can't fuse: " + why, "red");
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        if (failed) return BehaviorResult.FAILED;
        return handedOff ? BehaviorResult.SUCCESS : BehaviorResult.FAILED;
    }

    @Override public String describeState() { return failed ? "Fuse failed" : "Fusing with block"; }
    @Override public ProgressReport getProgress() { return progress; }
    @Override public void stop() {}
}
