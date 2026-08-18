package com.sigmastrain.aiplayermod.compat.guns;

import com.sigmastrain.aiplayermod.actions.ConjureAction;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Conjuring guns. TaCZ guns are ONE item ({@code tacz:modern_kinetic_gun}) whose
 * identity is a gun id component, so "channel tacz:modern_kinetic_gun" yields a
 * broken blank — the channel target must be the <em>gun id</em>
 * ({@code tacz:ak47}) and the stack must be built through TaCZ's builder.
 * Superb Warfare guns are ordinary items. This class is the single place that
 * turns "a gun name" into loaded gun + ammo stacks and prices it, used by
 * CHANNEL, the overlay quote, POST /conjure and the hive requisition path.
 */
public final class GunConjure {

    private GunConjure() {}

    public enum Kind { TACZ, SW }

    /** A resolved gun request. {@code id} is the canonical target to show back to the user. */
    public record Gun(Kind kind, ResourceLocation id, String display) {
        public String idString() { return id.toString(); }
    }

    /** Default ammo when the caller gives none: TaCZ rounds / SW ammo boxes. */
    public static final int DEFAULT_TACZ_ROUNDS = 90;
    public static final int DEFAULT_SW_BOXES = 3;

    /** Resolve a channel target to a gun, or null when it's not a gun. */
    public static Gun resolve(String target) {
        if (target == null || target.isBlank()) return null;
        String t = target.trim();
        // Superb Warfare: a real registered item that SW considers a gun.
        ResourceLocation rl = ResourceLocation.tryParse(t.contains(":") ? t : "superbwarfare:" + t);
        if (rl != null && BuiltInRegistries.ITEM.containsKey(rl)) {
            Item item = BuiltInRegistries.ITEM.get(rl);
            if (SwGunCompat.isGun(new ItemStack(item))) {
                return new Gun(Kind.SW, rl, new ItemStack(item).getHoverName().getString());
            }
            // the blank TaCZ item itself → fall through to gun-id resolution of the rest
            if (!"tacz".equals(rl.getNamespace()) || !"modern_kinetic_gun".equals(rl.getPath())) return null;
            return null;
        }
        // TaCZ: a gun id (loose match).
        ResourceLocation gunId = TaczCompat.resolveGunId(t);
        if (gunId != null) return new Gun(Kind.TACZ, gunId, TaczCompat.gunName(gunId));
        return null;
    }

    /** XP cost: the gun's base item cost (registry/default) + a flat ammo term. */
    public static int xpCost(Gun g, int ammo) {
        int base = g.kind() == Kind.TACZ
                ? ConjureAction.costFor("tacz:modern_kinetic_gun")
                : ConjureAction.costFor(g.idString());
        int ammoCost = g.kind() == Kind.TACZ
                ? Math.max(1, ammo / 30) * ConjureAction.costFor("tacz:ammo")
                : ammo * 2;
        return Math.max(1, base) + Math.max(0, ammoCost);
    }

    /** Build the gun (loaded) plus its ammo. */
    public static List<ItemStack> build(ServerLevel level, Gun g, int ammo) {
        List<ItemStack> out = new ArrayList<>();
        if (g.kind() == Kind.TACZ) {
            ItemStack gun = TaczCompat.buildGun(level.registryAccess(), g.id());
            if (!gun.isEmpty()) out.add(gun);
            int remaining = Math.max(0, ammo);
            while (remaining > 0) {
                ItemStack a = TaczCompat.buildAmmo(g.id(), Math.min(64, remaining));
                if (a.isEmpty()) break;
                out.add(a);
                remaining -= a.getCount();
            }
        } else {
            Item item = BuiltInRegistries.ITEM.get(g.id());
            if (item != Items.AIR) {
                ItemStack gun = new ItemStack(item);
                out.add(gun);
                ItemStack a = SwGunCompat.ammoStackFor(gun, Math.max(0, ammo));
                if (!a.isEmpty()) out.add(a);
            }
        }
        return out;
    }

    /** Catalogue for UIs: canonical id → display name (TaCZ gun ids + SW gun items). */
    public static Map<String, String> catalogue() {
        Map<String, String> out = new LinkedHashMap<>();
        for (String id : TaczCompat.gunIds()) {
            ResourceLocation rl = ResourceLocation.parse(id);
            out.put(id, TaczCompat.gunName(rl) + " (TaCZ)");
        }
        if (SwGunCompat.isAvailable()) {
            for (Item item : BuiltInRegistries.ITEM) {
                ResourceLocation rl = BuiltInRegistries.ITEM.getKey(item);
                if (!"superbwarfare".equals(rl.getNamespace())) continue;
                ItemStack st = new ItemStack(item);
                if (SwGunCompat.isGun(st)) out.put(rl.toString(), st.getHoverName().getString() + " (SW)");
            }
        }
        return out;
    }

    /** Catalogue id for a held stack: TaCZ gun → its gun id, TaCZ ammo → its ammo id, else null. */
    public static String discoveryId(ItemStack stack) {
        ResourceLocation gunId = TaczCompat.gunIdOf(stack);
        if (gunId != null) return gunId.toString();
        ResourceLocation ammoId = TaczCompat.ammoIdOf(stack);
        if (ammoId != null) return ammoId.toString();
        return null;
    }

    // ── ammo ─────────────────────────────────────────────────────────────

    /** An ammo request: TaCZ ammo id, or SW ammo template stack. */
    public record Ammo(Kind kind, ResourceLocation id, ItemStack template, String display) {
        public String idString() { return id != null ? id.toString() : (template == null ? "" : BuiltInRegistries.ITEM.getKey(template.getItem()).toString()); }
    }

    private static boolean isAmmoWord(String t) {
        String s = t.toLowerCase(java.util.Locale.ROOT).trim();
        return s.equals("ammo") || s.equals("ammunition") || s.equals("bullets") || s.equals("rounds")
                || s.equals("magazine") || s.equals("mags") || s.equals("ammo for held gun");
    }

    /**
     * Resolve an ammo target: "ammo" (the ammo of the gun the bot holds, else the
     * first gun it carries), a TaCZ ammo id ({@code tacz:762x39}), or an SW ammo item.
     * Null when it's not ammo.
     */
    public static Ammo resolveAmmo(String target, net.minecraft.server.level.ServerPlayer bot) {
        if (target == null || target.isBlank()) return null;
        String t = target.trim();
        if (isAmmoWord(t)) {
            ItemStack gun = bot == null ? ItemStack.EMPTY : heldGun(bot);
            if (gun.isEmpty()) return null;
            ResourceLocation gunId = TaczCompat.gunIdOf(gun);
            if (gunId != null) {
                ResourceLocation ammoId = TaczCompat.ammoIdFor(gunId);
                return ammoId == null ? null : new Ammo(Kind.TACZ, ammoId, null, "ammo for " + TaczCompat.gunName(gunId));
            }
            if (SwGunCompat.isGun(gun)) {
                ItemStack a = SwGunCompat.ammoStackFor(gun, 1);
                return a.isEmpty() ? null : new Ammo(Kind.SW, null, a, "ammo for " + gun.getHoverName().getString());
            }
            return null;
        }
        ResourceLocation rl = ResourceLocation.tryParse(t.contains(":") ? t : "tacz:" + t);
        if (rl != null && TaczCompat.isAmmoId(rl)) return new Ammo(Kind.TACZ, rl, null, "TaCZ ammo " + rl.getPath());
        return null;
    }

    /** The gun in the bot's main hand, else the first gun in its inventory, else empty. */
    public static ItemStack heldGun(net.minecraft.server.level.ServerPlayer bot) {
        ItemStack main = bot.getMainHandItem();
        if (TaczCompat.isGun(main) || SwGunCompat.isGun(main)) return main;
        for (int i = 0; i < 36; i++) {
            ItemStack st = bot.getInventory().getItem(i);
            if (TaczCompat.isGun(st) || SwGunCompat.isGun(st)) return st;
        }
        return ItemStack.EMPTY;
    }

    /** XP for {@code count} rounds/boxes of ammo. */
    public static int ammoXpCost(Ammo a, int count) {
        if (a.kind() == Kind.TACZ) return Math.max(1, (count + 29) / 30) * Math.max(1, ConjureAction.costFor("tacz:ammo"));
        return Math.max(1, count) * 2;
    }

    public static List<ItemStack> buildAmmo(Ammo a, int count) {
        List<ItemStack> out = new ArrayList<>();
        int remaining = Math.max(1, count);
        if (a.kind() == Kind.TACZ) {
            while (remaining > 0) {
                ItemStack st = TaczCompat.buildAmmoById(a.id(), Math.min(64, remaining));
                if (st.isEmpty()) break;
                out.add(st);
                remaining -= st.getCount();
            }
        } else if (a.template() != null) {
            while (remaining > 0) {
                int n = Math.min(a.template().getMaxStackSize(), remaining);
                out.add(a.template().copyWithCount(n));
                remaining -= n;
            }
        }
        return out;
    }

    /** Ammo default per kind. */
    public static int defaultAmmo(Gun g) {
        return g.kind() == Kind.TACZ ? DEFAULT_TACZ_ROUNDS : DEFAULT_SW_BOXES;
    }
}
