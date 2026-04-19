package com.sigmastrain.aiplayermod.bot;

import io.netty.channel.embedded.EmbeddedChannel;
import net.minecraft.network.Connection;
import net.minecraft.network.PacketSendListener;
import net.minecraft.network.protocol.Packet;
import net.minecraft.network.protocol.PacketFlow;
import net.minecraft.server.MinecraftServer;

import java.lang.reflect.Field;
import java.net.InetSocketAddress;

public class BotConnection extends Connection {

    private static final EmbeddedChannel DUMMY_CHANNEL = new EmbeddedChannel();

    public BotConnection(MinecraftServer server) {
        super(PacketFlow.SERVERBOUND);
        try {
            Field channelField = Connection.class.getDeclaredField("channel");
            channelField.setAccessible(true);
            channelField.set(this, new EmbeddedChannel());

            Field addressField = Connection.class.getDeclaredField("address");
            addressField.setAccessible(true);
            addressField.set(this, new InetSocketAddress("127.0.0.1", 0));
        } catch (Exception e) {
            throw new RuntimeException("Failed to initialize BotConnection", e);
        }
    }

    @Override
    public void send(Packet<?> packet) {
    }

    @Override
    public void send(Packet<?> packet, PacketSendListener listener) {
    }

    @Override
    public void send(Packet<?> packet, PacketSendListener listener, boolean flush) {
    }

    @Override
    public boolean isConnected() {
        return true;
    }

    @Override
    public boolean isMemoryConnection() {
        return true;
    }
}
