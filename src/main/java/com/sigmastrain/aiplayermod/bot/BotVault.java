package com.sigmastrain.aiplayermod.bot;

import net.minecraft.core.HolderLookup;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.world.entity.player.Inventory;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Unbounded per-bot storage — the backing store behind a bot's 36 carried slots.
 *
 * The carried inventory is a working set; this is where everything else lives.
 * Deliveries that don't fit page in here instead of evaporating or being dropped
 * (dropped items are destroyed by the entity-cleanup cronjob within minutes).
 *
 * Stacks are kept at or below their max stack size and merged on insert, so the
 * contents are always valid ItemStacks. Capacity is unbounded by design: storage
 * scarcity isn't an interesting constraint in a world where bots conjure matter
 * from XP.
 *
 * All mutation happens on the server thread (behaviors + API handlers marshal
 * through server.execute()); the list is synchronized for read safety from the
 * HTTP pool.
 */
public class BotVault {
    private final List<ItemStack> stacks = java.util.Collections.synchronizedList(new ArrayList<>());

    // ── Mutation ──────────────────────────────────────────────────────────

    /** Deposit a stack. Always succeeds — capacity is unbounded. */
    public void deposit(ItemStack incoming) {
        if (incoming == null || incoming.isEmpty()) return;
        ItemStack remaining = incoming.copy();
        synchronized (stacks) {
            // Top up existing compatible stacks first
            for (ItemStack existing : stacks) {
                if (remaining.isEmpty()) break;
                if (!ItemStack.isSameItemSameComponents(existing, remaining)) continue;
                int room = existing.getMaxStackSize() - existing.getCount();
                if (room <= 0) continue;
                int moved = Math.min(room, remaining.getCount());
                existing.grow(moved);
                remaining.shrink(moved);
            }
            // Whatever is left becomes new stacks
            while (!remaining.isEmpty()) {
                int size = Math.min(remaining.getCount(), remaining.getMaxStackSize());
                ItemStack chunk = remaining.copy();
                chunk.setCount(size);
                stacks.add(chunk);
                remaining.shrink(size);
            }
        }
        incoming.setCount(0);
    }

    /**
     * Withdraw up to {@code count} of an item. Returns the stacks actually
     * pulled (may total less than requested, or be empty).
     */
    public List<ItemStack> withdraw(String itemId, int count) {
        List<ItemStack> out = new ArrayList<>();
        if (count <= 0) return out;
        Item want = resolve(itemId);
        if (want == Items.AIR) return out;
        int remaining = count;
        synchronized (stacks) {
            var it = stacks.iterator();
            while (it.hasNext() && remaining > 0) {
                ItemStack s = it.next();
                if (!s.is(want)) continue;
                int take = Math.min(s.getCount(), remaining);
                ItemStack pulled = s.copy();
                pulled.setCount(take);
                out.add(pulled);
                s.shrink(take);
                remaining -= take;
                if (s.isEmpty()) it.remove();
            }
        }
        return out;
    }

    /** Withdraw into a player's carried inventory; returns how many moved. */
    public int withdrawInto(Inventory inventory, String itemId, int count) {
        int moved = 0;
        for (ItemStack pulled : withdraw(itemId, count)) {
            int before = pulled.getCount();
            inventory.add(pulled);
            // Read the leftover BEFORE re-depositing: deposit() zeroes the
            // stack it absorbs, which made this method report bounced items
            // as moved ("withdrawn: 1" into a full pack, v7 spike finding).
            int leftover = pulled.getCount();
            if (leftover > 0) {
                deposit(pulled);
            }
            moved += before - leftover;
        }
        return moved;
    }

    // ── Queries ───────────────────────────────────────────────────────────

    /** Total count of an exact item id. */
    public int count(String itemId) {
        Item want = resolve(itemId);
        if (want == Items.AIR) return 0;
        int total = 0;
        synchronized (stacks) {
            for (ItemStack s : stacks) {
                if (s.is(want)) total += s.getCount();
            }
        }
        return total;
    }

    /**
     * Search by substring against item id and display name — the bots
     * routinely ask for ids that only partially match reality.
     */
    public List<Map<String, Object>> search(String query) {
        String q = query == null ? "" : query.toLowerCase().trim();
        if (q.contains(":")) q = q.substring(q.indexOf(':') + 1);
        Map<String, Map<String, Object>> merged = new LinkedHashMap<>();
        synchronized (stacks) {
            for (ItemStack s : stacks) {
                String id = BuiltInRegistries.ITEM.getKey(s.getItem()).toString();
                String name = s.getHoverName().getString().toLowerCase();
                if (!q.isEmpty() && !id.toLowerCase().contains(q) && !name.contains(q)) continue;
                Map<String, Object> entry = merged.computeIfAbsent(id, k -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("item", id);
                    m.put("name", s.getHoverName().getString());
                    m.put("count", 0);
                    return m;
                });
                entry.put("count", (int) entry.get("count") + s.getCount());
            }
        }
        return new ArrayList<>(merged.values());
    }

    /** Full manifest, merged by item id. */
    public List<Map<String, Object>> manifest() {
        return search("");
    }

    public int totalItems() {
        int total = 0;
        synchronized (stacks) {
            for (ItemStack s : stacks) total += s.getCount();
        }
        return total;
    }

    public int distinctItems() {
        return manifest().size();
    }

    public boolean isEmpty() {
        synchronized (stacks) {
            return stacks.isEmpty();
        }
    }

    public void clear() {
        synchronized (stacks) {
            stacks.clear();
        }
    }

    // ── Persistence ───────────────────────────────────────────────────────

    public List<CompoundTag> save(HolderLookup.Provider registries) {
        List<CompoundTag> out = new ArrayList<>();
        synchronized (stacks) {
            for (ItemStack s : stacks) {
                if (s.isEmpty()) continue;
                out.add((CompoundTag) s.save(registries));
            }
        }
        return out;
    }

    public void load(List<ItemStack> loaded) {
        synchronized (stacks) {
            stacks.clear();
            for (ItemStack s : loaded) {
                if (s != null && !s.isEmpty()) stacks.add(s);
            }
        }
    }

    private static Item resolve(String itemId) {
        if (itemId == null || itemId.isEmpty()) return Items.AIR;
        String id = itemId.contains(":") ? itemId : "minecraft:" + itemId;
        try {
            return BuiltInRegistries.ITEM.get(ResourceLocation.parse(id));
        } catch (Exception e) {
            return Items.AIR;
        }
    }
}
