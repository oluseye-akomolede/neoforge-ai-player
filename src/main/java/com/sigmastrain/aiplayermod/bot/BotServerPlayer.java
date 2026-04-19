package com.sigmastrain.aiplayermod.bot;

import com.mojang.authlib.GameProfile;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ClientInformation;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;

public class BotServerPlayer extends ServerPlayer {

    public BotServerPlayer(MinecraftServer server, ServerLevel level, GameProfile profile, ClientInformation clientInfo) {
        super(server, level, profile, clientInfo);
    }

    @Override
    public boolean canBeSeenByAnyone() {
        // Prevents TargetingConditions from reaching mod predicates that crash
        // on fake players (e.g. rctmod's PlayerState.get() returning null).
        // Does NOT affect client-side rendering — visibility is based on entity tracking.
        return false;
    }
}
