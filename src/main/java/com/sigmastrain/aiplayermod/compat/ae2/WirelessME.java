package com.sigmastrain.aiplayermod.compat.ae2;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.item.ItemStack;
import net.neoforged.fml.ModList;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;

/**
 * Real ME network access from a terminal the bot carries.
 *
 * <p>The v7 spike proved the whole chain live: {@code getLinkedGrid} resolves
 * the stored access point with <b>no distance or dimension check</b> — range
 * is enforced only by the GUI menu host, which this path never constructs.
 * That makes range OUR policy: power is honored (a dead terminal is a dead
 * terminal), range is a config knob defaulting to unlimited, because "bot in
 * the Nether reaches home storage" is the point of the feature.
 *
 * <p>Everything is reflection — this mod takes no compile dependency on AE2
 * (frozen modpack; see build.gradle). Every failure resolves to an honest
 * {@link Access#status} rather than an exception: "no terminal", "unpowered",
 * "unlinked", "grid offline" are states the caller shows the player, not
 * errors it swallows.
 */
public final class WirelessME {

    private WirelessME() {}

    /** Range policy: unlimited unless the operator says otherwise. */
    private static final boolean HONOR_RANGE =
            Boolean.parseBoolean(System.getProperty("aiplayermod.me.honor_range",
                    System.getenv().getOrDefault("AIPLAYER_ME_HONOR_RANGE", "false")));

    /** AE energy drained per item moved — mirrors wireless terminal costs. */
    private static final double POWER_PER_OPERATION = 5.0;

    public record Access(Object meStorage, Object actionSource, ItemStack terminal,
                         Object terminalItem, ServerPlayer holder, String status) {
        public boolean online() { return meStorage != null; }
    }

    public static boolean isAvailable() {
        return ModList.get().isLoaded("ae2");
    }

    // ── resolution ───────────────────────────────────────────────────────

    /**
     * Find a linked, powered wireless terminal on the bot (curios included)
     * and open the grid behind it.
     */
    public static Access resolve(ServerPlayer bot) {
        if (!isAvailable()) return offline("ae2 not loaded");
        try {
            Class<?> wtClass = Class.forName("appeng.items.tools.powered.WirelessTerminalItem");

            ItemStack terminal = findTerminal(bot, wtClass);
            if (terminal.isEmpty()) return offline("no wireless terminal carried");
            Object item = terminal.getItem();

            Method hasPower = wtClass.getMethod("hasPower",
                    net.minecraft.world.entity.player.Player.class, double.class, ItemStack.class);
            if (!(boolean) hasPower.invoke(item, bot, POWER_PER_OPERATION, terminal)) {
                return offline("terminal unpowered");
            }

            List<String> errs = new ArrayList<>();
            Method getLinkedGrid = wtClass.getMethod("getLinkedGrid",
                    ItemStack.class, net.minecraft.world.level.Level.class,
                    java.util.function.Consumer.class);
            Object grid = getLinkedGrid.invoke(item, terminal, bot.level(),
                    (java.util.function.Consumer<net.minecraft.network.chat.Component>)
                            c -> errs.add(c.getString()));
            if (grid == null) {
                return offline(errs.isEmpty() ? "terminal unlinked" : errs.get(0));
            }

            if (HONOR_RANGE && !inRange(grid, bot)) {
                return offline("out of access point range");
            }

            Object storageService = grid.getClass().getMethod("getStorageService").invoke(grid);
            Object meStorage = storageService.getClass().getMethod("getInventory")
                    .invoke(storageService);
            if (meStorage == null) return offline("grid has no storage");

            Class<?> sourceClass = Class.forName("appeng.api.networking.security.IActionSource");
            Object source = sourceClass.getMethod("ofPlayer",
                    net.minecraft.world.entity.player.Player.class).invoke(null, bot);

            return new Access(meStorage, source, terminal, item, bot, "online");
        } catch (Throwable t) {
            AIPlayerMod.LOGGER.warn("[me] resolve failed: {}", t.toString());
            return offline("me error: " + t.getClass().getSimpleName());
        }
    }

    private static Access offline(String status) {
        return new Access(null, null, ItemStack.EMPTY, null, null, status);
    }

    private static ItemStack findTerminal(ServerPlayer bot, Class<?> wtClass) {
        var inv = bot.getInventory();
        for (int i = 0; i < inv.getContainerSize(); i++) {
            ItemStack s = inv.getItem(i);
            if (!s.isEmpty() && wtClass.isInstance(s.getItem())) return s;
        }
        // Curios — spike 1 proved fake players wear them.
        try {
            Class<?> api = Class.forName("top.theillusivec4.curios.api.CuriosApi");
            Object opt = api.getMethod("getCuriosInventory",
                    net.minecraft.world.entity.LivingEntity.class).invoke(null, bot);
            if (opt instanceof Optional<?> o && o.isPresent()) {
                Object handler = o.get();
                Object equipped = handler.getClass().getMethod("getEquippedCurios").invoke(handler);
                int size = (int) equipped.getClass().getMethod("getSlots").invoke(equipped);
                Method getStack = equipped.getClass().getMethod("getStackInSlot", int.class);
                for (int i = 0; i < size; i++) {
                    Object s = getStack.invoke(equipped, i);
                    if (s instanceof ItemStack st && !st.isEmpty()
                            && wtClass.isInstance(st.getItem())) {
                        return st;
                    }
                }
            }
        } catch (Throwable ignored) {
        }
        return ItemStack.EMPTY;
    }

    private static boolean inRange(Object grid, ServerPlayer bot) {
        // Optional policy. Mirrors WirelessTerminalMenuHost: any access point
        // on the grid, in this dimension, within its advertised range.
        try {
            Class<?> apClass = Class.forName(
                    "appeng.api.implementations.blockentities.IWirelessAccessPoint");
            java.util.List<Object> aps = new java.util.ArrayList<>();
            var classes = (java.util.Set<?>) grid.getClass()
                    .getMethod("getMachineClasses").invoke(grid);
            for (Object mc : classes) {
                if (mc instanceof Class<?> c && apClass.isAssignableFrom(c)) {
                    aps.addAll((java.util.Set<?>) grid.getClass()
                            .getMethod("getMachines", Class.class).invoke(grid, c));
                }
            }
            for (Object ap : aps) {
                Object loc = apClass.getMethod("getLocation").invoke(ap);
                double range = (double) apClass.getMethod("getRange").invoke(ap);
                Object level = loc.getClass().getMethod("getLevel").invoke(loc);
                if (level != bot.level()) continue;
                Object pos = loc.getClass().getMethod("getPos").invoke(loc);
                double d = bot.blockPosition().distSqr((net.minecraft.core.BlockPos) pos);
                if (d <= range * range) return true;
            }
            return false;
        } catch (Throwable t) {
            return true; // policy check failed — don't block the operation on it
        }
    }

    // ── operations ───────────────────────────────────────────────────────

    /** Insert a stack into the network. Returns how many were accepted. */
    public static int insert(Access access, ItemStack stack) {
        if (!access.online() || stack.isEmpty()) return 0;
        try {
            Object key = aeItemKey(stack);
            if (key == null) return 0;
            long accepted = storageOp(access, "insert", key, stack.getCount());
            if (accepted > 0) drainPower(access, accepted);
            return (int) accepted;
        } catch (Throwable t) {
            AIPlayerMod.LOGGER.warn("[me] insert failed: {}", t.toString());
            return 0;
        }
    }

    /** Extract up to {@code count} of an item id. Returns the pulled stacks. */
    public static List<ItemStack> extract(Access access, String itemId, int count) {
        List<ItemStack> out = new ArrayList<>();
        if (!access.online() || count <= 0) return out;
        try {
            var rl = ResourceLocation.tryParse(itemId.contains(":") ? itemId : "minecraft:" + itemId);
            if (rl == null || !BuiltInRegistries.ITEM.containsKey(rl)) return out;
            ItemStack proto = new ItemStack(BuiltInRegistries.ITEM.get(rl));
            Object key = aeItemKey(proto);
            if (key == null) return out;
            long pulled = storageOp(access, "extract", key, count);
            if (pulled > 0) {
                drainPower(access, pulled);
                int max = proto.getMaxStackSize();
                long left = pulled;
                while (left > 0) {
                    int n = (int) Math.min(left, max);
                    ItemStack s = proto.copy();
                    s.setCount(n);
                    out.add(s);
                    left -= n;
                }
            }
            return out;
        } catch (Throwable t) {
            AIPlayerMod.LOGGER.warn("[me] extract failed: {}", t.toString());
            return out;
        }
    }

    // ── network provisioning (v8 opening move) ──────────────────────────

    /**
     * Every ME network on the server that has at least one wireless access
     * point — the population behind the "pick a network" dropdown. On this
     * single-owner server every network is the player's; the owner filter
     * becomes real when the hive mod multiplies operators.
     */
    public static java.util.List<Map<String, Object>> listNetworks() {
        java.util.List<Map<String, Object>> out = new java.util.ArrayList<>();
        if (!isAvailable()) return out;
        try {
            Class<?> tickHandler = Class.forName("appeng.hooks.ticking.TickHandler");
            Object instance = tickHandler.getMethod("instance").invoke(null);
            Iterable<?> grids = (Iterable<?>) tickHandler.getMethod("getGridList").invoke(instance);
            Class<?> apClass = Class.forName(
                    "appeng.api.implementations.blockentities.IWirelessAccessPoint");
            for (Object grid : grids) {
                // AE2's machine index is keyed by CONCRETE class — asking it
                // for an interface returns nothing (live bug: 4,826-node grid
                // "not found"). Walk the class index and match assignables.
                java.util.Set<?> machines = java.util.Set.of();
                var classes = (java.util.Set<?>) grid.getClass()
                        .getMethod("getMachineClasses").invoke(grid);
                for (Object mc : classes) {
                    if (mc instanceof Class<?> c && apClass.isAssignableFrom(c)) {
                        machines = (java.util.Set<?>) grid.getClass()
                                .getMethod("getMachines", Class.class).invoke(grid, c);
                        if (!machines.isEmpty()) break;
                    }
                }
                if (machines.isEmpty()) continue;
                Object ap = machines.iterator().next();
                Object loc = apClass.getMethod("getLocation").invoke(ap);
                Object level = loc.getClass().getMethod("getLevel").invoke(loc);
                Object pos = loc.getClass().getMethod("getPos").invoke(loc);
                var bp = (net.minecraft.core.BlockPos) pos;
                String dim = level instanceof net.minecraft.world.level.Level l
                        ? l.dimension().location().toString() : "?";
                int nodes = 0;
                try {
                    var nodeIter = (Iterable<?>) grid.getClass().getMethod("getNodes").invoke(grid);
                    for (Object ignored : nodeIter) nodes++;
                } catch (Throwable ignored) {
                }
                Map<String, Object> row = new LinkedHashMap<>();
                row.put("dimension", dim);
                row.put("x", bp.getX());
                row.put("y", bp.getY());
                row.put("z", bp.getZ());
                row.put("nodes", nodes);
                row.put("access_points", machines.size());
                out.add(row);
            }
        } catch (Throwable t) {
            AIPlayerMod.LOGGER.warn("[me] network listing failed: {}", t.toString());
        }
        return out;
    }

    /**
     * Give this bot a working wireless terminal on the chosen network:
     * find one it carries (curios included) or conjure one at XP cost,
     * link it to the access point, charge it, wear it. Every failure is a
     * plain sentence. This is the fleet-onboarding ritual, promoted from
     * the hand-run spike into a directive bots can be ordered through.
     */
    public static String provision(ServerPlayer bot, String dimension,
                                   net.minecraft.core.BlockPos apPos) {
        if (!isAvailable()) return "ae2 not loaded";
        try {
            Class<?> wtClass = Class.forName("appeng.items.tools.powered.WirelessTerminalItem");
            ItemStack terminal = findTerminal(bot, wtClass);
            if (terminal.isEmpty()) {
                // Conjure one — XP is the fleet's universal currency.
                int cost = com.sigmastrain.aiplayermod.actions.ConjureAction
                        .costFor("ae2:wireless_terminal");
                if (bot.experienceLevel < cost) {
                    return "no terminal carried and not enough XP to conjure one (need "
                            + cost + " levels, has " + bot.experienceLevel + ")";
                }
                bot.giveExperienceLevels(-cost);
                var item = net.minecraft.core.registries.BuiltInRegistries.ITEM.get(
                        net.minecraft.resources.ResourceLocation.parse("ae2:wireless_terminal"));
                terminal = new ItemStack(item);
                if (!bot.getInventory().add(terminal)) {
                    bot.getInventory().setItem(0, new ItemStack(item)); // hotbar 0 — never drop it
                }
                // Inventory.add DRAINS the passed stack — link the slot-held
                // one, not our emptied local (live bug: four bots burned XP
                // then "cannot be linked" on a count-0 ghost).
                terminal = findTerminal(bot, wtClass);
                if (terminal.isEmpty()) return "conjured terminal vanished";
            }

            var dimKey = net.minecraft.resources.ResourceKey.create(
                    net.minecraft.core.registries.Registries.DIMENSION,
                    net.minecraft.resources.ResourceLocation.parse(dimension));
            var gp = net.minecraft.core.GlobalPos.of(dimKey, apPos);
            Object handler = wtClass.getField("LINKABLE_HANDLER").get(null);
            Class<?> handlerIface = Class.forName("appeng.api.features.IGridLinkableHandler");
            if (!(boolean) handlerIface.getMethod("canLink", ItemStack.class)
                    .invoke(handler, terminal)) {
                return "this terminal cannot be linked";
            }
            handlerIface.getMethod("link", ItemStack.class, net.minecraft.core.GlobalPos.class)
                    .invoke(handler, terminal, gp);

            // Charge to full — wireless range/power policy is ours (v7).
            Class<?> actionable = Class.forName("appeng.api.config.Actionable");
            Object modulate = actionable.getEnumConstants()[0];
            Class<?> powerIface = Class.forName("appeng.api.implementations.items.IAEItemPowerStorage");
            if (powerIface.isInstance(terminal.getItem())) {
                powerIface.getMethod("injectAEPower", ItemStack.class, double.class, actionable)
                        .invoke(terminal.getItem(), terminal, 1_600_000.0, modulate);
            }

            // Worn beats carried — but a full curio rack is not a failure.
            com.sigmastrain.aiplayermod.compat.curios.CuriosCompat
                    .equip(bot, "ae2:wireless_terminal");

            Access check = resolve(bot);
            return check.online() ? null
                    : "linked but network unreachable: " + check.status();
        } catch (Throwable t) {
            AIPlayerMod.LOGGER.warn("[me] provision failed", t);
            return "provision error: " + t.getClass().getSimpleName();
        }
    }

    /** Network contents matching a query — for the overlay's fabric view. */
    public static Map<String, Long> search(Access access, String query, int limit) {
        Map<String, Long> out = new LinkedHashMap<>();
        if (!access.online()) return out;
        String q = query == null ? "" : query.toLowerCase(Locale.ROOT).trim();
        try {
            // Reflect only through PUBLIC api types. The counter's own
            // iterator hands back entries of a private fastutil class —
            // getMethod on it succeeds but invoke() dies on accessibility,
            // which is why search came back empty against the real network
            // while push/pull (public-type paths) worked.
            Class<?> meStorageCls = Class.forName("appeng.api.storage.MEStorage");
            Class<?> counterCls = Class.forName("appeng.api.stacks.KeyCounter");
            Class<?> aeKeyCls = Class.forName("appeng.api.stacks.AEKey");
            Class<?> itemKey = Class.forName("appeng.api.stacks.AEItemKey");
            Object counter = meStorageCls.getMethod("getAvailableStacks")
                    .invoke(access.meStorage());
            Iterable<?> keys = (Iterable<?>) counterCls.getMethod("keySet").invoke(counter);
            var getAmount = counterCls.getMethod("get", aeKeyCls);
            for (Object key : keys) {
                if (out.size() >= limit) break;
                if (!itemKey.isInstance(key)) continue;
                long amount = (long) getAmount.invoke(counter, key);
                if (amount <= 0) continue;
                ItemStack stack = (ItemStack) itemKey.getMethod("toStack").invoke(key);
                String id = BuiltInRegistries.ITEM.getKey(stack.getItem()).toString();
                if (!q.isEmpty() && !id.toLowerCase(Locale.ROOT).contains(q)
                        && !stack.getHoverName().getString().toLowerCase(Locale.ROOT).contains(q)) {
                    continue;
                }
                out.merge(id, amount, Long::sum);
            }
        } catch (Throwable t) {
            AIPlayerMod.LOGGER.warn("[me] search failed: {}", t.toString());
        }
        return out;
    }

    /** Count of one item id in the network. */
    public static long count(Access access, String itemId) {
        Map<String, Long> res = search(access, itemId, 256);
        String want = itemId.contains(":") ? itemId : "minecraft:" + itemId;
        return res.getOrDefault(want, 0L);
    }

    /**
     * Grid introspection for "why is my fabric offline": node count, machine
     * classes, stored energy. An AP alone on an unpowered one-node grid and a
     * healthy network are both "online" to {@link #resolve} — this tells them
     * apart.
     */
    public static Map<String, Object> diagnostics(ServerPlayer bot) {
        Map<String, Object> out = new LinkedHashMap<>();
        Access access = resolve(bot);
        out.put("status", access.status());
        if (!access.online()) return out;
        try {
            Class<?> wtClass = Class.forName("appeng.items.tools.powered.WirelessTerminalItem");
            List<String> errs = new ArrayList<>();
            Object grid = wtClass.getMethod("getLinkedGrid",
                            ItemStack.class, net.minecraft.world.level.Level.class,
                            java.util.function.Consumer.class)
                    .invoke(access.terminalItem(), access.terminal(), bot.level(),
                            (java.util.function.Consumer<net.minecraft.network.chat.Component>)
                                    c -> errs.add(c.getString()));
            if (grid == null) {
                out.put("grid", null);
                return out;
            }
            int nodes = 0;
            for (Object ignored2 : (Iterable<?>) grid.getClass().getMethod("getNodes").invoke(grid)) {
                nodes++;
            }
            out.put("nodes", nodes);
            List<String> classes = new ArrayList<>();
            for (Object c : (Iterable<?>) grid.getClass().getMethod("getMachineClasses").invoke(grid)) {
                classes.add(((Class<?>) c).getSimpleName());
            }
            out.put("machines", classes);
            Object energy = grid.getClass().getMethod("getEnergyService").invoke(grid);
            out.put("stored_power", energy.getClass().getMethod("getStoredPower").invoke(energy));
            out.put("max_power", energy.getClass().getMethod("getMaxStoredPower").invoke(energy));
        } catch (Throwable t) {
            out.put("diag_error", t.toString());
        }
        return out;
    }

    // ── internals ────────────────────────────────────────────────────────

    private static Object aeItemKey(ItemStack stack) throws Exception {
        return Class.forName("appeng.api.stacks.AEItemKey")
                .getMethod("of", ItemStack.class).invoke(null, stack);
    }

    private static long storageOp(Access access, String op, Object key, long amount) throws Exception {
        Class<?> actionable = Class.forName("appeng.api.config.Actionable");
        Object modulate = actionable.getField("MODULATE").get(null);
        Class<?> aeKey = Class.forName("appeng.api.stacks.AEKey");
        Class<?> sourceClass = Class.forName("appeng.api.networking.security.IActionSource");
        Method m = access.meStorage().getClass().getMethod(op,
                aeKey, long.class, actionable, sourceClass);
        m.setAccessible(true);
        return (long) m.invoke(access.meStorage(), key, amount, modulate, access.actionSource());
    }

    private static void drainPower(Access access, long items) {
        try {
            Class<?> wtClass = Class.forName("appeng.items.tools.powered.WirelessTerminalItem");
            wtClass.getMethod("usePower",
                            net.minecraft.world.entity.player.Player.class, double.class, ItemStack.class)
                    .invoke(access.terminalItem(), access.holder(),
                            POWER_PER_OPERATION * Math.max(1, items / 8.0), access.terminal());
        } catch (Throwable ignored) {
        }
    }
}
