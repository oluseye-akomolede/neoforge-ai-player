package com.sigmastrain.aiplayermod.compat.curios;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.item.ItemStack;
import net.neoforged.fml.ModList;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * Curios worn-slot access for bots — list, equip, unequip.
 *
 * <p>Reflection-only (no compile dependency, frozen-modpack rule). The v7
 * spike proved fake players get the full 48-slot curios inventory; this
 * turns that finding into the real loadout surface: the overlay's Worn row
 * and the {@code curios_equip}/{@code curios_unequip} API actions.
 *
 * <p>Every failure is an honest status string, never an exception — the
 * caller shows it to the player ("no curios slot accepts that item",
 * "slot occupied by <item>").
 */
public final class CuriosCompat {

    private CuriosCompat() {}

    public record WornSlot(String slotType, int index, ItemStack stack) {}

    public static boolean isAvailable() {
        return ModList.get().isLoaded("curios");
    }

    // ── the handler internals, resolved once ─────────────────────────────

    private static Object handler(ServerPlayer bot) throws Exception {
        Class<?> api = Class.forName("top.theillusivec4.curios.api.CuriosApi");
        Object opt = api.getMethod("getCuriosInventory",
                net.minecraft.world.entity.LivingEntity.class).invoke(null, bot);
        if (opt instanceof Optional<?> o && o.isPresent()) return o.get();
        return null;
    }

    /** All worn slots, empty ones included (the overlay shows the empties). */
    public static List<WornSlot> list(ServerPlayer bot) {
        List<WornSlot> out = new ArrayList<>();
        if (!isAvailable()) return out;
        try {
            Object handler = handler(bot);
            if (handler == null) return out;
            // Map<String, ICurioStacksHandler> getCurios()
            Object curios = handler.getClass().getMethod("getCurios").invoke(handler);
            if (!(curios instanceof Map<?, ?> byType)) return out;
            for (Map.Entry<?, ?> e : byType.entrySet()) {
                String slotType = String.valueOf(e.getKey());
                Object stacksHandler = e.getValue();
                Object stacks = stacksHandler.getClass().getMethod("getStacks")
                        .invoke(stacksHandler);
                int size = (int) stacks.getClass().getMethod("getSlots").invoke(stacks);
                Method getStack = stacks.getClass().getMethod("getStackInSlot", int.class);
                for (int i = 0; i < size; i++) {
                    Object s = getStack.invoke(stacks, i);
                    if (s instanceof ItemStack st) {
                        out.add(new WornSlot(slotType, i, st));
                    }
                }
            }
        } catch (Throwable t) {
            AIPlayerMod.LOGGER.warn("[curios] list failed: {}", t.toString());
        }
        return out;
    }

    /**
     * Equip one item from the bot's inventory into the first curios slot
     * that accepts it. @return null on success, else an honest reason.
     */
    public static String equip(ServerPlayer bot, String itemId) {
        if (!isAvailable()) return "curios not loaded";
        try {
            var rl = net.minecraft.resources.ResourceLocation.tryParse(
                    itemId.contains(":") ? itemId : "minecraft:" + itemId);
            if (rl == null) return "bad item id: " + itemId;

            // Find the stack in the bot's main inventory.
            var inv = bot.getInventory();
            int slot = -1;
            for (int i = 0; i < inv.getContainerSize(); i++) {
                ItemStack s = inv.getItem(i);
                if (!s.isEmpty() && net.minecraft.core.registries.BuiltInRegistries
                        .ITEM.getKey(s.getItem()).equals(rl)) {
                    slot = i;
                    break;
                }
            }
            if (slot == -1) return "not carrying " + itemId;
            ItemStack toWear = inv.getItem(slot);

            Object handler = handler(bot);
            if (handler == null) return "no curios inventory on this bot";

            Object curios = handler.getClass().getMethod("getCurios").invoke(handler);
            if (!(curios instanceof Map<?, ?> byType)) return "curios handler shape unknown";

            List<String> rejections = new ArrayList<>();
            for (Map.Entry<?, ?> e : byType.entrySet()) {
                String slotType = String.valueOf(e.getKey());
                Object stacksHandler = e.getValue();
                Object stacks = stacksHandler.getClass().getMethod("getStacks")
                        .invoke(stacksHandler);
                int size = (int) stacks.getClass().getMethod("getSlots").invoke(stacks);
                Method getStack = stacks.getClass().getMethod("getStackInSlot", int.class);
                Method setStack = stacks.getClass().getMethod("setStackInSlot",
                        int.class, ItemStack.class);
                for (int i = 0; i < size; i++) {
                    if (!(getStack.invoke(stacks, i) instanceof ItemStack cur)) continue;
                    if (!cur.isEmpty()) continue;
                    if (!accepts(bot, slotType, i, toWear)) {
                        rejections.add(slotType);
                        break; // one rejection per slot type is enough signal
                    }
                    ItemStack one = toWear.split(1);
                    setStack.invoke(stacks, i, one);
                    if (toWear.isEmpty()) inv.setItem(slot, ItemStack.EMPTY);
                    return null;
                }
            }
            return rejections.isEmpty()
                    ? "no empty curios slot"
                    : "no curios slot accepts " + itemId;
        } catch (Throwable t) {
            AIPlayerMod.LOGGER.warn("[curios] equip failed: {}", t.toString());
            return "curios error: " + t.getClass().getSimpleName();
        }
    }

    /**
     * Remove a worn item back into the bot's inventory.
     * @return null on success, else an honest reason.
     */
    public static String unequip(ServerPlayer bot, String slotType, int index) {
        if (!isAvailable()) return "curios not loaded";
        try {
            Object handler = handler(bot);
            if (handler == null) return "no curios inventory on this bot";
            Object curios = handler.getClass().getMethod("getCurios").invoke(handler);
            if (!(curios instanceof Map<?, ?> byType)) return "curios handler shape unknown";
            Object stacksHandler = byType.get(slotType);
            if (stacksHandler == null) return "no such slot type: " + slotType;
            Object stacks = stacksHandler.getClass().getMethod("getStacks")
                    .invoke(stacksHandler);
            Object cur = stacks.getClass().getMethod("getStackInSlot", int.class)
                    .invoke(stacks, index);
            if (!(cur instanceof ItemStack worn) || worn.isEmpty()) {
                return "that slot is empty";
            }
            if (!bot.getInventory().add(worn.copy())) {
                return "bot inventory is full";
            }
            stacks.getClass().getMethod("setStackInSlot", int.class, ItemStack.class)
                    .invoke(stacks, index, ItemStack.EMPTY);
            return null;
        } catch (Throwable t) {
            AIPlayerMod.LOGGER.warn("[curios] unequip failed: {}", t.toString());
            return "curios error: " + t.getClass().getSimpleName();
        }
    }

    /** Place a stack directly into a worn slot — the state-load path.
     *  Restarts must not strip the fleet's terminals (they did once). */
    public static boolean putDirect(ServerPlayer bot, String slotType, int index,
                                    ItemStack stack) {
        if (!isAvailable()) return false;
        try {
            Object handler = handler(bot);
            if (handler == null) return false;
            Object curios = handler.getClass().getMethod("getCurios").invoke(handler);
            if (!(curios instanceof Map<?, ?> byType)) return false;
            Object stacksHandler = byType.get(slotType);
            if (stacksHandler == null) return false;
            Object stacks = stacksHandler.getClass().getMethod("getStacks").invoke(stacksHandler);
            int size = (int) stacks.getClass().getMethod("getSlots").invoke(stacks);
            if (index < 0 || index >= size) return false;
            stacks.getClass().getMethod("setStackInSlot", int.class, ItemStack.class)
                    .invoke(stacks, index, stack);
            return true;
        } catch (Throwable t) {
            AIPlayerMod.LOGGER.warn("[curios] putDirect failed: {}", t.toString());
            return false;
        }
    }

    /** Does this slot accept the item? Falls back to true when the check
     *  itself can't run — equip then fails loudly rather than silently. */
    private static boolean accepts(ServerPlayer bot, String slotType, int index,
                                   ItemStack stack) {
        try {
            // CuriosApi.isStackValid(SlotContext, ItemStack) — SlotContext is
            // a record (slot id, entity, index, cosmetic, visible).
            Class<?> ctxClass = Class.forName("top.theillusivec4.curios.api.SlotContext");
            Object ctx = ctxClass.getConstructors()[0].newInstance(
                    slotType, bot, index, false, true);
            Class<?> api = Class.forName("top.theillusivec4.curios.api.CuriosApi");
            Object ok = api.getMethod("isStackValid", ctxClass, ItemStack.class)
                    .invoke(null, ctx, stack);
            return Boolean.TRUE.equals(ok);
        } catch (Throwable t) {
            return true;
        }
    }
}
