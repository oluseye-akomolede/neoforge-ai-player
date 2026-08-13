package com.sigmastrain.aiplayermod.network;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.bot.BotManager;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.stats.Stats;
import net.neoforged.bus.api.SubscribeEvent;
import net.neoforged.fml.common.EventBusSubscriber;
import net.neoforged.neoforge.event.entity.player.PlayerEvent;
import net.neoforged.neoforge.event.tick.ServerTickEvent;
import net.neoforged.neoforge.network.PacketDistributor;
import net.neoforged.neoforge.network.event.RegisterPayloadHandlersEvent;
import net.neoforged.neoforge.network.registration.PayloadRegistrar;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Registration and the server half of the overlay channel.
 *
 * <p>Snapshots are push-on-subscribe: nothing is built or sent unless at
 * least one player has the overlay open. At ~4 Hz with five bots the payload
 * is a few hundred bytes — but the discipline matters more than the number,
 * because the hive mod will multiply everything.
 *
 * <p>Registered {@code optional()} so a client running an older jar (MinIO
 * sync lag) can still connect; the overlay simply stays dark until the
 * client catches up.
 */
@EventBusSubscriber(modid = AIPlayerMod.MOD_ID, bus = EventBusSubscriber.Bus.MOD)
public final class OverlayNetwork {

    private OverlayNetwork() {}

    /** Players currently holding the overlay open. */
    private static final Set<UUID> SUBSCRIBERS = ConcurrentHashMap.newKeySet();

    private static final int SNAPSHOT_INTERVAL_TICKS = 5; // 4 Hz
    private static long tickCounter = 0;

    /**
     * The hive-seam address: resolve a bot by stable UUID first, display
     * name second. Every C2S handler goes through here, so a client that
     * addresses by id (the contract) and one that still says "Mystic" both
     * work — and nothing server-side ever assumes name==identity.
     */
    static BotPlayer resolveBot(String idOrName) {
        if (idOrName == null || idOrName.isEmpty()) return null;
        try {
            UUID id = UUID.fromString(idOrName);
            for (BotPlayer b : BotManager.getAllBots().values()) {
                if (b.getPlayer() != null && b.getPlayer().getUUID().equals(id)) return b;
            }
            return null;
        } catch (IllegalArgumentException notAUuid) {
            return BotManager.getBot(idOrName);
        }
    }

    /** Display name for a resolved bot (payloads may carry either form). */
    static String botName(BotPlayer bot) {
        return bot.getPlayer() != null ? bot.getPlayer().getGameProfile().getName() : "?";
    }

    @SubscribeEvent
    public static void onRegisterPayloads(RegisterPayloadHandlersEvent event) {
        PayloadRegistrar registrar = event.registrar("1").optional();

        registrar.playToServer(
                OverlayPayloads.OverlaySubscribe.TYPE,
                OverlayPayloads.OverlaySubscribe.CODEC,
                (payload, context) -> context.enqueueWork(() -> {
                    if (context.player() instanceof ServerPlayer sp) {
                        if (payload.on()) {
                            SUBSCRIBERS.add(sp.getUUID());
                            // Immediate first frame — the overlay should not
                            // open onto a blank pane while waiting for the
                            // next scheduled tick.
                            PacketDistributor.sendToPlayer(sp, buildSnapshot());
                            PacketDistributor.sendToPlayer(sp, buildInboxState());
                        } else {
                            SUBSCRIBERS.remove(sp.getUUID());
                        }
                    }
                }));

        registrar.playToServer(
                OverlayPayloads.InterruptDirective.TYPE,
                OverlayPayloads.InterruptDirective.CODEC,
                (payload, context) -> context.enqueueWork(() -> {
                    if (!(context.player() instanceof ServerPlayer sp)) return;
                    BotPlayer bot = resolveBot(payload.bot());
                    if (bot == null) {
                        PacketDistributor.sendToPlayer(sp, new OverlayPayloads.ControlAck(
                                false, "no bot named " + payload.bot()));
                        return;
                    }
                    // Same id-scoped cancel the HTTP API uses — the D3 race
                    // guard ignores this if a newer directive took over.
                    bot.getBrain().cancelDirective(payload.directiveId());
                    AIPlayerMod.LOGGER.info("[overlay] {} interrupted {} (directive id={})",
                            sp.getName().getString(), botName(bot), payload.directiveId());
                    PacketDistributor.sendToPlayer(sp, new OverlayPayloads.ControlAck(
                            true, "interrupted " + botName(bot)));
                    PacketDistributor.sendToPlayer(sp, buildSnapshot());
                }));

        registrar.playToServer(
                OverlayPayloads.RequestVault.TYPE,
                OverlayPayloads.RequestVault.CODEC,
                (payload, context) -> context.enqueueWork(() -> {
                    if (!(context.player() instanceof ServerPlayer sp)) return;
                    BotPlayer bot = resolveBot(payload.bot());
                    if (bot != null) {
                        PacketDistributor.sendToPlayer(sp, buildVaultSnapshot(botName(bot), bot, payload.query()));
                    }
                }));

        registrar.playToServer(
                OverlayPayloads.VaultOp.TYPE,
                OverlayPayloads.VaultOp.CODEC,
                (payload, context) -> context.enqueueWork(() -> {
                    if (!(context.player() instanceof ServerPlayer sp)) return;
                    BotPlayer bot = resolveBot(payload.bot());
                    if (bot == null) return;
                    String msg;
                    if (payload.toVault()) {
                        Map<String, Object> res = bot.storeToVault(payload.itemId(), payload.count());
                        Object stored = res.getOrDefault("stored", res.getOrDefault("stored_stacks", 0));
                        msg = "stowed " + stored + " " + shortItem(payload.itemId());
                    } else {
                        int moved = bot.getVault().withdrawInto(
                                bot.getPlayer().getInventory(), payload.itemId(), payload.count());
                        msg = moved > 0
                                ? "withdrew " + moved + " " + shortItem(payload.itemId())
                                : "pack full — nothing withdrawn";
                    }
                    PacketDistributor.sendToPlayer(sp, new OverlayPayloads.ControlAck(true, msg));
                    PacketDistributor.sendToPlayer(sp, buildVaultSnapshot(botName(bot), bot, ""));
                }));

        registrar.playToServer(
                OverlayPayloads.MEOp.TYPE,
                OverlayPayloads.MEOp.CODEC,
                (payload, context) -> context.enqueueWork(() -> {
                    if (!(context.player() instanceof ServerPlayer sp)) return;
                    BotPlayer bot = resolveBot(payload.bot());
                    if (bot == null) return;
                    var access = com.sigmastrain.aiplayermod.compat.ae2.WirelessME
                            .resolve(bot.getPlayer());
                    if (!access.online()) {
                        PacketDistributor.sendToPlayer(sp, new OverlayPayloads.ControlAck(
                                false, "ME: " + access.status()));
                        return;
                    }
                    int moved = 0;
                    if (payload.toME()) {
                        var p = bot.getPlayer();
                        var rl = net.minecraft.resources.ResourceLocation.tryParse(payload.itemId());
                        for (int i = 0; i < p.getInventory().getContainerSize()
                                && moved < payload.count(); i++) {
                            var stack = p.getInventory().getItem(i);
                            if (stack.isEmpty() || stack == access.terminal()) continue;
                            if (rl == null || !net.minecraft.core.registries.BuiltInRegistries.ITEM
                                    .getKey(stack.getItem()).equals(rl)) continue;
                            var take = stack.copy();
                            take.setCount(Math.min(stack.getCount(), payload.count() - moved));
                            int in = com.sigmastrain.aiplayermod.compat.ae2.WirelessME
                                    .insert(access, take);
                            if (in > 0) {
                                stack.shrink(in);
                                p.getInventory().setItem(i, stack.isEmpty()
                                        ? net.minecraft.world.item.ItemStack.EMPTY : stack);
                                moved += in;
                            }
                        }
                    } else {
                        for (var stack : com.sigmastrain.aiplayermod.compat.ae2.WirelessME
                                .extract(access, payload.itemId(), payload.count())) {
                            moved += BotPlayer.deliverTo(bot.getPlayer(), stack);
                        }
                    }
                    PacketDistributor.sendToPlayer(sp, new OverlayPayloads.ControlAck(moved > 0,
                            (payload.toME() ? "pushed " : "pulled ") + moved + " "
                                    + shortItem(payload.itemId())));
                    PacketDistributor.sendToPlayer(sp, buildVaultSnapshot(botName(bot), bot, ""));
                }));

        registrar.playToServer(
                OverlayPayloads.ChannelQuote.TYPE,
                OverlayPayloads.ChannelQuote.CODEC,
                (payload, context) -> context.enqueueWork(() -> {
                    if (!(context.player() instanceof ServerPlayer sp)) return;
                    BotPlayer bot = resolveBot(payload.bot());
                    if (bot == null) return;
                    PacketDistributor.sendToPlayer(sp, buildQuote(botName(bot), bot,
                            payload.itemId(), payload.count()));
                }));

        registrar.playToServer(
                OverlayPayloads.ChannelExecute.TYPE,
                OverlayPayloads.ChannelExecute.CODEC,
                (payload, context) -> context.enqueueWork(() -> {
                    if (!(context.player() instanceof ServerPlayer sp)) return;
                    BotPlayer bot = resolveBot(payload.bot());
                    if (bot == null) return;
                    if (payload.interrupt()) {
                        // Interrupt exactly the directive the player was
                        // looking at — the id travels with the request, so the
                        // D3 guard drops the cancel if something newer took
                        // over between quote and commit.
                        bot.getBrain().cancelDirective(payload.expectDirectiveId());
                    }
                    // The CHANNEL directive, not a raw conjure: the directive
                    // MEDITATES for missing XP before conjuring (the overlay
                    // used to hard-block on affordability while the meditation
                    // path sat unused one layer down).
                    var directive = com.sigmastrain.aiplayermod.brain.Directive
                            .builder(com.sigmastrain.aiplayermod.brain.DirectiveType.CHANNEL)
                            .target(payload.itemId())
                            .count(payload.count())
                            .build();
                    bot.getBrain().setDirective(directive);
                    AIPlayerMod.LOGGER.info("[overlay] {} channels {}x {} for {} (interrupt={})",
                            sp.getName().getString(), payload.count(), payload.itemId(),
                            botName(bot), payload.interrupt());
                    PacketDistributor.sendToPlayer(sp, new OverlayPayloads.ControlAck(true,
                            "channeling " + payload.count() + "x " + shortItem(payload.itemId())
                                    + " §8(meditates if short on XP)"));
                }));

        registrar.playToServer(
                OverlayPayloads.OpenEquipment.TYPE,
                OverlayPayloads.OpenEquipment.CODEC,
                (payload, context) -> context.enqueueWork(() -> {
                    if (!(context.player() instanceof ServerPlayer sp)) return;
                    BotPlayer bot = resolveBot(payload.bot());
                    if (bot == null || bot.getPlayer() == null) return;
                    int entityId = bot.getPlayer().getId();
                    com.sigmastrain.aiplayermod.bot.BotEquipmentMenu
                            .setPendingBotName(botName(bot));
                    sp.openMenu(new net.minecraft.world.SimpleMenuProvider(
                            (id, inv, p) -> new com.sigmastrain.aiplayermod.bot.BotEquipmentMenu(
                                    id, inv, bot.getPlayer().getInventory(), entityId),
                            net.minecraft.network.chat.Component.literal(botName(bot) + "'s Inventory")
                    ), buf -> buf.writeInt(entityId));
                }));

        registrar.playToServer(
                OverlayPayloads.InboxRespond.TYPE,
                OverlayPayloads.InboxRespond.CODEC,
                (payload, context) -> context.enqueueWork(() -> {
                    if (!(context.player() instanceof ServerPlayer sp)) return;
                    boolean ok = com.sigmastrain.aiplayermod.telemetry.EscalationStore.respond(
                            payload.id(), payload.action(), payload.text());
                    AIPlayerMod.LOGGER.info("[L4] {} ruled on {}: {} {}",
                            sp.getName().getString(), payload.id(), payload.action(),
                            payload.text().isEmpty() ? "" : "'" + payload.text() + "'");
                    PacketDistributor.sendToPlayer(sp, new OverlayPayloads.ControlAck(ok,
                            ok ? "ruling sent: " + payload.action()
                               : "question expired or already answered"));
                    PacketDistributor.sendToPlayer(sp, buildInboxState());
                }));

        registrar.playToServer(
                OverlayPayloads.JackIn.TYPE,
                OverlayPayloads.JackIn.CODEC,
                (payload, context) -> context.enqueueWork(() -> {
                    if (!(context.player() instanceof ServerPlayer sp)) return;
                    BotPlayer bot = resolveBot(payload.bot());
                    if (bot == null) {
                        PacketDistributor.sendToPlayer(sp, new OverlayPayloads.ControlAck(
                                false, "no bot " + payload.bot()));
                        return;
                    }
                    String err = com.sigmastrain.aiplayermod.jack.JackInManager
                            .jackIn(sp, botName(bot));
                    if (err != null) {
                        // A refusal must be loud on BOTH ends — the overlay
                        // closes on click, so the ack alone can vanish unseen.
                        AIPlayerMod.LOGGER.warn("[jack] refused {} -> {}: {}",
                                sp.getName().getString(), botName(bot), err);
                        sp.sendSystemMessage(net.minecraft.network.chat.Component
                                .literal("§c◈ jack-in refused: " + err));
                    }
                    PacketDistributor.sendToPlayer(sp, new OverlayPayloads.ControlAck(
                            err == null, err == null ? "jacked into " + botName(bot) : err));
                }));

        registrar.playToServer(
                OverlayPayloads.EjectRequest.TYPE,
                OverlayPayloads.EjectRequest.CODEC,
                (payload, context) -> context.enqueueWork(() -> {
                    if (!(context.player() instanceof ServerPlayer sp)) return;
                    String err = com.sigmastrain.aiplayermod.jack.JackInManager.eject(sp, false);
                    PacketDistributor.sendToPlayer(sp, new OverlayPayloads.ControlAck(
                            err == null, err == null ? "back in your body" : err));
                    PacketDistributor.sendToPlayer(sp, new OverlayPayloads.JackState(
                            false, "", 0, 0, 0, 0, ""));
                }));

        registrar.playToServer(
                OverlayPayloads.TalkSend.TYPE,
                OverlayPayloads.TalkSend.CODEC,
                (payload, context) -> context.enqueueWork(() -> {
                    if (!(context.player() instanceof ServerPlayer sp)) return;
                    // Stores are keyed by display name; the wire address may
                    // be a UUID — normalize at the seam.
                    BotPlayer bot = resolveBot(payload.bot());
                    if (bot == null) return;
                    com.sigmastrain.aiplayermod.telemetry.TalkStore.playerMessage(
                            botName(bot), sp.getName().getString(), payload.text());
                }));

        registrar.playToServer(
                OverlayPayloads.RequestTalk.TYPE,
                OverlayPayloads.RequestTalk.CODEC,
                (payload, context) -> context.enqueueWork(() -> {
                    if (!(context.player() instanceof ServerPlayer sp)) return;
                    BotPlayer bot = resolveBot(payload.bot());
                    if (bot == null) return;
                    PacketDistributor.sendToPlayer(sp, buildTalkHistory(botName(bot)));
                }));

        registrar.playToServer(
                OverlayPayloads.RequestThoughts.TYPE,
                OverlayPayloads.RequestThoughts.CODEC,
                (payload, context) -> context.enqueueWork(() -> {
                    if (!(context.player() instanceof ServerPlayer sp)) return;
                    BotPlayer bot = resolveBot(payload.bot());
                    if (bot == null) return;
                    String name = botName(bot);
                    List<OverlayPayloads.Thought> thoughts = new ArrayList<>();
                    for (var t : com.sigmastrain.aiplayermod.telemetry.TelemetryStore
                            .recent(name, 50)) {
                        thoughts.add(new OverlayPayloads.Thought(t.atMillis(), t.type(), t.text()));
                    }
                    PacketDistributor.sendToPlayer(sp,
                            new OverlayPayloads.ThoughtBatch(name, true, thoughts));
                }));

        registrar.playToServer(
                OverlayPayloads.SubmitOrder.TYPE,
                OverlayPayloads.SubmitOrder.CODEC,
                (payload, context) -> context.enqueueWork(() -> {
                    if (!(context.player() instanceof ServerPlayer sp)) return;
                    if ("fleet".equalsIgnoreCase(payload.bot())) {
                        // One order, many bots. Typed orders fan out verbatim
                        // under a shared fleet id; TEXT orders travel WHOLE to
                        // the agent (bot="fleet") for capability partitioning.
                        String fleetId = com.sigmastrain.aiplayermod.telemetry
                                .OrderStore.nextFleetId();
                        if ("TEXT".equals(payload.kind())) {
                            com.sigmastrain.aiplayermod.telemetry.OrderStore.submit(
                                    "fleet", sp.getName().getString(), "TEXT",
                                    payload.paramsJson(), fleetId);
                        } else {
                            for (var e : BotManager.getAllBots().entrySet()) {
                                if (e.getValue().getPlayer() == null
                                        || !e.getValue().isAlive()) continue;
                                com.sigmastrain.aiplayermod.telemetry.OrderStore.submit(
                                        e.getKey(), sp.getName().getString(),
                                        payload.kind(), payload.paramsJson(), fleetId);
                            }
                        }
                        AIPlayerMod.LOGGER.info("[overlay] {} fleet order {} ({})",
                                sp.getName().getString(), payload.kind(), fleetId);
                        PacketDistributor.sendToPlayer(sp, new OverlayPayloads.ControlAck(
                                true, "fleet order " + fleetId + " dispatched"));
                        return;
                    }
                    BotPlayer bot = resolveBot(payload.bot());
                    if (bot == null) {
                        PacketDistributor.sendToPlayer(sp, new OverlayPayloads.ControlAck(
                                false, "no bot " + payload.bot()));
                        return;
                    }
                    String name = botName(bot);
                    String id = com.sigmastrain.aiplayermod.telemetry.OrderStore.submit(
                            name, sp.getName().getString(), payload.kind(), payload.paramsJson());
                    AIPlayerMod.LOGGER.info("[overlay] {} orders {} for {} ({})",
                            sp.getName().getString(), payload.kind(), name,
                            id == null ? "QUEUE FULL" : id);
                    PacketDistributor.sendToPlayer(sp, new OverlayPayloads.ControlAck(
                            id != null,
                            id != null ? "order queued: " + payload.kind() + " #" + id
                                       : "order queue full — agent not draining?"));
                    PacketDistributor.sendToPlayer(sp, buildOrderStatus(name));
                }));

        registrar.playToServer(
                OverlayPayloads.VaultTransfer.TYPE,
                OverlayPayloads.VaultTransfer.CODEC,
                (payload, context) -> context.enqueueWork(() -> {
                    if (!(context.player() instanceof ServerPlayer sp)) return;
                    BotPlayer bot = resolveBot(payload.bot());
                    if (bot == null) return;
                    String msg = doVaultTransfer(sp, bot, payload.itemId(),
                            payload.count(), payload.dest());
                    PacketDistributor.sendToPlayer(sp,
                            new OverlayPayloads.ControlAck(!msg.startsWith("!"),
                                    msg.startsWith("!") ? msg.substring(1) : msg));
                    PacketDistributor.sendToPlayer(sp, buildVaultSnapshot(botName(bot), bot, ""));
                }));

        registrar.playToServer(
                OverlayPayloads.CuriosOp.TYPE,
                OverlayPayloads.CuriosOp.CODEC,
                (payload, context) -> context.enqueueWork(() -> {
                    if (!(context.player() instanceof ServerPlayer sp)) return;
                    BotPlayer bot = resolveBot(payload.bot());
                    if (bot == null || bot.getPlayer() == null) return;
                    String err = payload.equip()
                            ? com.sigmastrain.aiplayermod.compat.curios.CuriosCompat
                                    .equip(bot.getPlayer(), payload.itemId())
                            : com.sigmastrain.aiplayermod.compat.curios.CuriosCompat
                                    .unequip(bot.getPlayer(), payload.slotType(), payload.index());
                    PacketDistributor.sendToPlayer(sp, new OverlayPayloads.ControlAck(
                            err == null,
                            err == null
                                    ? (payload.equip() ? "equipped " + shortItem(payload.itemId())
                                                       : "took off " + payload.slotType())
                                    : err));
                    PacketDistributor.sendToPlayer(sp, buildVaultSnapshot(botName(bot), bot, ""));
                }));

        registrar.playToServer(
                OverlayPayloads.StandingOp.TYPE,
                OverlayPayloads.StandingOp.CODEC,
                (payload, context) -> context.enqueueWork(() -> {
                    if (!(context.player() instanceof ServerPlayer sp)) return;
                    BotPlayer bot = resolveBot(payload.bot());
                    if (bot == null) return;
                    String name = botName(bot);
                    switch (payload.op()) {
                        case "create" -> {
                            String id = com.sigmastrain.aiplayermod.telemetry.StandingStore
                                    .create(name, payload.watchType(), payload.item(),
                                            payload.threshold(), payload.comparator(),
                                            payload.actionKind(), payload.actionParams());
                            PacketDistributor.sendToPlayer(sp, new OverlayPayloads.ControlAck(
                                    id != null,
                                    id != null ? "standing order " + id + " watching"
                                               : "standing cap reached for " + name));
                        }
                        case "toggle" -> com.sigmastrain.aiplayermod.telemetry
                                .StandingStore.toggle(payload.id());
                        case "delete" -> {
                            com.sigmastrain.aiplayermod.telemetry.StandingStore
                                    .delete(payload.id());
                            PacketDistributor.sendToPlayer(sp, new OverlayPayloads.ControlAck(
                                    true, "standing order removed"));
                        }
                    }
                    PacketDistributor.sendToPlayer(sp, buildStandingList(name));
                }));

        // S2C payloads: lambda bodies so the client classes load only when a
        // packet actually arrives (never on a dedicated server).
        registrar.playToClient(
                OverlayPayloads.FleetSnapshot.TYPE,
                OverlayPayloads.FleetSnapshot.CODEC,
                (payload, context) -> context.enqueueWork(() ->
                        com.sigmastrain.aiplayermod.client.overlay.OverlayClientState.acceptSnapshot(payload)));

        registrar.playToClient(
                OverlayPayloads.SchemaPush.TYPE,
                OverlayPayloads.SchemaPush.CODEC,
                (payload, context) -> context.enqueueWork(() ->
                        com.sigmastrain.aiplayermod.client.overlay.OverlayClientState.acceptSchemas(payload)));

        registrar.playToClient(
                OverlayPayloads.StandingList.TYPE,
                OverlayPayloads.StandingList.CODEC,
                (payload, context) -> context.enqueueWork(() ->
                        com.sigmastrain.aiplayermod.client.overlay.OverlayClientState.acceptStanding(payload)));

        registrar.playToClient(
                OverlayPayloads.OrderStatusBatch.TYPE,
                OverlayPayloads.OrderStatusBatch.CODEC,
                (payload, context) -> context.enqueueWork(() ->
                        com.sigmastrain.aiplayermod.client.overlay.OverlayClientState.acceptOrders(payload)));

        registrar.playToClient(
                OverlayPayloads.ControlAck.TYPE,
                OverlayPayloads.ControlAck.CODEC,
                (payload, context) -> context.enqueueWork(() ->
                        com.sigmastrain.aiplayermod.client.overlay.OverlayClientState.acceptAck(payload)));

        registrar.playToClient(
                OverlayPayloads.VaultSnapshot.TYPE,
                OverlayPayloads.VaultSnapshot.CODEC,
                (payload, context) -> context.enqueueWork(() ->
                        com.sigmastrain.aiplayermod.client.overlay.OverlayClientState.acceptVault(payload)));

        registrar.playToClient(
                OverlayPayloads.ChannelQuoteReply.TYPE,
                OverlayPayloads.ChannelQuoteReply.CODEC,
                (payload, context) -> context.enqueueWork(() ->
                        com.sigmastrain.aiplayermod.client.overlay.OverlayClientState.acceptQuote(payload)));

        registrar.playToClient(
                OverlayPayloads.ThoughtBatch.TYPE,
                OverlayPayloads.ThoughtBatch.CODEC,
                (payload, context) -> context.enqueueWork(() ->
                        com.sigmastrain.aiplayermod.client.overlay.OverlayClientState.acceptThoughts(payload)));

        registrar.playToClient(
                OverlayPayloads.InboxState.TYPE,
                OverlayPayloads.InboxState.CODEC,
                (payload, context) -> context.enqueueWork(() ->
                        com.sigmastrain.aiplayermod.client.overlay.OverlayClientState.acceptInbox(payload)));

        registrar.playToClient(
                OverlayPayloads.TalkHistory.TYPE,
                OverlayPayloads.TalkHistory.CODEC,
                (payload, context) -> context.enqueueWork(() ->
                        com.sigmastrain.aiplayermod.client.overlay.OverlayClientState.acceptTalk(payload)));

        registrar.playToClient(
                OverlayPayloads.JackState.TYPE,
                OverlayPayloads.JackState.CODEC,
                (payload, context) -> context.enqueueWork(() ->
                        com.sigmastrain.aiplayermod.client.overlay.OverlayClientState.acceptJackState(payload)));
    }

    /**
     * The matter side of the fabric: move {@code count} of an item out of a
     * bot's pool (vault first, then carried) to the player or another bot's
     * vault. Returns an honest human line; "!"-prefixed = failure.
     */
    private static String doVaultTransfer(ServerPlayer sp, BotPlayer from,
                                          String itemId, int count, String dest) {
        // Gather from the vault, then top up from carried.
        List<net.minecraft.world.item.ItemStack> moving =
                new ArrayList<>(from.getVault().withdraw(itemId, count));
        int have = moving.stream().mapToInt(net.minecraft.world.item.ItemStack::getCount).sum();
        if (have < count) {
            var rl = net.minecraft.resources.ResourceLocation.tryParse(
                    itemId.contains(":") ? itemId : "minecraft:" + itemId);
            var inv = from.getPlayer().getInventory();
            for (int i = 0; i < inv.getContainerSize() && have < count; i++) {
                var s = inv.getItem(i);
                if (s.isEmpty() || rl == null || !net.minecraft.core.registries
                        .BuiltInRegistries.ITEM.getKey(s.getItem()).equals(rl)) continue;
                int take = Math.min(s.getCount(), count - have);
                var part = s.copy();
                part.setCount(take);
                moving.add(part);
                s.shrink(take);
                inv.setItem(i, s.isEmpty() ? net.minecraft.world.item.ItemStack.EMPTY : s);
                have += take;
            }
        }
        if (have == 0) return "!" + botName(from) + " has no " + shortItem(itemId);

        int delivered = 0;
        if ("player".equals(dest)) {
            for (var s : moving) {
                int want = s.getCount();
                if (sp.getInventory().add(s)) delivered += want;
                else {
                    delivered += want - s.getCount();
                    from.getVault().deposit(s); // leftovers go back where they're safe
                }
            }
            return delivered == have
                    ? "sent " + delivered + " " + shortItem(itemId) + " to you"
                    : "sent " + delivered + "/" + have + " — your inventory is full, rest re-vaulted";
        }
        if (dest.startsWith("bot:")) {
            BotPlayer to = resolveBot(dest.substring(4));
            if (to == null) {
                for (var s : moving) from.getVault().deposit(s);
                return "!no bot " + dest.substring(4) + " — nothing moved";
            }
            if (to == from) {
                for (var s : moving) from.getVault().deposit(s);
                return "!that is the same bot";
            }
            for (var s : moving) {
                delivered += s.getCount();
                to.getVault().deposit(s); // vaults absorb fully
            }
            return "sent " + delivered + " " + shortItem(itemId) + " → " + botName(to) + "'s vault";
        }
        for (var s : moving) from.getVault().deposit(s);
        return "!unknown destination " + dest;
    }

    /**
     * A completed bot action (conjure, etc.) changed this bot's holdings —
     * push a fresh vault snapshot to every subscriber so the overlay's
     * totals track reality instead of waiting for a manual re-query.
     */
    public static void onBotInventoryChanged(BotPlayer bot) {
        if (SUBSCRIBERS.isEmpty() || bot.getPlayer() == null) return;
        var server = bot.getPlayer().getServer();
        if (server == null) return;
        var snapshot = buildVaultSnapshot(botName(bot), bot, "");
        for (UUID id : SUBSCRIBERS) {
            ServerPlayer sp = server.getPlayerList().getPlayer(id);
            if (sp != null) {
                PacketDistributor.sendToPlayer(sp, snapshot);
            }
        }
    }

    private static OverlayPayloads.StandingList buildStandingList(String bot) {
        List<OverlayPayloads.StandingEntry> rows = new ArrayList<>();
        for (var st : com.sigmastrain.aiplayermod.telemetry.StandingStore.forBot(bot)) {
            rows.add(new OverlayPayloads.StandingEntry(st.id(), st.watchType(),
                    st.item(), st.threshold(), st.comparator(), st.actionKind(),
                    st.enabled(), st.lastFired(), st.lastResult(), st.reading()));
        }
        return new OverlayPayloads.StandingList(bot, rows);
    }

    private static OverlayPayloads.OrderStatusBatch buildOrderStatus(String bot) {
        List<OverlayPayloads.OrderLine> lines = new ArrayList<>();
        for (var s : com.sigmastrain.aiplayermod.telemetry.OrderStore.statuses(bot)) {
            lines.add(new OverlayPayloads.OrderLine(
                    s.id(), s.kind(), s.status(), s.detail(), s.fleetId(), s.atMillis()));
        }
        return new OverlayPayloads.OrderStatusBatch(bot, lines);
    }

    private static OverlayPayloads.TalkHistory buildTalkHistory(String bot) {
        List<OverlayPayloads.TalkLine> lines = new ArrayList<>();
        for (var l : com.sigmastrain.aiplayermod.telemetry.TalkStore.history(bot)) {
            lines.add(new OverlayPayloads.TalkLine(l.atMillis(), l.who(), l.text()));
        }
        return new OverlayPayloads.TalkHistory(bot, lines);
    }

    // ── Phase 2 assembly helpers (server thread) ─────────────────────────

    private static final int VAULT_PAGE = 100;

    private static OverlayPayloads.VaultSnapshot buildVaultSnapshot(String name, BotPlayer bot, String query) {
        String q = query == null ? "" : query.toLowerCase().trim();

        // The fabric: carried + vault + ME network through the worn terminal.
        // The full network is only walked when the player is actually
        // searching — iterating thousands of AEKeys per snapshot would be
        // rude; iterating them per typed query is fine.
        var access = com.sigmastrain.aiplayermod.compat.ae2.WirelessME.resolve(bot.getPlayer());
        Map<String, Long> meCounts = (!q.isEmpty() && access.online())
                ? com.sigmastrain.aiplayermod.compat.ae2.WirelessME.search(access, q, VAULT_PAGE)
                : Map.of();

        Map<String, OverlayPayloads.HoldingEntry> byItem = new java.util.LinkedHashMap<>();
        int total = 0;
        for (Map<String, Object> row : bot.getEffectiveInventory()) {
            String item = String.valueOf(row.getOrDefault("item", ""));
            String display = String.valueOf(row.getOrDefault("name", item));
            if (!q.isEmpty() && !item.toLowerCase().contains(q)
                    && !display.toLowerCase().contains(q)) continue;
            total++;
            if (byItem.size() < VAULT_PAGE) {
                byItem.put(item, new OverlayPayloads.HoldingEntry(
                        item, display,
                        asInt(row.get("carried")), asInt(row.get("vault")),
                        meCounts.getOrDefault(item, 0L)));
            }
        }
        // ME items the bot holds none of still belong in the search result.
        for (var e : meCounts.entrySet()) {
            if (byItem.size() >= VAULT_PAGE) break;
            byItem.computeIfAbsent(e.getKey(), k ->
                    new OverlayPayloads.HoldingEntry(k, shortItem(k), 0, 0, e.getValue()));
        }

        List<OverlayPayloads.HoldingEntry> entries = new ArrayList<>(byItem.values());
        // Big movers first — a vault query is usually "what do I have a lot of".
        entries.sort((a, b) -> Long.compare(
                b.carried() + b.vault() + b.me(), a.carried() + a.vault() + a.me()));

        // The Worn row: occupied curios slots only (48 mostly-empty slots
        // would be noise; the overlay offers equip against the carried list).
        List<OverlayPayloads.WornEntry> worn = new ArrayList<>();
        for (var w : com.sigmastrain.aiplayermod.compat.curios.CuriosCompat
                .list(bot.getPlayer())) {
            if (w.stack().isEmpty()) continue;
            worn.add(new OverlayPayloads.WornEntry(
                    w.slotType(), w.index(),
                    net.minecraft.core.registries.BuiltInRegistries.ITEM
                            .getKey(w.stack().getItem()).toString(),
                    w.stack().getHoverName().getString()));
        }

        return new OverlayPayloads.VaultSnapshot(name,
                bot.getPlayer().experienceLevel, Math.max(total, entries.size()),
                access.online() ? "online" : access.status(), entries, worn);
    }

    private static OverlayPayloads.ChannelQuoteReply buildQuote(String name, BotPlayer bot,
                                                                String itemId, int count) {
        int n = Math.max(1, Math.min(64, count));
        var rl = net.minecraft.resources.ResourceLocation.tryParse(
                itemId.contains(":") ? itemId : "minecraft:" + itemId);
        boolean known = rl != null
                && net.minecraft.core.registries.BuiltInRegistries.ITEM.containsKey(rl);
        String resolved = known ? rl.toString() : itemId;
        int cost = known
                ? com.sigmastrain.aiplayermod.actions.ConjureAction.costFor(resolved) * n
                : 0;
        int levels = bot.getPlayer().experienceLevel;

        var directive = bot.getBrain().peekDirective();
        boolean active = directive != null
                && directive.getStatus() == com.sigmastrain.aiplayermod.brain.DirectiveStatus.ACTIVE;

        return new OverlayPayloads.ChannelQuoteReply(
                name, resolved, n, known, cost, levels, known && levels >= cost,
                active ? directive.getId() : -1L,
                active ? directive.getType().name() : "");
    }

    private static OverlayPayloads.InboxState buildInboxState() {
        List<OverlayPayloads.InboxItem> items = new ArrayList<>();
        for (var e : com.sigmastrain.aiplayermod.telemetry.EscalationStore.pending()) {
            items.add(new OverlayPayloads.InboxItem(
                    e.id(), e.bot(), e.kind(), e.question(), e.options(),
                    e.directiveJson(), e.atMillis()));
        }
        return new OverlayPayloads.InboxState(items);
    }

    /** High-water mark per bot so each thought is forwarded exactly once. */
    private static final Map<String, Long> THOUGHT_FORWARDED = new ConcurrentHashMap<>();

    private static List<OverlayPayloads.ThoughtBatch> collectNewThoughts() {
        List<String> dirty = com.sigmastrain.aiplayermod.telemetry.TelemetryStore.drainDirty();
        if (dirty.isEmpty()) return List.of();
        List<OverlayPayloads.ThoughtBatch> out = new ArrayList<>();
        for (String bot : dirty) {
            long since = THOUGHT_FORWARDED.getOrDefault(bot, 0L);
            List<OverlayPayloads.Thought> fresh = new ArrayList<>();
            long newest = since;
            for (var t : com.sigmastrain.aiplayermod.telemetry.TelemetryStore.recent(bot, 50)) {
                if (t.atMillis() > since) {
                    fresh.add(new OverlayPayloads.Thought(t.atMillis(), t.type(), t.text()));
                    newest = Math.max(newest, t.atMillis());
                }
            }
            if (!fresh.isEmpty()) {
                THOUGHT_FORWARDED.put(bot, newest);
                out.add(new OverlayPayloads.ThoughtBatch(bot, false, fresh));
            }
        }
        return out;
    }

    private static int asInt(Object o) {
        return o instanceof Number num ? num.intValue() : 0;
    }

    private static String shortItem(String id) {
        return id.contains(":") ? id.substring(id.indexOf(':') + 1) : id;
    }

    // ── server broadcast loop (game bus) ─────────────────────────────────

    @EventBusSubscriber(modid = AIPlayerMod.MOD_ID)
    public static final class ServerEvents {

        @SubscribeEvent
        public static void onServerTick(ServerTickEvent.Post event) {
            if (SUBSCRIBERS.isEmpty()) return;
            if (++tickCounter % SNAPSHOT_INTERVAL_TICKS != 0) return;

            OverlayPayloads.FleetSnapshot snapshot = buildSnapshot();
            List<OverlayPayloads.ThoughtBatch> thoughtBatches = collectNewThoughts();

            // Talk transcripts: full resend per dirty bot (30 lines, tiny).
            List<OverlayPayloads.TalkHistory> talkUpdates = new ArrayList<>();
            for (String bot : com.sigmastrain.aiplayermod.telemetry.TalkStore.drainDirty()) {
                talkUpdates.add(buildTalkHistory(bot));
            }

            // Order statuses: same dirty-gating as talk.
            List<OverlayPayloads.OrderStatusBatch> orderUpdates = new ArrayList<>();
            for (String bot : com.sigmastrain.aiplayermod.telemetry.OrderStore.drainDirty()) {
                orderUpdates.add(buildOrderStatus(bot));
            }

            // Inbox: resend only when the store changed (version bump).
            long inboxVersion = com.sigmastrain.aiplayermod.telemetry.EscalationStore.version();
            OverlayPayloads.InboxState inbox = null;
            if (inboxVersion != lastInboxVersion) {
                lastInboxVersion = inboxVersion;
                inbox = buildInboxState();
            }

            // Standing orders: version-gated full resend per bot (tiny).
            long standingVersion = com.sigmastrain.aiplayermod.telemetry.StandingStore.version();
            List<OverlayPayloads.StandingList> standingUpdates = new ArrayList<>();
            if (standingVersion != lastStandingVersion) {
                lastStandingVersion = standingVersion;
                for (String b : BotManager.getAllBots().keySet()) {
                    standingUpdates.add(buildStandingList(b));
                }
            }

            // Schemas: version-gated, once per push per client.
            long schemaVersion = com.sigmastrain.aiplayermod.telemetry.SchemaStore.version();
            OverlayPayloads.SchemaPush schemas = schemaVersion > 0
                    ? new OverlayPayloads.SchemaPush(schemaVersion,
                            com.sigmastrain.aiplayermod.telemetry.SchemaStore.json())
                    : null;

            long now = System.currentTimeMillis();
            var playerList = event.getServer().getPlayerList();
            for (UUID id : SUBSCRIBERS) {
                ServerPlayer sp = playerList.getPlayer(id);
                if (sp == null) continue;

                // Bandwidth discipline: the fleet snapshot goes out only when
                // it CHANGED for this subscriber (records compare
                // structurally), with a keepalive floor so the client can
                // still distinguish "quiet" from "dead". The floor must sit
                // BELOW the client's 3 s "NO LINK" threshold — the first live
                // test shipped 5 s and the indicator flashed red on every
                // idle fleet. 2 s keeps the light green at 1/8th the packets.
                OverlayPayloads.FleetSnapshot last = LAST_SNAPSHOT.get(id);
                Long lastAt = LAST_SNAPSHOT_AT.get(id);
                if (!snapshot.equals(last) || lastAt == null || now - lastAt >= 2000) {
                    PacketDistributor.sendToPlayer(sp, snapshot);
                    LAST_SNAPSHOT.put(id, snapshot);
                    LAST_SNAPSHOT_AT.put(id, now);
                }
                for (var batch : thoughtBatches) {
                    PacketDistributor.sendToPlayer(sp, batch);
                }
                if (inbox != null) {
                    PacketDistributor.sendToPlayer(sp, inbox);
                }
                for (var talk : talkUpdates) {
                    PacketDistributor.sendToPlayer(sp, talk);
                }
                for (var orders : orderUpdates) {
                    PacketDistributor.sendToPlayer(sp, orders);
                }
                for (var st : standingUpdates) {
                    PacketDistributor.sendToPlayer(sp, st);
                }
                if (schemas != null
                        && SCHEMA_SENT.getOrDefault(id, 0L) != schemaVersion) {
                    PacketDistributor.sendToPlayer(sp, schemas);
                    SCHEMA_SENT.put(id, schemaVersion);
                }
            }
        }

        private static long lastInboxVersion = -1;
        private static long lastStandingVersion = -1;
        private static final Map<UUID, OverlayPayloads.FleetSnapshot> LAST_SNAPSHOT =
                new ConcurrentHashMap<>();
        private static final Map<UUID, Long> LAST_SNAPSHOT_AT = new ConcurrentHashMap<>();
        private static final Map<UUID, Long> SCHEMA_SENT = new ConcurrentHashMap<>();

        @SubscribeEvent
        public static void onLogout(PlayerEvent.PlayerLoggedOutEvent event) {
            UUID id = event.getEntity().getUUID();
            SUBSCRIBERS.remove(id);
            LAST_SNAPSHOT.remove(id);
            LAST_SNAPSHOT_AT.remove(id);
            SCHEMA_SENT.remove(id);
            LAST_JACK.remove(id);
            LAST_JACK_AT.remove(id);
            if (event.getEntity() instanceof ServerPlayer sp) {
                // Body restoration must happen before the entity is saved.
                com.sigmastrain.aiplayermod.jack.JackInManager.onPlayerLogout(sp);
            }
        }

        @SubscribeEvent
        public static void onHuskDeath(net.neoforged.neoforge.event.entity.living.LivingDeathEvent event) {
            if (!(event.getEntity() instanceof net.minecraft.world.entity.player.Player p)) return;
            var session = com.sigmastrain.aiplayermod.jack.JackInManager.sessionForHusk(p);
            if (session != null && p.getServer() != null) {
                com.sigmastrain.aiplayermod.jack.JackInManager.onHuskDeath(session, p.getServer());
            }
        }

        @SubscribeEvent
        public static void onServerStopping(net.neoforged.neoforge.event.server.ServerStoppingEvent event) {
            com.sigmastrain.aiplayermod.jack.JackInManager.ejectAll(event.getServer());
        }

        private static long jackTickCounter = 0;

        @SubscribeEvent
        public static void onJackTick(ServerTickEvent.Post event) {
            com.sigmastrain.aiplayermod.jack.JackInManager.tick(event.getServer());
            // The tether: jacked players get their body's state, overlay open
            // or not — the HUD line AND free-look depend on it. Its OWN
            // counter: the snapshot counter only advances while the overlay
            // is open, and riding it starved the tether whenever the panel
            // closed (live bug: "the bot takes my camera back until I open
            // the overlay"). Diff-gated with a 2 s keepalive, comfortably
            // inside the client's 5 s eject assumption.
            if (++jackTickCounter % SNAPSHOT_INTERVAL_TICKS != 0) return;
            long now = System.currentTimeMillis();
            for (var sp : event.getServer().getPlayerList().getPlayers()) {
                var st = com.sigmastrain.aiplayermod.jack.JackInManager.statusFor(sp);
                if (Boolean.TRUE.equals(st.get("active"))) {
                    var state = new OverlayPayloads.JackState(
                            true, String.valueOf(st.get("bot")),
                            ((Number) st.get("husk_health")).floatValue(),
                            ((Number) st.get("x")).intValue(),
                            ((Number) st.get("y")).intValue(),
                            ((Number) st.get("z")).intValue(),
                            String.valueOf(st.get("dimension")));
                    var id = sp.getUUID();
                    Long lastAt = LAST_JACK_AT.get(id);
                    if (!state.equals(LAST_JACK.get(id)) || lastAt == null
                            || now - lastAt >= 2000) {
                        PacketDistributor.sendToPlayer(sp, state);
                        LAST_JACK.put(id, state);
                        LAST_JACK_AT.put(id, now);
                    }
                } else {
                    LAST_JACK.remove(sp.getUUID());
                    LAST_JACK_AT.remove(sp.getUUID());
                }
            }
        }

        private static final Map<UUID, OverlayPayloads.JackState> LAST_JACK =
                new ConcurrentHashMap<>();
        private static final Map<UUID, Long> LAST_JACK_AT = new ConcurrentHashMap<>();
    }

    // ── snapshot assembly (server thread only) ───────────────────────────

    private static OverlayPayloads.FleetSnapshot buildSnapshot() {
        List<OverlayPayloads.BotEntry> entries = new ArrayList<>();
        for (Map.Entry<String, BotPlayer> e : BotManager.getAllBots().entrySet()) {
            BotPlayer bot = e.getValue();
            ServerPlayer p = bot.getPlayer();
            if (p == null) continue;

            var brain = bot.getBrain();
            var directive = brain.peekDirective();

            int kills = 0, deaths = 0;
            try {
                kills = p.getStats().getValue(Stats.CUSTOM.get(Stats.MOB_KILLS));
                deaths = p.getStats().getValue(Stats.CUSTOM.get(Stats.DEATHS));
            } catch (Exception ignored) {
            }

            entries.add(new OverlayPayloads.BotEntry(
                    p.getUUID().toString(),
                    e.getKey(),
                    p.getHealth(),
                    p.getFoodData().getFoodLevel(),
                    p.experienceLevel,
                    p.level().dimension().location().toString(),
                    p.getBlockX(), p.getBlockY(), p.getBlockZ(),
                    directive != null ? directive.getId() : -1L,
                    directive != null ? directive.getType().name() : "",
                    directive != null ? directive.getStatus().name() : "",
                    directive != null && directive.getTarget() != null ? directive.getTarget() : "",
                    brain.currentPhase(),
                    brain.stateLine(),
                    kills,
                    deaths,
                    com.sigmastrain.aiplayermod.bot.AnchorManager.isAnchored(e.getKey())));
        }
        return new OverlayPayloads.FleetSnapshot(
                com.sigmastrain.aiplayermod.telemetry.AgentPresence.silentSeconds(),
                entries);
    }
}
