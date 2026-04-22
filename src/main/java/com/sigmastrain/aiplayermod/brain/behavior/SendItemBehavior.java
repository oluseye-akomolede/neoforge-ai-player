package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.bot.BotManager;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import net.minecraft.core.particles.ParticleTypes;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.sounds.SoundEvents;
import net.minecraft.sounds.SoundSource;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.phys.Vec3;

/**
 * Sends items to another bot by item name (not slot).
 * Directive target = "item_id>bot_name" (e.g. "minecraft:iron_ingot>Scout")
 * Directive count = how many to send.
 */
public class SendItemBehavior implements Behavior {
    private final ProgressReport progress = new ProgressReport();

    private String itemId;
    private String targetBot;
    private int count;
    private int transferTicks;
    private int sourceSlot = -1;

    private static final int TRANSFER_DURATION = 40; // 2 seconds

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
        progress.setPhase("validate");

        String raw = directive.getTarget();
        if (raw == null || !raw.contains(">")) {
            progress.setFailureReason("Invalid send_item target format. Expected 'item_id>bot_name'");
            return;
        }

        String[] parts = raw.split(">", 2);
        this.itemId = parts[0].trim();
        this.targetBot = parts[1].trim();
        this.count = directive.getCount() > 0 ? directive.getCount() : 1;
        this.transferTicks = 0;

        if (!itemId.contains(":")) {
            itemId = "minecraft:" + itemId;
        }

        progress.logEvent("Send " + count + "x " + itemId + " to " + targetBot);
        bot.systemChat("Sending " + count + "x " + itemId + " to " + targetBot, "light_purple");
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();

        if (progress.toMap().containsKey("failure_reason")) {
            return BehaviorResult.FAILED;
        }

        if (transferTicks == 0) {
            BotPlayer target = BotManager.getBot(targetBot);
            if (target == null) {
                progress.setFailureReason("Bot '" + targetBot + "' not found");
                return BehaviorResult.FAILED;
            }

            Item item = BuiltInRegistries.ITEM.get(ResourceLocation.parse(itemId));
            if (item == Items.AIR) {
                progress.setFailureReason("Unknown item: " + itemId);
                return BehaviorResult.FAILED;
            }

            sourceSlot = findItemSlot(player, item);
            if (sourceSlot < 0) {
                progress.setFailureReason("No " + itemId + " in inventory");
                return BehaviorResult.FAILED;
            }

            ItemStack stack = player.getInventory().getItem(sourceSlot);
            if (stack.getCount() < count) {
                int available = collectItem(player, item);
                if (available < count) {
                    progress.setFailureReason("Only have " + available + "x " + itemId + ", need " + count);
                    return BehaviorResult.FAILED;
                }
                sourceSlot = findItemSlot(player, item);
            }

            progress.setPhase("transferring");
            ServerLevel level = player.serverLevel();
            level.playSound(null, player.blockPosition(),
                    SoundEvents.ENDERMAN_TELEPORT, SoundSource.PLAYERS, 0.4f, 1.8f);
        }

        ServerLevel level = player.serverLevel();
        Vec3 pos = player.position();
        if (transferTicks % 3 == 0) {
            level.sendParticles(ParticleTypes.REVERSE_PORTAL,
                    pos.x, pos.y + 1.0, pos.z, 3, 0.4, 0.4, 0.4, 0.1);
        }

        transferTicks++;
        if (transferTicks < TRANSFER_DURATION) {
            return BehaviorResult.RUNNING;
        }

        ItemStack stack = player.getInventory().getItem(sourceSlot);
        Item item = BuiltInRegistries.ITEM.get(ResourceLocation.parse(itemId));
        if (stack.isEmpty() || !stack.is(item)) {
            sourceSlot = findItemSlot(player, item);
            if (sourceSlot < 0) {
                progress.setFailureReason("Items disappeared during transfer");
                return BehaviorResult.FAILED;
            }
            stack = player.getInventory().getItem(sourceSlot);
        }

        BotPlayer target = BotManager.getBot(targetBot);
        if (target == null) {
            progress.setFailureReason("Target bot disconnected during transfer");
            return BehaviorResult.FAILED;
        }

        int toSend = Math.min(count, stack.getCount());
        ItemStack sendStack = stack.copyWithCount(toSend);
        stack.shrink(toSend);

        ServerPlayer receiver = target.getPlayer();
        if (!receiver.getInventory().add(sendStack)) {
            receiver.drop(sendStack, false);
        }

        level.sendParticles(ParticleTypes.REVERSE_PORTAL,
                pos.x, pos.y + 1.0, pos.z, 10, 0.5, 0.5, 0.5, 0.15);
        level.playSound(null, player.blockPosition(),
                SoundEvents.ENDERMAN_TELEPORT, SoundSource.PLAYERS, 0.5f, 1.5f);

        ServerLevel recLevel = receiver.serverLevel();
        Vec3 recPos = receiver.position();
        recLevel.sendParticles(ParticleTypes.REVERSE_PORTAL,
                recPos.x, recPos.y + 1.0, recPos.z, 10, 0.5, 0.5, 0.5, 0.15);
        recLevel.playSound(null, receiver.blockPosition(),
                SoundEvents.ENDERMAN_TELEPORT, SoundSource.PLAYERS, 0.5f, 1.5f);

        progress.increment("items_sent", toSend);
        progress.logEvent("Sent " + toSend + "x " + itemId + " to " + targetBot);
        bot.systemChat("Sent " + toSend + "x " + itemId + " → " + targetBot, "green");
        AIPlayerMod.LOGGER.info("[{}] Sent {}x {} to {}",
                player.getName().getString(), toSend, itemId, targetBot);

        return BehaviorResult.SUCCESS;
    }

    private int findItemSlot(ServerPlayer player, Item item) {
        for (int i = 0; i < 36; i++) {
            ItemStack s = player.getInventory().getItem(i);
            if (!s.isEmpty() && s.is(item)) {
                return i;
            }
        }
        return -1;
    }

    private int collectItem(ServerPlayer player, Item item) {
        int total = 0;
        for (int i = 0; i < 36; i++) {
            ItemStack s = player.getInventory().getItem(i);
            if (!s.isEmpty() && s.is(item)) {
                total += s.getCount();
            }
        }
        return total;
    }

    @Override
    public String describeState() {
        return "Sending " + count + "x " + itemId + " to " + targetBot
                + " (" + transferTicks + "/" + TRANSFER_DURATION + ")";
    }

    @Override
    public ProgressReport getProgress() { return progress; }

    @Override
    public void stop() {}
}
