package com.sigmastrain.aiplayermod.network;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import net.minecraft.network.RegistryFriendlyByteBuf;
import net.minecraft.network.codec.StreamCodec;
import net.minecraft.network.protocol.common.custom.CustomPacketPayload;
import net.minecraft.resources.ResourceLocation;

import java.util.ArrayList;
import java.util.List;

/**
 * v7 overlay wire format — the mod's first client↔server channel.
 *
 * <p>Everything before this went client → vanilla container sync or agent →
 * HTTP. The overlay needs its own lane: the player's client subscribes, the
 * server streams fleet snapshots at ~4 Hz, and control packets (interrupt,
 * directives in later phases) flow back.
 *
 * <p>Codecs are written manually against {@link RegistryFriendlyByteBuf}
 * rather than composed — the snapshot nests a list of per-bot entries, and a
 * flat hand-rolled codec is easier to keep honest than a composite tower.
 */
public final class OverlayPayloads {

    private OverlayPayloads() {}

    private static ResourceLocation id(String path) {
        return ResourceLocation.fromNamespaceAndPath(AIPlayerMod.MOD_ID, path);
    }

    // ── C2S: subscribe / unsubscribe to fleet snapshots ──────────────────

    public record OverlaySubscribe(boolean on) implements CustomPacketPayload {
        public static final Type<OverlaySubscribe> TYPE = new Type<>(id("overlay_subscribe"));
        public static final StreamCodec<RegistryFriendlyByteBuf, OverlaySubscribe> CODEC =
                StreamCodec.of(
                        (buf, p) -> buf.writeBoolean(p.on),
                        buf -> new OverlaySubscribe(buf.readBoolean()));

        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    // ── C2S: interrupt a directive ───────────────────────────────────────

    /**
     * Id-scoped on purpose: the client names the directive it is looking at,
     * and the server's race guard (finding D3) ignores the cancel if a newer
     * directive is already active. A bare "stop whatever you're doing" from a
     * stale screen must not kill fresh work.
     */
    public record InterruptDirective(String bot, long directiveId) implements CustomPacketPayload {
        public static final Type<InterruptDirective> TYPE = new Type<>(id("overlay_interrupt"));
        public static final StreamCodec<RegistryFriendlyByteBuf, InterruptDirective> CODEC =
                StreamCodec.of(
                        (buf, p) -> { buf.writeUtf(p.bot); buf.writeVarLong(p.directiveId); },
                        buf -> new InterruptDirective(buf.readUtf(), buf.readVarLong()));

        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    // ── S2C: fleet snapshot ──────────────────────────────────────────────

    /** One bot's row in the fleet view. Lean by design — detail comes later phases.
     *  {@code id} is the bot's stable UUID: the hive-seam address. Handlers
     *  resolve by id first, display name second; nothing in the schema
     *  assumes a single owner. */
    public record BotEntry(
            String id,               // bot UUID string — the address
            String name,             // display only
            float health,
            int food,
            int xpLevel,
            String dimension,
            int x, int y, int z,
            long directiveId,        // -1 = none
            String directiveType,    // "" = none
            String directiveStatus,  // ACTIVE / COMPLETED / FAILED / CANCELLED / ""
            String target,
            String phase,
            String stateLine,
            int kills,
            int deaths,
            boolean anchored
    ) {
        static void write(RegistryFriendlyByteBuf buf, BotEntry e) {
            buf.writeUtf(e.id);
            buf.writeUtf(e.name);
            buf.writeFloat(e.health);
            buf.writeVarInt(e.food);
            buf.writeVarInt(e.xpLevel);
            buf.writeUtf(e.dimension);
            buf.writeVarInt(e.x);
            buf.writeVarInt(e.y);
            buf.writeVarInt(e.z);
            buf.writeVarLong(e.directiveId + 1); // VarLong dislikes -1; shift by one
            buf.writeUtf(e.directiveType);
            buf.writeUtf(e.directiveStatus);
            buf.writeUtf(e.target);
            buf.writeUtf(e.phase);
            buf.writeUtf(e.stateLine);
            buf.writeVarInt(e.kills);
            buf.writeVarInt(e.deaths);
            buf.writeBoolean(e.anchored);
        }

        static BotEntry read(RegistryFriendlyByteBuf buf) {
            return new BotEntry(
                    buf.readUtf(),
                    buf.readUtf(),
                    buf.readFloat(),
                    buf.readVarInt(),
                    buf.readVarInt(),
                    buf.readUtf(),
                    buf.readVarInt(),
                    buf.readVarInt(),
                    buf.readVarInt(),
                    buf.readVarLong() - 1,
                    buf.readUtf(),
                    buf.readUtf(),
                    buf.readUtf(),
                    buf.readUtf(),
                    buf.readUtf(),
                    buf.readVarInt(),
                    buf.readVarInt(),
                    buf.readBoolean());
        }
    }

    /** {@code agentSilentSeconds}: 0 = agent alive; otherwise how long it
     *  has been silent (quantized server-side so idle fleets stay quiet). */
    public record FleetSnapshot(int agentSilentSeconds, List<BotEntry> bots)
            implements CustomPacketPayload {
        public static final Type<FleetSnapshot> TYPE = new Type<>(id("overlay_fleet"));
        public static final StreamCodec<RegistryFriendlyByteBuf, FleetSnapshot> CODEC =
                StreamCodec.of(
                        (buf, p) -> {
                            buf.writeVarInt(p.agentSilentSeconds);
                            buf.writeVarInt(p.bots.size());
                            for (BotEntry e : p.bots) BotEntry.write(buf, e);
                        },
                        buf -> {
                            int silent = buf.readVarInt();
                            int n = buf.readVarInt();
                            List<BotEntry> list = new ArrayList<>(n);
                            for (int i = 0; i < n; i++) list.add(BotEntry.read(buf));
                            return new FleetSnapshot(silent, list);
                        });

        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    // ── C2S: vault + channel (Phase 2) ───────────────────────────────────

    public record RequestVault(String bot, String query) implements CustomPacketPayload {
        public static final Type<RequestVault> TYPE = new Type<>(id("overlay_vault_req"));
        public static final StreamCodec<RegistryFriendlyByteBuf, RequestVault> CODEC =
                StreamCodec.of(
                        (buf, p) -> { buf.writeUtf(p.bot); buf.writeUtf(p.query); },
                        buf -> new RequestVault(buf.readUtf(), buf.readUtf()));

        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    /** Move items between carried and vault. {@code toVault} true = stow. */
    public record VaultOp(String bot, String itemId, int count, boolean toVault)
            implements CustomPacketPayload {
        public static final Type<VaultOp> TYPE = new Type<>(id("overlay_vault_op"));
        public static final StreamCodec<RegistryFriendlyByteBuf, VaultOp> CODEC =
                StreamCodec.of(
                        (buf, p) -> {
                            buf.writeUtf(p.bot);
                            buf.writeUtf(p.itemId);
                            buf.writeVarInt(p.count);
                            buf.writeBoolean(p.toVault);
                        },
                        buf -> new VaultOp(buf.readUtf(), buf.readUtf(), buf.readVarInt(), buf.readBoolean()));

        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    public record ChannelQuote(String bot, String itemId, int count) implements CustomPacketPayload {
        public static final Type<ChannelQuote> TYPE = new Type<>(id("overlay_channel_quote"));
        public static final StreamCodec<RegistryFriendlyByteBuf, ChannelQuote> CODEC =
                StreamCodec.of(
                        (buf, p) -> { buf.writeUtf(p.bot); buf.writeUtf(p.itemId); buf.writeVarInt(p.count); },
                        buf -> new ChannelQuote(buf.readUtf(), buf.readUtf(), buf.readVarInt()));

        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    /** Commit a channel. {@code interrupt} = cancel the active directive first. */
    public record ChannelExecute(String bot, String itemId, int count, boolean interrupt,
                                 long expectDirectiveId) implements CustomPacketPayload {
        public static final Type<ChannelExecute> TYPE = new Type<>(id("overlay_channel_exec"));
        public static final StreamCodec<RegistryFriendlyByteBuf, ChannelExecute> CODEC =
                StreamCodec.of(
                        (buf, p) -> {
                            buf.writeUtf(p.bot);
                            buf.writeUtf(p.itemId);
                            buf.writeVarInt(p.count);
                            buf.writeBoolean(p.interrupt);
                            buf.writeVarLong(p.expectDirectiveId + 1);
                        },
                        buf -> new ChannelExecute(buf.readUtf(), buf.readUtf(), buf.readVarInt(),
                                buf.readBoolean(), buf.readVarLong() - 1));

        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    public record OpenEquipment(String bot) implements CustomPacketPayload {
        public static final Type<OpenEquipment> TYPE = new Type<>(id("overlay_open_equipment"));
        public static final StreamCodec<RegistryFriendlyByteBuf, OpenEquipment> CODEC =
                StreamCodec.of(
                        (buf, p) -> buf.writeUtf(p.bot),
                        buf -> new OpenEquipment(buf.readUtf()));

        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    // ── S2C: vault snapshot + channel quote (Phase 2) ────────────────────

    /** {@code me} is a long: networks hold millions of an item. */
    public record HoldingEntry(String item, String name, int carried, int vault, long me) {
        static void write(RegistryFriendlyByteBuf buf, HoldingEntry e) {
            buf.writeUtf(e.item);
            buf.writeUtf(e.name);
            buf.writeVarInt(e.carried);
            buf.writeVarInt(e.vault);
            buf.writeVarLong(e.me);
        }

        static HoldingEntry read(RegistryFriendlyByteBuf buf) {
            return new HoldingEntry(buf.readUtf(), buf.readUtf(),
                    buf.readVarInt(), buf.readVarInt(), buf.readVarLong());
        }
    }

    /** One occupied (or notable empty) curios slot on the bot. */
    public record WornEntry(String slotType, int index, String item, String name) {
        static void write(RegistryFriendlyByteBuf buf, WornEntry e) {
            buf.writeUtf(e.slotType);
            buf.writeVarInt(e.index);
            buf.writeUtf(e.item);
            buf.writeUtf(e.name);
        }

        static WornEntry read(RegistryFriendlyByteBuf buf) {
            return new WornEntry(buf.readUtf(), buf.readVarInt(), buf.readUtf(), buf.readUtf());
        }
    }

    public record VaultSnapshot(String bot, int xpLevel, int totalEntries,
                                String meStatus,
                                List<HoldingEntry> entries,
                                List<WornEntry> worn) implements CustomPacketPayload {
        public static final Type<VaultSnapshot> TYPE = new Type<>(id("overlay_vault"));
        public static final StreamCodec<RegistryFriendlyByteBuf, VaultSnapshot> CODEC =
                StreamCodec.of(
                        (buf, p) -> {
                            buf.writeUtf(p.bot);
                            buf.writeVarInt(p.xpLevel);
                            buf.writeVarInt(p.totalEntries);
                            buf.writeUtf(p.meStatus);
                            buf.writeVarInt(p.entries.size());
                            for (HoldingEntry e : p.entries) HoldingEntry.write(buf, e);
                            buf.writeVarInt(p.worn.size());
                            for (WornEntry e : p.worn) WornEntry.write(buf, e);
                        },
                        buf -> {
                            String bot = buf.readUtf();
                            int xp = buf.readVarInt();
                            int total = buf.readVarInt();
                            String me = buf.readUtf();
                            int n = buf.readVarInt();
                            List<HoldingEntry> list = new ArrayList<>(n);
                            for (int i = 0; i < n; i++) list.add(HoldingEntry.read(buf));
                            int w = buf.readVarInt();
                            List<WornEntry> worn = new ArrayList<>(w);
                            for (int i = 0; i < w; i++) worn.add(WornEntry.read(buf));
                            return new VaultSnapshot(bot, xp, total, me, list, worn);
                        });

        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    /** Move items between the bot and the ME network. {@code toME} true = push. */
    public record MEOp(String bot, String itemId, int count, boolean toME)
            implements CustomPacketPayload {
        public static final Type<MEOp> TYPE = new Type<>(id("overlay_me_op"));
        public static final StreamCodec<RegistryFriendlyByteBuf, MEOp> CODEC =
                StreamCodec.of(
                        (buf, p) -> {
                            buf.writeUtf(p.bot);
                            buf.writeUtf(p.itemId);
                            buf.writeVarInt(p.count);
                            buf.writeBoolean(p.toME);
                        },
                        buf -> new MEOp(buf.readUtf(), buf.readUtf(), buf.readVarInt(), buf.readBoolean()));

        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    public record ChannelQuoteReply(String bot, String item, int count, boolean known,
                                    int costLevels, int botLevels, boolean affordable,
                                    long activeDirectiveId, String activeDirective)
            implements CustomPacketPayload {
        public static final Type<ChannelQuoteReply> TYPE = new Type<>(id("overlay_channel_reply"));
        public static final StreamCodec<RegistryFriendlyByteBuf, ChannelQuoteReply> CODEC =
                StreamCodec.of(
                        (buf, p) -> {
                            buf.writeUtf(p.bot);
                            buf.writeUtf(p.item);
                            buf.writeVarInt(p.count);
                            buf.writeBoolean(p.known);
                            buf.writeVarInt(p.costLevels);
                            buf.writeVarInt(p.botLevels);
                            buf.writeBoolean(p.affordable);
                            buf.writeVarLong(p.activeDirectiveId + 1);
                            buf.writeUtf(p.activeDirective);
                        },
                        buf -> new ChannelQuoteReply(buf.readUtf(), buf.readUtf(), buf.readVarInt(),
                                buf.readBoolean(), buf.readVarInt(), buf.readVarInt(), buf.readBoolean(),
                                buf.readVarLong() - 1, buf.readUtf()));

        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    // ── thought stream (Phase 3) ─────────────────────────────────────────

    public record RequestThoughts(String bot) implements CustomPacketPayload {
        public static final Type<RequestThoughts> TYPE = new Type<>(id("overlay_thoughts_req"));
        public static final StreamCodec<RegistryFriendlyByteBuf, RequestThoughts> CODEC =
                StreamCodec.of(
                        (buf, p) -> buf.writeUtf(p.bot),
                        buf -> new RequestThoughts(buf.readUtf()));

        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    public record Thought(long atMillis, String type, String text) {
        static void write(RegistryFriendlyByteBuf buf, Thought t) {
            buf.writeVarLong(t.atMillis);
            buf.writeUtf(t.type);
            buf.writeUtf(t.text);
        }

        static Thought read(RegistryFriendlyByteBuf buf) {
            return new Thought(buf.readVarLong(), buf.readUtf(), buf.readUtf());
        }
    }

    /** {@code full} true = replace the client's list; false = append. */
    public record ThoughtBatch(String bot, boolean full, List<Thought> thoughts)
            implements CustomPacketPayload {
        public static final Type<ThoughtBatch> TYPE = new Type<>(id("overlay_thoughts"));
        public static final StreamCodec<RegistryFriendlyByteBuf, ThoughtBatch> CODEC =
                StreamCodec.of(
                        (buf, p) -> {
                            buf.writeUtf(p.bot);
                            buf.writeBoolean(p.full);
                            buf.writeVarInt(p.thoughts.size());
                            for (Thought t : p.thoughts) Thought.write(buf, t);
                        },
                        buf -> {
                            String bot = buf.readUtf();
                            boolean full = buf.readBoolean();
                            int n = buf.readVarInt();
                            List<Thought> list = new ArrayList<>(n);
                            for (int i = 0; i < n; i++) list.add(Thought.read(buf));
                            return new ThoughtBatch(bot, full, list);
                        });

        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    // ── L4 inbox (Phase 3b) ──────────────────────────────────────────────

    public record InboxItem(String id, String bot, String kind, String question,
                            List<String> options, String directiveJson, long atMillis) {
        static void write(RegistryFriendlyByteBuf buf, InboxItem e) {
            buf.writeUtf(e.id);
            buf.writeUtf(e.bot);
            buf.writeUtf(e.kind);
            buf.writeUtf(e.question);
            buf.writeVarInt(e.options.size());
            for (String o : e.options) buf.writeUtf(o);
            buf.writeUtf(e.directiveJson, 4096);
            buf.writeVarLong(e.atMillis);
        }

        static InboxItem read(RegistryFriendlyByteBuf buf) {
            String id = buf.readUtf();
            String bot = buf.readUtf();
            String kind = buf.readUtf();
            String question = buf.readUtf();
            int n = buf.readVarInt();
            List<String> options = new ArrayList<>(n);
            for (int i = 0; i < n; i++) options.add(buf.readUtf());
            return new InboxItem(id, bot, kind, question, options,
                    buf.readUtf(4096), buf.readVarLong());
        }
    }

    /** Full pending list — small (a handful of open questions at most). */
    public record InboxState(List<InboxItem> items) implements CustomPacketPayload {
        public static final Type<InboxState> TYPE = new Type<>(id("overlay_inbox"));
        public static final StreamCodec<RegistryFriendlyByteBuf, InboxState> CODEC =
                StreamCodec.of(
                        (buf, p) -> {
                            buf.writeVarInt(p.items.size());
                            for (InboxItem e : p.items) InboxItem.write(buf, e);
                        },
                        buf -> {
                            int n = buf.readVarInt();
                            List<InboxItem> list = new ArrayList<>(n);
                            for (int i = 0; i < n; i++) list.add(InboxItem.read(buf));
                            return new InboxState(list);
                        });

        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    /** Player's ruling. action ∈ choose | answer | escalate_l5 | cancel. */
    public record InboxRespond(String id, String action, String text)
            implements CustomPacketPayload {
        // Qualified: the record's `id` component shadows the outer helper.
        public static final Type<InboxRespond> TYPE =
                new Type<>(OverlayPayloads.id("overlay_inbox_respond"));
        public static final StreamCodec<RegistryFriendlyByteBuf, InboxRespond> CODEC =
                StreamCodec.of(
                        (buf, p) -> { buf.writeUtf(p.id); buf.writeUtf(p.action); buf.writeUtf(p.text); },
                        buf -> new InboxRespond(buf.readUtf(), buf.readUtf(), buf.readUtf()));

        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    // ── Talk (Phase 4) ───────────────────────────────────────────────────

    public record TalkSend(String bot, String text) implements CustomPacketPayload {
        public static final Type<TalkSend> TYPE = new Type<>(id("overlay_talk_send"));
        public static final StreamCodec<RegistryFriendlyByteBuf, TalkSend> CODEC =
                StreamCodec.of(
                        (buf, p) -> { buf.writeUtf(p.bot); buf.writeUtf(p.text); },
                        buf -> new TalkSend(buf.readUtf(), buf.readUtf()));

        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    public record RequestTalk(String bot) implements CustomPacketPayload {
        public static final Type<RequestTalk> TYPE = new Type<>(id("overlay_talk_req"));
        public static final StreamCodec<RegistryFriendlyByteBuf, RequestTalk> CODEC =
                StreamCodec.of(
                        (buf, p) -> buf.writeUtf(p.bot),
                        buf -> new RequestTalk(buf.readUtf()));

        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    public record TalkLine(long atMillis, String who, String text) {
        static void write(RegistryFriendlyByteBuf buf, TalkLine t) {
            buf.writeVarLong(t.atMillis);
            buf.writeUtf(t.who);
            buf.writeUtf(t.text);
        }

        static TalkLine read(RegistryFriendlyByteBuf buf) {
            return new TalkLine(buf.readVarLong(), buf.readUtf(), buf.readUtf());
        }
    }

    /** Full transcript for one bot — short (30 lines), so always full. */
    public record TalkHistory(String bot, List<TalkLine> lines) implements CustomPacketPayload {
        public static final Type<TalkHistory> TYPE = new Type<>(id("overlay_talk"));
        public static final StreamCodec<RegistryFriendlyByteBuf, TalkHistory> CODEC =
                StreamCodec.of(
                        (buf, p) -> {
                            buf.writeUtf(p.bot);
                            buf.writeVarInt(p.lines.size());
                            for (TalkLine t : p.lines) TalkLine.write(buf, t);
                        },
                        buf -> {
                            String bot = buf.readUtf();
                            int n = buf.readVarInt();
                            List<TalkLine> list = new ArrayList<>(n);
                            for (int i = 0; i < n; i++) list.add(TalkLine.read(buf));
                            return new TalkHistory(bot, list);
                        });

        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    // ── Jack in (Phase 5) ────────────────────────────────────────────────

    public record JackIn(String bot) implements CustomPacketPayload {
        public static final Type<JackIn> TYPE = new Type<>(id("overlay_jack_in"));
        public static final StreamCodec<RegistryFriendlyByteBuf, JackIn> CODEC =
                StreamCodec.of(
                        (buf, p) -> buf.writeUtf(p.bot),
                        buf -> new JackIn(buf.readUtf()));

        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    public record EjectRequest() implements CustomPacketPayload {
        public static final Type<EjectRequest> TYPE = new Type<>(id("overlay_eject"));
        public static final EjectRequest INSTANCE = new EjectRequest();
        public static final StreamCodec<RegistryFriendlyByteBuf, EjectRequest> CODEC =
                StreamCodec.unit(INSTANCE);

        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    /** The traveler's tether: where the body is and how it is doing. */
    public record JackState(boolean active, String bot, float huskHealth,
                            int x, int y, int z, String dimension)
            implements CustomPacketPayload {
        public static final Type<JackState> TYPE = new Type<>(id("overlay_jack_state"));
        public static final StreamCodec<RegistryFriendlyByteBuf, JackState> CODEC =
                StreamCodec.of(
                        (buf, p) -> {
                            buf.writeBoolean(p.active);
                            buf.writeUtf(p.bot);
                            buf.writeFloat(p.huskHealth);
                            buf.writeVarInt(p.x);
                            buf.writeVarInt(p.y);
                            buf.writeVarInt(p.z);
                            buf.writeUtf(p.dimension);
                        },
                        buf -> new JackState(buf.readBoolean(), buf.readUtf(), buf.readFloat(),
                                buf.readVarInt(), buf.readVarInt(), buf.readVarInt(), buf.readUtf()));

        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    // ── Phase 7: command surface ─────────────────────────────────────────

    /** Directive schemas (agent-owned vocabulary) relayed to the builder. */
    public record SchemaPush(long version, String json) implements CustomPacketPayload {
        public static final Type<SchemaPush> TYPE = new Type<>(id("overlay_schemas"));
        public static final StreamCodec<RegistryFriendlyByteBuf, SchemaPush> CODEC =
                StreamCodec.of(
                        (buf, p) -> { buf.writeVarLong(p.version); buf.writeUtf(p.json, 65535); },
                        buf -> new SchemaPush(buf.readVarLong(), buf.readUtf(65535)));

        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    /** Player order from the directive builder. {@code paramsJson} is a flat
     *  JSON object of field values keyed by the schema's param names. */
    public record SubmitOrder(String bot, String kind, String paramsJson)
            implements CustomPacketPayload {
        public static final Type<SubmitOrder> TYPE = new Type<>(id("overlay_order_submit"));
        public static final StreamCodec<RegistryFriendlyByteBuf, SubmitOrder> CODEC =
                StreamCodec.of(
                        (buf, p) -> {
                            buf.writeUtf(p.bot);
                            buf.writeUtf(p.kind);
                            buf.writeUtf(p.paramsJson, 8192);
                        },
                        buf -> new SubmitOrder(buf.readUtf(), buf.readUtf(), buf.readUtf(8192)));

        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    public record OrderLine(String id, String kind, String status, String detail,
                            String fleetId, long atMillis) {
        static void write(RegistryFriendlyByteBuf buf, OrderLine e) {
            buf.writeUtf(e.id);
            buf.writeUtf(e.kind);
            buf.writeUtf(e.status);
            buf.writeUtf(e.detail);
            buf.writeUtf(e.fleetId);
            buf.writeVarLong(e.atMillis);
        }

        static OrderLine read(RegistryFriendlyByteBuf buf) {
            return new OrderLine(buf.readUtf(), buf.readUtf(), buf.readUtf(),
                    buf.readUtf(), buf.readUtf(), buf.readVarLong());
        }
    }

    /** Recent order statuses for one bot (QUEUED/RUNNING/COMPLETED/FAILED). */
    public record OrderStatusBatch(String bot, List<OrderLine> orders)
            implements CustomPacketPayload {
        public static final Type<OrderStatusBatch> TYPE = new Type<>(id("overlay_order_status"));
        public static final StreamCodec<RegistryFriendlyByteBuf, OrderStatusBatch> CODEC =
                StreamCodec.of(
                        (buf, p) -> {
                            buf.writeUtf(p.bot);
                            buf.writeVarInt(p.orders.size());
                            for (OrderLine e : p.orders) OrderLine.write(buf, e);
                        },
                        buf -> {
                            String bot = buf.readUtf();
                            int n = buf.readVarInt();
                            List<OrderLine> list = new ArrayList<>(n);
                            for (int i = 0; i < n; i++) list.add(OrderLine.read(buf));
                            return new OrderStatusBatch(bot, list);
                        });

        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    /** Move items out of a bot's pool (vault first, then carried) to a
     *  destination: {@code "player"} or {@code "bot:<idOrName>"}. */
    public record VaultTransfer(String bot, String itemId, int count, String dest)
            implements CustomPacketPayload {
        public static final Type<VaultTransfer> TYPE = new Type<>(id("overlay_vault_transfer"));
        public static final StreamCodec<RegistryFriendlyByteBuf, VaultTransfer> CODEC =
                StreamCodec.of(
                        (buf, p) -> {
                            buf.writeUtf(p.bot);
                            buf.writeUtf(p.itemId);
                            buf.writeVarInt(p.count);
                            buf.writeUtf(p.dest);
                        },
                        buf -> new VaultTransfer(buf.readUtf(), buf.readUtf(),
                                buf.readVarInt(), buf.readUtf()));

        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    /** Equip an item into curios ({@code equip} true, itemId set) or take a
     *  worn item off ({@code equip} false, slotType+index set). */
    public record CuriosOp(String bot, boolean equip, String itemId,
                           String slotType, int index) implements CustomPacketPayload {
        public static final Type<CuriosOp> TYPE = new Type<>(id("overlay_curios_op"));
        public static final StreamCodec<RegistryFriendlyByteBuf, CuriosOp> CODEC =
                StreamCodec.of(
                        (buf, p) -> {
                            buf.writeUtf(p.bot);
                            buf.writeBoolean(p.equip);
                            buf.writeUtf(p.itemId);
                            buf.writeUtf(p.slotType);
                            buf.writeVarInt(p.index);
                        },
                        buf -> new CuriosOp(buf.readUtf(), buf.readBoolean(),
                                buf.readUtf(), buf.readUtf(), buf.readVarInt()));

        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    /** One standing order row for the overlay. */
    public record StandingEntry(String id, String watchType, String item,
                                long threshold, String comparator,
                                String actionKind, boolean enabled,
                                long lastFired, String lastResult, long reading) {
        static void write(RegistryFriendlyByteBuf buf, StandingEntry e) {
            buf.writeUtf(e.id);
            buf.writeUtf(e.watchType);
            buf.writeUtf(e.item);
            buf.writeVarLong(e.threshold);
            buf.writeUtf(e.comparator);
            buf.writeUtf(e.actionKind);
            buf.writeBoolean(e.enabled);
            buf.writeVarLong(e.lastFired);
            buf.writeUtf(e.lastResult);
            buf.writeVarLong(e.reading + 2); // -1 sentinel survives VarLong
        }

        static StandingEntry read(RegistryFriendlyByteBuf buf) {
            return new StandingEntry(buf.readUtf(), buf.readUtf(), buf.readUtf(),
                    buf.readVarLong(), buf.readUtf(), buf.readUtf(),
                    buf.readBoolean(), buf.readVarLong(), buf.readUtf(),
                    buf.readVarLong() - 2);
        }
    }

    public record StandingList(String bot, List<StandingEntry> orders)
            implements CustomPacketPayload {
        public static final Type<StandingList> TYPE = new Type<>(id("overlay_standing"));
        public static final StreamCodec<RegistryFriendlyByteBuf, StandingList> CODEC =
                StreamCodec.of(
                        (buf, p) -> {
                            buf.writeUtf(p.bot);
                            buf.writeVarInt(p.orders.size());
                            for (StandingEntry e : p.orders) StandingEntry.write(buf, e);
                        },
                        buf -> {
                            String bot = buf.readUtf();
                            int n = buf.readVarInt();
                            List<StandingEntry> list = new ArrayList<>(n);
                            for (int i = 0; i < n; i++) list.add(StandingEntry.read(buf));
                            return new StandingList(bot, list);
                        });

        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    /** op ∈ create | toggle | delete. Create uses the remaining fields. */
    public record StandingOp(String bot, String op, String id, String watchType,
                             String item, long threshold, String comparator,
                             String actionKind, String actionParams)
            implements CustomPacketPayload {
        public static final Type<StandingOp> TYPE =
                new Type<>(OverlayPayloads.id("overlay_standing_op"));
        public static final StreamCodec<RegistryFriendlyByteBuf, StandingOp> CODEC =
                StreamCodec.of(
                        (buf, p) -> {
                            buf.writeUtf(p.bot);
                            buf.writeUtf(p.op);
                            buf.writeUtf(p.id);
                            buf.writeUtf(p.watchType);
                            buf.writeUtf(p.item);
                            buf.writeVarLong(p.threshold);
                            buf.writeUtf(p.comparator);
                            buf.writeUtf(p.actionKind);
                            buf.writeUtf(p.actionParams, 2048);
                        },
                        buf -> new StandingOp(buf.readUtf(), buf.readUtf(), buf.readUtf(),
                                buf.readUtf(), buf.readUtf(), buf.readVarLong(),
                                buf.readUtf(), buf.readUtf(), buf.readUtf(2048)));

        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    // ── S2C: ack / error for a control packet ────────────────────────────

    public record ControlAck(boolean ok, String message) implements CustomPacketPayload {
        public static final Type<ControlAck> TYPE = new Type<>(id("overlay_ack"));
        public static final StreamCodec<RegistryFriendlyByteBuf, ControlAck> CODEC =
                StreamCodec.of(
                        (buf, p) -> { buf.writeBoolean(p.ok); buf.writeUtf(p.message); },
                        buf -> new ControlAck(buf.readBoolean(), buf.readUtf()));

        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }
}
