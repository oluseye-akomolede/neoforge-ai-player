package com.sigmastrain.aiplayermod.compat;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import net.minecraft.core.BlockPos;
import net.minecraft.core.GlobalPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.neoforged.fml.ModList;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * v7 Phase 0 probes — answers, at runtime, the three questions the overlay
 * design is betting on. Reflective because this mod takes no compile-time
 * dependency on optional mods (see build.gradle).
 *
 * <p>Diagnostics, not a feature. Delete once the answers are recorded in
 * openspec/changes/v7-player-in-the-network.
 *
 * <p>What is being asked:
 * <ol>
 *   <li><b>Curios on a fake player.</b> Slots are granted through data-driven
 *       modifiers applied on player join; bots never run a real login, so they
 *       may have an inventory with zero slots — or none at all.</li>
 *   <li><b>ME grid from an item, server-side.</b> AE2 exposes
 *       {@code WirelessTerminalItem.getLinkedGrid(stack, level, err)}, which
 *       would give bots real network storage instead of the 16-block interface
 *       buffer scan they use today.</li>
 * </ol>
 */
public final class SpikeDiagnostics {

    private SpikeDiagnostics() {}

    // ── probe 1: does Curios attach to a fake player? ────────────────────

    public static Map<String, Object> probeCurios(ServerPlayer bot) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("probe", "curios");
        if (!ModList.get().isLoaded("curios")) {
            out.put("mod_loaded", false);
            return out;
        }
        out.put("mod_loaded", true);
        try {
            Class<?> api = Class.forName("top.theillusivec4.curios.api.CuriosApi");

            // What the data pack says a player SHOULD have.
            try {
                Method playerSlots = api.getMethod("getPlayerSlots",
                        net.minecraft.world.entity.player.Player.class);
                Object slots = playerSlots.invoke(null, bot);
                if (slots instanceof Map<?, ?> m) {
                    out.put("expected_player_slots", new ArrayList<>(
                            m.keySet().stream().map(String::valueOf).toList()));
                }
            } catch (Throwable t) {
                out.put("expected_player_slots_error", t.toString());
            }

            // What this entity actually got.
            Method getInv = api.getMethod("getCuriosInventory",
                    net.minecraft.world.entity.LivingEntity.class);
            Object opt = getInv.invoke(null, bot);
            boolean present = opt instanceof Optional<?> o && o.isPresent();
            out.put("inventory_present", present);
            if (!present) {
                out.put("verdict", "NO curios inventory on this fake player");
                return out;
            }

            Object handler = ((Optional<?>) opt).get();
            out.put("handler_class", handler.getClass().getName());

            int total = (int) handler.getClass().getMethod("getSlots").invoke(handler);
            out.put("total_slots", total);

            Object curios = handler.getClass().getMethod("getCurios").invoke(handler);
            List<String> ids = new ArrayList<>();
            if (curios instanceof Map<?, ?> m) {
                for (Object k : m.keySet()) ids.add(String.valueOf(k));
            }
            out.put("slot_ids", ids);

            // The real question: can something be put in one?
            Object equipped = handler.getClass().getMethod("getEquippedCurios").invoke(handler);
            if (equipped != null) {
                int size = (int) equipped.getClass().getMethod("getSlots").invoke(equipped);
                out.put("equipped_handler_slots", size);
                out.put("insert_test", tryInsert(equipped, size));
            }

            out.put("verdict", total > 0
                    ? "curios ATTACHED with " + total + " slot(s)"
                    : "inventory exists but ZERO slots — modifiers not applied to fake player");
        } catch (Throwable t) {
            out.put("error", t.getClass().getSimpleName() + ": " + t.getMessage());
        }
        return out;
    }

    /** Round-trip a marker item through the first writable curio slot. */
    private static String tryInsert(Object equippedHandler, int size) {
        if (size <= 0) return "no slots to test";
        try {
            ItemStack probe = new ItemStack(net.minecraft.world.item.Items.DIAMOND);
            Method insert = equippedHandler.getClass().getMethod(
                    "insertItem", int.class, ItemStack.class, boolean.class);
            for (int i = 0; i < size; i++) {
                Object leftover = insert.invoke(equippedHandler, i, probe.copy(), true); // simulate
                if (leftover instanceof ItemStack ls && ls.isEmpty()) {
                    return "slot " + i + " would accept an item (simulated)";
                }
            }
            return "no slot accepted a plain item — slots may be type-restricted (normal)";
        } catch (Throwable t) {
            return "insert probe failed: " + t;
        }
    }

    // ── probe 2: real ME grid access from a carried terminal ─────────────

    public static Map<String, Object> probeMEWireless(ServerPlayer bot) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("probe", "me_wireless");
        if (!ModList.get().isLoaded("ae2")) {
            out.put("mod_loaded", false);
            return out;
        }
        out.put("mod_loaded", true);
        try {
            Class<?> wtClass = Class.forName("appeng.items.tools.powered.WirelessTerminalItem");

            // Any wireless terminal the bot is carrying, curios included.
            ItemStack found = ItemStack.EMPTY;
            String where = null;
            var inv = bot.getInventory();
            for (int i = 0; i < inv.getContainerSize() && found.isEmpty(); i++) {
                ItemStack s = inv.getItem(i);
                if (!s.isEmpty() && wtClass.isInstance(s.getItem())) {
                    found = s;
                    where = "inventory slot " + i;
                }
            }
            if (found.isEmpty()) {
                ItemStack fromCurio = firstCurioMatching(bot, wtClass);
                if (!fromCurio.isEmpty()) {
                    found = fromCurio;
                    where = "curio slot";
                }
            }

            out.put("terminals_in_registry", countTerminalItems(wtClass));
            if (found.isEmpty()) {
                out.put("terminal_carried", false);
                out.put("verdict", "bot carries no wireless terminal — give or conjure one to test the grid path");
                return out;
            }
            out.put("terminal_carried", true);
            out.put("terminal_item", BuiltInRegistries.ITEM.getKey(found.getItem()).toString());
            out.put("found_in", where);

            Object item = found.getItem();

            // Linked to an access point?
            try {
                Method linkedPos = wtClass.getMethod("getLinkedPosition", ItemStack.class);
                Object gp = linkedPos.invoke(item, found);
                out.put("linked", gp != null);
                if (gp instanceof GlobalPos g) {
                    out.put("linked_to", g.dimension().location() + " " + g.pos().toShortString());
                }
            } catch (Throwable t) {
                out.put("linked_position_error", t.toString());
            }

            // Power — a terminal with no charge cannot serve a request.
            try {
                Method hasPower = wtClass.getMethod("hasPower",
                        net.minecraft.world.entity.player.Player.class, double.class, ItemStack.class);
                out.put("has_power", hasPower.invoke(item, bot, 1.0d, found));
            } catch (Throwable t) {
                out.put("has_power_error", t.toString());
            }

            // THE question: a grid, server-side, with no GUI and no menu host.
            List<String> gridErrors = new ArrayList<>();
            Method getLinkedGrid = wtClass.getMethod("getLinkedGrid",
                    ItemStack.class, net.minecraft.world.level.Level.class, java.util.function.Consumer.class);
            Object grid = getLinkedGrid.invoke(item, found, bot.level(),
                    (java.util.function.Consumer<net.minecraft.network.chat.Component>)
                            c -> gridErrors.add(c.getString()));
            out.put("grid_resolved", grid != null);
            if (!gridErrors.isEmpty()) out.put("grid_errors", gridErrors);

            if (grid != null) {
                out.put("grid_class", grid.getClass().getName());
                Object storageService = grid.getClass().getMethod("getStorageService").invoke(grid);
                Object meStorage = storageService.getClass().getMethod("getInventory").invoke(storageService);
                out.put("me_storage", meStorage != null);
                if (meStorage != null) {
                    out.put("me_storage_class", meStorage.getClass().getName());
                    out.put("me_description", String.valueOf(
                            meStorage.getClass().getMethod("getDescription").invoke(meStorage)));
                }
                out.put("verdict", "REAL grid access from a carried terminal — no GUI, no proximity");
            } else {
                out.put("verdict", "terminal present but no grid: " + gridErrors);
            }
        } catch (Throwable t) {
            out.put("error", t.getClass().getSimpleName() + ": " + t.getMessage());
        }
        return out;
    }

    private static ItemStack firstCurioMatching(ServerPlayer bot, Class<?> itemClass) {
        try {
            Class<?> api = Class.forName("top.theillusivec4.curios.api.CuriosApi");
            Object opt = api.getMethod("getCuriosInventory",
                    net.minecraft.world.entity.LivingEntity.class).invoke(null, bot);
            if (!(opt instanceof Optional<?> o) || o.isEmpty()) return ItemStack.EMPTY;
            Object handler = o.get();
            Object equipped = handler.getClass().getMethod("getEquippedCurios").invoke(handler);
            int size = (int) equipped.getClass().getMethod("getSlots").invoke(equipped);
            Method getStack = equipped.getClass().getMethod("getStackInSlot", int.class);
            for (int i = 0; i < size; i++) {
                Object s = getStack.invoke(equipped, i);
                if (s instanceof ItemStack st && !st.isEmpty() && itemClass.isInstance(st.getItem())) {
                    return st;
                }
            }
        } catch (Throwable ignored) {
        }
        return ItemStack.EMPTY;
    }

    private static List<String> countTerminalItems(Class<?> wtClass) {
        List<String> ids = new ArrayList<>();
        for (ResourceLocation id : BuiltInRegistries.ITEM.keySet()) {
            Item it = BuiltInRegistries.ITEM.get(id);
            if (wtClass.isInstance(it)) ids.add(id.toString());
        }
        return ids;
    }

    // ── probe 2b: link + charge the carried terminal, then re-resolve ────

    /**
     * The write half of the ME spike: link the bot's terminal to an access
     * point and charge it, both through public AE2 API, no GUI. Proves a
     * LINK_TERMINAL bot action is possible — a player never has to touch the
     * terminal for a bot to join the network.
     */
    public static Map<String, Object> probeLink(ServerPlayer bot, BlockPos accessPoint) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("probe", "link");
        if (!ModList.get().isLoaded("ae2")) {
            out.put("mod_loaded", false);
            return out;
        }
        try {
            Class<?> wtClass = Class.forName("appeng.items.tools.powered.WirelessTerminalItem");

            ItemStack terminal = ItemStack.EMPTY;
            var inv = bot.getInventory();
            for (int i = 0; i < inv.getContainerSize() && terminal.isEmpty(); i++) {
                ItemStack s = inv.getItem(i);
                if (!s.isEmpty() && wtClass.isInstance(s.getItem())) terminal = s;
            }
            if (terminal.isEmpty()) {
                out.put("error", "no wireless terminal carried");
                return out;
            }
            out.put("terminal", BuiltInRegistries.ITEM.getKey(terminal.getItem()).toString());

            // Link — the same handler AE2 registers for right-clicking an AP.
            Object handler = wtClass.getField("LINKABLE_HANDLER").get(null);
            Class<?> handlerIface = Class.forName("appeng.api.features.IGridLinkableHandler");
            boolean canLink = (boolean) handlerIface.getMethod("canLink", ItemStack.class)
                    .invoke(handler, terminal);
            out.put("can_link", canLink);
            if (canLink) {
                // The access point lives in the OVERWORLD regardless of where
                // the bot is standing — linking with the bot's own dimension
                // stranded End-side bots on a GlobalPos that points at
                // nothing ("Linked network cannot be found").
                GlobalPos gp = GlobalPos.of(net.minecraft.world.level.Level.OVERWORLD, accessPoint);
                handlerIface.getMethod("link", ItemStack.class, GlobalPos.class)
                        .invoke(handler, terminal, gp);
                out.put("linked_to", gp.dimension().location() + " " + gp.pos().toShortString());
            }

            // Charge — terminals ship empty; an empty battery hides the answer.
            Class<?> powerIface = Class.forName("appeng.api.implementations.items.IAEItemPowerStorage");
            Class<?> actionable = Class.forName("appeng.api.config.Actionable");
            Object modulate = actionable.getField("MODULATE").get(null);
            double max = (double) powerIface.getMethod("getAEMaxPower", ItemStack.class)
                    .invoke(terminal.getItem(), terminal);
            powerIface.getMethod("injectAEPower", ItemStack.class, double.class, actionable)
                    .invoke(terminal.getItem(), terminal, max, modulate);
            out.put("charged_to", powerIface.getMethod("getAECurrentPower", ItemStack.class)
                    .invoke(terminal.getItem(), terminal));

            // The proof: does the grid resolve now?
            out.put("recheck", probeMEWireless(bot));
        } catch (Throwable t) {
            out.put("error", t.getClass().getSimpleName() + ": " + t.getMessage());
        }
        return out;
    }

    // ── probe 3: is there an access point to link against? ───────────────

    /**
     * Nearest Wireless Access Point, so a terminal can be linked without the
     * player standing there. String-matched like the existing AE2Compat scan;
     * fine for a probe, not for production.
     */
    public static Map<String, Object> probeAccessPoint(ServerPlayer bot, int radius) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("probe", "access_point");
        ServerLevel level = bot.serverLevel();
        BlockPos origin = bot.blockPosition();
        int r = Math.max(1, Math.min(64, radius));
        BlockPos best = null;
        double bestDist = Double.MAX_VALUE;
        for (int dx = -r; dx <= r; dx++) {
            for (int dy = -r; dy <= r; dy++) {
                for (int dz = -r; dz <= r; dz++) {
                    BlockPos p = origin.offset(dx, dy, dz);
                    var key = BuiltInRegistries.BLOCK.getKey(level.getBlockState(p).getBlock());
                    if (key != null && key.toString().contains("wireless_access_point")) {
                        double d = origin.distSqr(p);
                        if (d < bestDist) { bestDist = d; best = p.immutable(); }
                    }
                }
            }
        }
        out.put("searched_radius", r);
        out.put("found", best != null);
        if (best != null) {
            out.put("pos", List.of(best.getX(), best.getY(), best.getZ()));
            out.put("dimension", level.dimension().location().toString());
            out.put("distance", (int) Math.sqrt(bestDist));
        }
        return out;
    }

    public static Map<String, Object> runAll(ServerPlayer bot) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("bot", bot.getName().getString());
        out.put("dimension", bot.level().dimension().location().toString());
        out.put("curios", probeCurios(bot));
        out.put("me_wireless", probeMEWireless(bot));
        out.put("access_point", probeAccessPoint(bot, 24));
        AIPlayerMod.LOGGER.info("[v7 spike] diagnostics for {}: {}", bot.getName().getString(), out);
        return out;
    }
}
