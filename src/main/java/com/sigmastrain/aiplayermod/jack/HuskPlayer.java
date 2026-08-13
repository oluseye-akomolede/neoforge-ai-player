package com.sigmastrain.aiplayermod.jack;

import com.mojang.authlib.GameProfile;
import com.sigmastrain.aiplayermod.bot.BotServerPlayer;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ClientInformation;
import net.minecraft.server.level.ServerLevel;

/**
 * The body left behind.
 *
 * <p>Extends the bots' fake-player base for its safety overrides (the
 * isAlliedTo NPE guard), but reverses the visibility decision: bots hide
 * from targeting; the husk is a REAL presence. Mobs must be able to see it —
 * an invulnerable body-double would make jack-in free, and free is the one
 * thing it must not be.
 */
public class HuskPlayer extends BotServerPlayer {

    public HuskPlayer(MinecraftServer server, ServerLevel level, GameProfile profile,
                      ClientInformation clientInfo) {
        super(server, level, profile, clientInfo);
    }

    @Override
    public boolean canBeSeenByAnyone() {
        return true;
    }

    /**
     * The husk does not tick. First live jack-in crashed the server four
     * seconds in: rctmod's player-tick hook assumed every ticking player has
     * login-time state (`PlayerState.get(player)` → null → NPE on the server
     * thread). Any of 327 mods may make that assumption, and the tick
     * pipeline is where they all hook.
     *
     * <p>Everything the husk exists for is push-based and survives this:
     * mobs target it (it is tracked and visible), {@code hurt()} lands,
     * death events fire, damage mirrors to the traveler. What it loses is
     * tick-driven physics — no falling, no fire burn-down — which was
     * already an accepted edge ("jack in mid-air and your body hangs
     * there").
     */
    @Override
    public void tick() {
        // no-op: see class comment
    }

    @Override
    public void doTick() {
        // no-op: ServerPlayer's tick entry point on some paths
    }
}
