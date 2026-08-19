package com.sigmastrain.aiplayermod.api;

import com.google.gson.JsonObject;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.DirectiveType;
import com.sigmastrain.aiplayermod.brain.Fusion;
import com.sigmastrain.aiplayermod.brain.FusionControl;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Server-thread backing for the {@code /bot/{name}/fuse_block|unfuse_block|
 * manage_fusion|fusion} actions, and the overlay's fusion ops. {@code fuse_block}
 * routes through a directive (so it shows as an order); {@code manage_fusion}
 * writes the live knobs the running MANAGE_FUSION behavior re-reads each tick.
 */
public final class FusionApi {

    private FusionApi() {}

    private static Map<String, Object> err(String msg) { return Map.of("ok", false, "error", msg); }

    private static String str(JsonObject b, String k, String d) {
        return b != null && b.has(k) && !b.get(k).isJsonNull() ? b.get(k).getAsString() : d;
    }
    private static double num(JsonObject b, String k, double d) {
        try { return b != null && b.has(k) ? b.get(k).getAsDouble() : d; } catch (Exception e) { return d; }
    }
    private static boolean bool(JsonObject b, String k, boolean d) {
        try { return b != null && b.has(k) ? b.get(k).getAsBoolean() : d; } catch (Exception e) { return d; }
    }

    public static Map<String, Object> act(BotPlayer bot, String action, JsonObject body) {
        String name = bot.getPlayer().getGameProfile().getName();
        switch (action) {
            case "fuse_block" -> {
                var b = Directive.builder(DirectiveType.FUSE_BLOCK);
                // Optional explicit target; else the behavior uses the marked/looked-at block.
                if (body != null && body.has("x") && body.has("y") && body.has("z")) {
                    b.location(body.get("x").getAsDouble(), body.get("y").getAsDouble(), body.get("z").getAsDouble());
                }
                String role = str(body, "role", "");
                if (!role.isEmpty()) b.extra("role", role);
                String mode = str(body, "mode", "");
                if (!mode.isEmpty()) b.extra("mode", mode);
                bot.getBrain().setDirective(b.build());
                return Map.of("ok", true, "queued", "FUSE_BLOCK");
            }
            case "unfuse_block" -> {
                bot.getBrain().setDirective(Directive.builder(DirectiveType.UNFUSE_BLOCK).build());
                return Map.of("ok", true, "queued", "UNFUSE_BLOCK");
            }
            case "manage_fusion" -> {
                if (!Fusion.isFused(name)) return err("not fused with anything");
                FusionControl.Knobs k = FusionControl.get(name);
                if (body != null && body.has("rate")) k.targetRate = Math.max(0, Math.min(1, num(body, "rate", k.targetRate)));
                if (body != null && body.has("safe_mode")) k.safeMode = bool(body, "safe_mode", k.safeMode);
                if (body != null && body.has("divert")) k.divert = bool(body, "divert", k.divert);
                if (body != null && body.has("output_rate")) k.outputRate = Math.max(0, (long) num(body, "output_rate", k.outputRate));
                if (body != null && body.has("sim_mode")) k.simMode = "training".equalsIgnoreCase(str(body, "sim_mode", k.simMode)) ? "training" : "inference";
                if (body != null && body.has("auto_matrix")) k.autoMatrix = bool(body, "auto_matrix", k.autoMatrix);
                if (body != null && body.has("mode")) {
                    Fusion.Mode m = "output".equalsIgnoreCase(str(body, "mode", "")) ? Fusion.Mode.OUTPUT : Fusion.Mode.CAPACITY;
                    Fusion.setMode(name, m);
                }
                Map<String, Object> out = new LinkedHashMap<>(FusionControl.toMap(name));
                out.put("ok", true);
                var st = Fusion.of(name);
                if (st != null) out.put("mode", st.mode().name());
                return out;
            }
            case "fusion" -> {
                Map<String, Object> info = bot.getFusionInfo();
                Map<String, Object> out = new LinkedHashMap<>();
                out.put("ok", true);
                out.put("fused", info != null);
                if (info != null) out.put("fusion", info);
                else {
                    var pos = bot.blockLookingAt();
                    if (pos != null && bot.getPlayer().level() instanceof net.minecraft.server.level.ServerLevel sl) {
                        out.put("looking_at", Map.of(
                                "x", pos.getX(), "y", pos.getY(), "z", pos.getZ(),
                                "block", com.sigmastrain.aiplayermod.compat.blockfusion.BlockFusionCompat.blockName(sl, pos),
                                "role", com.sigmastrain.aiplayermod.compat.blockfusion.BlockFusionCompat.roleOf(sl, pos).name()));
                    }
                }
                return out;
            }
            default -> { return err("unknown fusion action " + action); }
        }
    }
}
