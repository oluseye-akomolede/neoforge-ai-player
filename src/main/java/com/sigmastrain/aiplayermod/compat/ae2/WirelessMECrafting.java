package com.sigmastrain.aiplayermod.compat.ae2;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.item.ItemStack;

import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Future;

/**
 * AE2 autocrafting through the worn wireless terminal — the last v8 rock.
 *
 * <p>"Submit crafting requests for a full set of quantum armor" needs three
 * verbs against {@code ICraftingService}: what CAN the network craft
 * ({@link #listCraftables}), start a job ({@link #startRequest} — async
 * calculation, then submit), and how is it going ({@link #poll} — the
 * per-bot state machine the CRAFT_REQUEST behavior ticks).
 *
 * <p>Reflection + {@link Proxy} only (frozen modpack, no compile dep). The
 * simulation requester is a two-method proxy; {@code submitJob} takes a null
 * requester the same way AE2's own terminals do, so crafted items land in
 * network storage — where {@code me_pull} and the Vault tab already reach.
 */
public final class WirelessMECrafting {

    private WirelessMECrafting() {}

    /** One in-flight request per bot — the fleet convention everywhere. */
    public record Job(String itemId, long count, Future<?> calculation,
                      Object link, String state, String detail) {}

    private static final Map<String, Job> JOBS = new ConcurrentHashMap<>();

    // ── craftables ───────────────────────────────────────────────────────

    public static List<String> listCraftables(ServerPlayer bot, String query, int limit) {
        List<String> out = new ArrayList<>();
        try {
            Object grid = gridFor(bot);
            if (grid == null) return out;
            Object crafting = grid.getClass().getMethod("getCraftingService").invoke(grid);
            Class<?> filterCls = Class.forName("appeng.api.storage.AEKeyFilter");
            Object none = filterCls.getMethod("none").invoke(null);
            var keys = (java.util.Set<?>) crafting.getClass()
                    .getMethod("getCraftables", filterCls).invoke(crafting, none);
            Class<?> itemKey = Class.forName("appeng.api.stacks.AEItemKey");
            String q = query == null ? "" : query.toLowerCase();
            for (Object key : keys) {
                if (out.size() >= limit) break;
                if (!itemKey.isInstance(key)) continue;
                ItemStack stack = (ItemStack) itemKey.getMethod("toStack").invoke(key);
                String id = BuiltInRegistries.ITEM.getKey(stack.getItem()).toString();
                if (!q.isEmpty() && !id.toLowerCase().contains(q)
                        && !stack.getHoverName().getString().toLowerCase().contains(q)) {
                    continue;
                }
                out.add(id);
            }
            java.util.Collections.sort(out);
        } catch (Throwable t) {
            AIPlayerMod.LOGGER.warn("[me-craft] listCraftables failed: {}", t.toString());
        }
        return out;
    }

    // ── request lifecycle ────────────────────────────────────────────────

    /** Begin the async calculation. @return null ok, else honest refusal. */
    public static String startRequest(ServerPlayer bot, String itemId, long count) {
        String name = bot.getGameProfile().getName();
        Job existing = JOBS.get(name);
        if (existing != null && ("CALCULATING".equals(existing.state())
                || "CRAFTING".equals(existing.state()))) {
            return "already crafting " + existing.itemId() + " — one job per bot";
        }
        try {
            Object grid = gridFor(bot);
            if (grid == null) return "no linked, powered terminal on this bot";
            Object crafting = grid.getClass().getMethod("getCraftingService").invoke(grid);

            var rl = ResourceLocation.tryParse(
                    itemId.contains(":") ? itemId : "minecraft:" + itemId);
            if (rl == null || !BuiltInRegistries.ITEM.containsKey(rl)) {
                return "unknown item: " + itemId;
            }
            Class<?> itemKeyCls = Class.forName("appeng.api.stacks.AEItemKey");
            Object key = itemKeyCls.getMethod("of", net.minecraft.world.level.ItemLike.class)
                    .invoke(null, BuiltInRegistries.ITEM.get(rl));

            Object isCraftable = crafting.getClass().getMethod("isCraftable",
                    Class.forName("appeng.api.stacks.AEKey")).invoke(crafting, key);
            if (!Boolean.TRUE.equals(isCraftable)) {
                return "the network has no pattern for " + itemId;
            }
            // Diagnostic seam: log EXACTLY what the gate saw — calculations
            // have been failing with "missing = the request" while this very
            // gate passes, and the divergence point must be pinned.
            try {
                var pats = (java.util.Collection<?>) crafting.getClass()
                        .getMethod("getCraftingFor", Class.forName("appeng.api.stacks.AEKey"))
                        .invoke(crafting, key);
                Object first = pats.isEmpty() ? null : pats.iterator().next();
                AIPlayerMod.LOGGER.info("[me-craft] gate: key={} patterns={} first={}",
                        key, pats.size(), first == null ? "-" : first.getClass().getSimpleName());
            } catch (Throwable lg) {
                AIPlayerMod.LOGGER.info("[me-craft] gate logging failed: {}", lg.toString());
            }

            Class<?> sourceCls = Class.forName("appeng.api.networking.security.IActionSource");
            Object source = sourceCls.getMethod("ofPlayer",
                    net.minecraft.world.entity.player.Player.class).invoke(null, bot);

            // The requester's grid node is NOT optional decoration:
            // buildChildPatterns derives its crafting service from
            // node.getGrid() and silently builds ZERO patterns on null —
            // the root of every "missing: <the request itself>" failure.
            // The grid's pivot node is a legitimate stand-in for a
            // terminal-less requester.
            Object pivotNode = grid.getClass().getMethod("getPivot").invoke(grid);
            Class<?> simReqCls = Class.forName(
                    "appeng.api.networking.crafting.ICraftingSimulationRequester");
            Object simRequester = Proxy.newProxyInstance(
                    simReqCls.getClassLoader(), new Class<?>[]{simReqCls},
                    (proxy, method, args) -> switch (method.getName()) {
                        case "getActionSource" -> source;
                        case "getGridNode" -> pivotNode;
                        case "equals" -> proxy == args[0];
                        case "hashCode" -> System.identityHashCode(proxy);
                        case "toString" -> "aiplayermod-sim-requester";
                        default -> null;
                    });

            Class<?> strategyCls = Class.forName(
                    "appeng.api.networking.crafting.CalculationStrategy");
            Object strategy = strategyCls.getField("REPORT_MISSING_ITEMS").get(null);

            Method begin = crafting.getClass().getMethod("beginCraftingCalculation",
                    net.minecraft.world.level.Level.class, simReqCls,
                    Class.forName("appeng.api.stacks.AEKey"), long.class, strategyCls);
            Future<?> future = (Future<?>) begin.invoke(
                    crafting, bot.level(), simRequester, key, count, strategy);

            JOBS.put(name, new Job(rl.toString(), count, future, null,
                    "CALCULATING", "computing recipe tree"));
            return null;
        } catch (Throwable t) {
            AIPlayerMod.LOGGER.warn("[me-craft] startRequest failed", t);
            return "craft request error: " + t.getClass().getSimpleName();
        }
    }

    /**
     * Advance the bot's job one step. Server thread. Returns the job (never
     * null once started; TERMINAL states persist until the next start).
     */
    public static Job poll(ServerPlayer bot) {
        String name = bot.getGameProfile().getName();
        Job job = JOBS.get(name);
        if (job == null) return null;
        try {
            switch (job.state()) {
                case "CALCULATING" -> {
                    if (!job.calculation().isDone()) return job;
                    Object plan = job.calculation().get();
                    boolean simulation = (boolean) plan.getClass()
                            .getMethod("simulation").invoke(plan);
                    if (simulation) {
                        Object missing = plan.getClass().getMethod("missingItems").invoke(plan);
                        job = new Job(job.itemId(), job.count(), job.calculation(), null,
                                "FAILED", "missing ingredients: " + summarizeCounter(missing));
                        JOBS.put(name, job);
                        return job;
                    }
                    Object grid = gridFor(bot);
                    if (grid == null) {
                        job = new Job(job.itemId(), job.count(), job.calculation(), null,
                                "FAILED", "terminal went offline mid-request");
                        JOBS.put(name, job);
                        return job;
                    }
                    Object crafting = grid.getClass().getMethod("getCraftingService").invoke(grid);
                    Class<?> sourceCls = Class.forName(
                            "appeng.api.networking.security.IActionSource");
                    Object source = sourceCls.getMethod("ofPlayer",
                            net.minecraft.world.entity.player.Player.class).invoke(null, bot);
                    Method submit = crafting.getClass().getMethod("submitJob",
                            Class.forName("appeng.api.networking.crafting.ICraftingPlan"),
                            Class.forName("appeng.api.networking.crafting.ICraftingRequester"),
                            Class.forName("appeng.api.networking.crafting.ICraftingCPU"),
                            boolean.class, sourceCls);
                    Object result = submit.invoke(crafting, plan, null, null, false, source);
                    boolean ok = (boolean) result.getClass().getMethod("successful").invoke(result);
                    if (!ok) {
                        Object code = result.getClass().getMethod("errorCode").invoke(result);
                        job = new Job(job.itemId(), job.count(), job.calculation(), null,
                                "FAILED", "submit refused: " + code);
                        JOBS.put(name, job);
                        return job;
                    }
                    Object link = result.getClass().getMethod("link").invoke(result);
                    job = new Job(job.itemId(), job.count(), job.calculation(), link,
                            "CRAFTING", "job on the grid");
                    JOBS.put(name, job);
                    return job;
                }
                case "CRAFTING" -> {
                    Object link = job.link();
                    if (link == null) return job;
                    boolean cancelled = (boolean) link.getClass()
                            .getMethod("isCanceled").invoke(link);
                    boolean done = (boolean) link.getClass().getMethod("isDone").invoke(link);
                    if (!done && !cancelled) {
                        // Standalone links (null requester) are never marked
                        // done by the CPU — live bug: the helmet finished on
                        // the grid while the directive polled forever. The
                        // service's own request tracker is the truth: when it
                        // stops requesting the key, the job is over.
                        try {
                            Object grid = gridFor(bot);
                            if (grid != null) {
                                Object crafting = grid.getClass()
                                        .getMethod("getCraftingService").invoke(grid);
                                var rl = ResourceLocation.parse(job.itemId());
                                Class<?> itemKeyCls = Class.forName("appeng.api.stacks.AEItemKey");
                                Object key = itemKeyCls.getMethod("of",
                                        net.minecraft.world.level.ItemLike.class)
                                        .invoke(null, BuiltInRegistries.ITEM.get(rl));
                                boolean requesting = (boolean) crafting.getClass()
                                        .getMethod("isRequesting",
                                                Class.forName("appeng.api.stacks.AEKey"))
                                        .invoke(crafting, key);
                                if (!requesting) done = true;
                            }
                        } catch (Throwable ignored) {
                        }
                    }
                    if (cancelled) {
                        job = new Job(job.itemId(), job.count(), job.calculation(), link,
                                "CANCELLED", "grid cancelled the job");
                        JOBS.put(name, job);
                    } else if (done) {
                        job = new Job(job.itemId(), job.count(), job.calculation(), link,
                                "DONE", job.count() + "x " + job.itemId() + " in network storage");
                        JOBS.put(name, job);
                    }
                    return job;
                }
                default -> {
                    return job;
                }
            }
        } catch (Throwable t) {
            AIPlayerMod.LOGGER.warn("[me-craft] poll failed", t);
            Job failed = new Job(job.itemId(), job.count(), job.calculation(), job.link(),
                    "FAILED", "poll error: " + t.getClass().getSimpleName());
            JOBS.put(name, failed);
            return failed;
        }
    }

    public static void cancel(ServerPlayer bot) {
        Job job = JOBS.get(bot.getGameProfile().getName());
        if (job != null && job.link() != null) {
            try {
                job.link().getClass().getMethod("cancel").invoke(job.link());
            } catch (Throwable ignored) {
            }
        }
        if (job != null && job.calculation() != null) {
            job.calculation().cancel(true);
        }
        JOBS.remove(bot.getGameProfile().getName());
    }

    // ── helpers ──────────────────────────────────────────────────────────

    /** The grid behind the bot's worn/carried terminal, or null. */
    private static Object gridFor(ServerPlayer bot) {
        try {
            Class<?> wtClass = Class.forName("appeng.items.tools.powered.WirelessTerminalItem");
            var access = WirelessME.resolve(bot);
            if (!access.online()) return null;
            Method getLinkedGrid = wtClass.getMethod("getLinkedGrid",
                    ItemStack.class, net.minecraft.world.level.Level.class,
                    java.util.function.Consumer.class);
            return getLinkedGrid.invoke(access.terminalItem(), access.terminal(),
                    bot.level(), (java.util.function.Consumer<?>) c -> { });
        } catch (Throwable t) {
            return null;
        }
    }

    private static String summarizeCounter(Object counter) {
        try {
            Class<?> counterCls = Class.forName("appeng.api.stacks.KeyCounter");
            Class<?> aeKeyCls = Class.forName("appeng.api.stacks.AEKey");
            Class<?> itemKey = Class.forName("appeng.api.stacks.AEItemKey");
            Iterable<?> keys = (Iterable<?>) counterCls.getMethod("keySet").invoke(counter);
            Method get = counterCls.getMethod("get", aeKeyCls);
            List<String> parts = new ArrayList<>();
            for (Object key : keys) {
                if (parts.size() >= 5) {
                    parts.add("…");
                    break;
                }
                long n = (long) get.invoke(counter, key);
                String id = itemKey.isInstance(key)
                        ? BuiltInRegistries.ITEM.getKey(((ItemStack) itemKey
                                .getMethod("toStack").invoke(key)).getItem()).getPath()
                        : key.toString();
                parts.add(n + "x " + id);
            }
            return String.join(", ", parts);
        } catch (Throwable t) {
            return "(unreadable)";
        }
    }
}
