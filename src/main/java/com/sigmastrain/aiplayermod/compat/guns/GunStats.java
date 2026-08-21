package com.sigmastrain.aiplayermod.compat.guns;

import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.bot.BotManager;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.LivingEntity;
import net.neoforged.bus.api.Event;
import net.neoforged.neoforge.common.NeoForge;

import java.lang.reflect.Method;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Consumer;

/**
 * Gun accuracy telemetry for bots, from TaCZ's own events (GunShootEvent,
 * EntityHurtByGunEvent, EntityKillByGunEvent). The live test burned ~1300 P90
 * rounds for ~5 kills at 4 blocks and nothing could say why: this counts shots,
 * hits (by what was hit — hostile vs another bot vs other), and kills per bot,
 * logs a line every 50 shots and on each kill, and rides along in bot status.
 * TaCZ is not on the compile classpath, so the event classes are bound by name
 * and read reflectively; absent TaCZ this is a no-op. Hits bind to
 * EntityHurtByGunEvent$Post: TaCZ posts the Pre/Post SUBCLASSES, and a listener
 * on the parent class never fires (first telemetry run read 0 hits on 3,320
 * shots for that reason alone).
 */
public final class GunStats {

    private GunStats() {}

    public static final class Stats {
        public volatile long shots, hits, kills, hitHostile, hitBot, hitOther;
        public volatile double damage;
        Map<String, Object> toMap() {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("shots", shots); m.put("hits", hits); m.put("kills", kills);
            m.put("hit_hostile", hitHostile); m.put("hit_bot", hitBot); m.put("hit_other", hitOther);
            m.put("damage", Math.round(damage));
            m.put("accuracy", shots > 0 ? Math.round(1000.0 * hits / shots) / 10.0 : 0.0);
            return m;
        }
    }

    private static final Map<String, Stats> STATS = new ConcurrentHashMap<>();
    private static boolean registered;

    public static Map<String, Object> summary(String bot) {
        Stats s = STATS.get(bot);
        return s == null ? Map.of() : s.toMap();
    }

    @SuppressWarnings({"unchecked", "rawtypes"})
    public static synchronized void register() {
        if (registered || !TaczCompat.isAvailable()) return;
        registered = true;
        try {
            bind("com.tacz.guns.api.event.common.GunShootEvent", "getShooter", (bot, e, m) -> {
                stats(bot).shots++;
                Stats s = stats(bot);
                if (s.shots % 50 == 0) log(bot, s);
            });
            bind("com.tacz.guns.api.event.common.EntityHurtByGunEvent$Post", "getAttacker", (bot, e, m) -> {
                Stats s = stats(bot);
                s.hits++;
                try {
                    Object hurt = m.get("getHurtEntity").invoke(e);
                    Object amt = m.get("getAmount").invoke(e);
                    if (amt instanceof Number n) s.damage += n.doubleValue();
                    if (hurt instanceof ServerPlayer) s.hitBot++;
                    else if (hurt instanceof net.minecraft.world.entity.monster.Monster
                            || hurt instanceof net.minecraft.world.entity.monster.Enemy) s.hitHostile++;
                    else s.hitOther++;
                } catch (Throwable ignored) {}
            });
            bind("com.tacz.guns.api.event.common.EntityKillByGunEvent", "getAttacker", (bot, e, m) -> {
                Stats s = stats(bot);
                s.kills++;
                log(bot, s);
            });
            AIPlayerMod.LOGGER.info("[GunStats] TaCZ shot/hit/kill telemetry registered");
        } catch (Throwable t) {
            AIPlayerMod.LOGGER.warn("[GunStats] could not bind TaCZ events: {}", t.toString());
        }
    }

    private interface Handler { void accept(String bot, Object event, Map<String, Method> methods) throws Exception; }

    @SuppressWarnings({"unchecked", "rawtypes"})
    private static void bind(String className, String shooterGetter, Handler h) throws Exception {
        Class<? extends Event> cls = (Class<? extends Event>) Class.forName(className);
        Map<String, Method> methods = new LinkedHashMap<>();
        for (Method mm : cls.getMethods()) if (mm.getParameterCount() == 0 && mm.getName().startsWith("get")) methods.put(mm.getName(), mm);
        Method shooter = methods.get(shooterGetter);
        Consumer<Event> c = e -> {
            try {
                Object who = shooter.invoke(e);
                if (!(who instanceof ServerPlayer sp) || !BotManager.isBot(sp)) return;
                h.accept(sp.getGameProfile().getName(), e, methods);
            } catch (Throwable ignored) {}
        };
        NeoForge.EVENT_BUS.addListener((Class) cls, (Consumer) c);
    }

    private static Stats stats(String bot) { return STATS.computeIfAbsent(bot, k -> new Stats()); }

    private static void log(String bot, Stats s) {
        AIPlayerMod.LOGGER.info("[{}] [GunStats] shots={} hits={} ({}%) kills={} hit_hostile={} hit_bot={} hit_other={} dmg={}",
                bot, s.shots, s.hits, s.shots > 0 ? Math.round(100.0 * s.hits / s.shots) : 0,
                s.kills, s.hitHostile, s.hitBot, s.hitOther, Math.round(s.damage));
    }
}
