package com.sigmastrain.aiplayermod.bot;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import net.minecraft.network.PacketSendListener;
import net.minecraft.network.protocol.Packet;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.network.CommonListenerCookie;
import net.minecraft.server.network.ServerGamePacketListenerImpl;

public class BotPacketListener extends ServerGamePacketListenerImpl {

    public BotPacketListener(MinecraftServer server, BotConnection connection, ServerPlayer player, CommonListenerCookie cookie) {
        super(server, connection, player, cookie);
    }

    @Override
    public void send(Packet<?> packet) {
        // silently drop all packets — bot has no real client
    }

    @Override
    public void send(Packet<?> packet, PacketSendListener listener) {
        // silently drop
    }
}
