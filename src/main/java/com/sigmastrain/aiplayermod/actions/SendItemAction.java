package com.sigmastrain.aiplayermod.actions;

import com.sigmastrain.aiplayermod.bot.BotManager;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.core.particles.ParticleTypes;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.sounds.SoundEvents;
import net.minecraft.sounds.SoundSource;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.phys.Vec3;

public class SendItemAction implements BotAction {
    private final int slot;
    private final String targetBot;
    private final int count;
    private int ticksRemaining = 40; // 2 second transfer
    private String result = null;

    public SendItemAction(int slot, String targetBot, int count) {
        this.slot = slot;
        this.targetBot = targetBot;
        this.count = Math.max(1, count);
    }

    @Override
    public boolean tick(BotPlayer bot) {
        ServerPlayer sender = bot.getPlayer();

        // First tick: validate
        if (ticksRemaining == 40) {
            ItemStack stack = sender.getInventory().getItem(slot);
            if (stack.isEmpty()) {
                result = "FAILED: Slot " + slot + " is empty";
                return true;
            }

            BotPlayer target = BotManager.getBot(targetBot);
            if (target == null) {
                result = "FAILED: Bot '" + targetBot + "' not found";
                return true;
            }

            if (stack.getCount() < count) {
                result = "FAILED: Slot " + slot + " only has " + stack.getCount()
                        + " items, requested " + count;
                return true;
            }

            // Start sound
            ServerLevel level = (ServerLevel) sender.level();
            level.playSound(null, sender.blockPosition(),
                    SoundEvents.ENDERMAN_TELEPORT, SoundSource.PLAYERS, 0.4f, 1.8f);
        }

        // Channeling particles on sender
        ServerLevel level = (ServerLevel) sender.level();
        Vec3 pos = sender.position();
        if (ticksRemaining % 3 == 0) {
            level.sendParticles(ParticleTypes.REVERSE_PORTAL,
                    pos.x, pos.y + 1.0, pos.z,
                    3, 0.4, 0.4, 0.4, 0.1);
        }

        ticksRemaining--;
        if (ticksRemaining > 0) return false;

        // Complete transfer
        ItemStack stack = sender.getInventory().getItem(slot);
        if (stack.isEmpty() || stack.getCount() < count) {
            result = "FAILED: Items removed from slot during transfer";
            return true;
        }

        BotPlayer target = BotManager.getBot(targetBot);
        if (target == null) {
            result = "FAILED: Target bot '" + targetBot + "' disconnected during transfer";
            return true;
        }

        String itemName = BuiltInRegistries.ITEM.getKey(stack.getItem()).toString();
        ItemStack toSend = stack.copyWithCount(count);
        stack.shrink(count);

        ServerPlayer receiver = target.getPlayer();
        receiver.getInventory().add(toSend);

        // Effects on sender
        level.sendParticles(ParticleTypes.REVERSE_PORTAL,
                pos.x, pos.y + 1.0, pos.z,
                10, 0.5, 0.5, 0.5, 0.15);
        level.playSound(null, sender.blockPosition(),
                SoundEvents.ENDERMAN_TELEPORT, SoundSource.PLAYERS, 0.5f, 1.5f);

        // Effects on receiver (may be in different dimension)
        ServerLevel recLevel = (ServerLevel) receiver.level();
        Vec3 recPos = receiver.position();
        recLevel.sendParticles(ParticleTypes.REVERSE_PORTAL,
                recPos.x, recPos.y + 1.0, recPos.z,
                10, 0.5, 0.5, 0.5, 0.15);
        recLevel.playSound(null, receiver.blockPosition(),
                SoundEvents.ENDERMAN_TELEPORT, SoundSource.PLAYERS, 0.5f, 1.5f);

        result = "Sent " + count + "x " + itemName + " to " + targetBot;
        return true;
    }

    @Override
    public String getResult() { return result; }

    @Override
    public String describe() {
        return String.format("SendItem(slot=%d -> %s, %ds remaining)", slot, targetBot, ticksRemaining / 20);
    }
}
