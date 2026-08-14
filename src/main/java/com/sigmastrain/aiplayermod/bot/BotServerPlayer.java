package com.sigmastrain.aiplayermod.bot;

import com.mojang.authlib.GameProfile;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ClientInformation;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.Entity;

public class BotServerPlayer extends ServerPlayer {

    public BotServerPlayer(MinecraftServer server, ServerLevel level, GameProfile profile, ClientInformation clientInfo) {
        super(server, level, profile, clientInfo);
    }

    @Override
    public boolean canBeSeenByAnyone() {
        // Bots must be targetable: TargetingConditions.test() checks this
        // FIRST, so returning false made every hostile mob ignore the fleet.
        // (Melee/combat targeting funnels through this check, and the
        // BotAggro pump hands targets to hostiles directly — but they could
        // never land a hit while this was false.) Crash-prone mod selectors
        // that dereference fake-player state are now contained by
        // TargetingConditionsMixin instead of by hiding the bot.
        return true;
    }

    @Override
    public boolean isAlliedTo(Entity other) {
        // Bot players aren't registered with FTB Teams/Chunks, so mod-level
        // alliance checks (e.g. Ars Nouveau summons → FTB Chunks getOrCreateData)
        // throw NPE. Wrap the call to prevent server crashes.
        try {
            return super.isAlliedTo(other);
        } catch (NullPointerException e) {
            return false;
        }
    }
}
