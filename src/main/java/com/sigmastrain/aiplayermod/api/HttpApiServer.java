package com.sigmastrain.aiplayermod.api;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.actions.*;
import com.sigmastrain.aiplayermod.bot.BotManager;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.*;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.Executors;

public class HttpApiServer {
    private final int port;
    private final String apiKey;
    private final Gson gson = new GsonBuilder().setPrettyPrinting().create();
    private HttpServer server;

    public HttpApiServer(int port, String apiKey) {
        this.port = port;
        this.apiKey = apiKey;
    }

    public void start() {
        try {
            server = HttpServer.create(new InetSocketAddress("0.0.0.0", port), 0);
            server.setExecutor(Executors.newFixedThreadPool(4));

            server.createContext("/health", this::handleHealth);
            server.createContext("/bots", this::handleBots);
            server.createContext("/bot/", this::handleBotAction);

            server.start();
        } catch (IOException e) {
            AIPlayerMod.LOGGER.error("Failed to start API server on port {}", port, e);
        }
    }

    public void stop() {
        if (server != null) {
            server.stop(0);
        }
    }

    private boolean checkAuth(HttpExchange exchange) throws IOException {
        if (apiKey == null || apiKey.isEmpty()) return true;
        String provided = exchange.getRequestHeaders().getFirst("X-Api-Key");
        if (!apiKey.equals(provided)) {
            sendJson(exchange, 401, Map.of("error", "Invalid API key"));
            return false;
        }
        return true;
    }

    // ── /health ──

    private void handleHealth(HttpExchange exchange) throws IOException {
        sendJson(exchange, 200, Map.of(
                "status", "ok",
                "mod", AIPlayerMod.MOD_ID,
                "bots", BotManager.getAllBots().size()
        ));
    }

    // ── /bots ── (GET = list, POST = spawn)

    private void handleBots(HttpExchange exchange) throws IOException {
        if (!checkAuth(exchange)) return;

        if ("GET".equals(exchange.getRequestMethod())) {
            List<Map<String, Object>> botList = new ArrayList<>();
            for (var entry : BotManager.getAllBots().entrySet()) {
                botList.add(entry.getValue().getStatus());
            }
            sendJson(exchange, 200, Map.of("bots", botList));
        } else if ("POST".equals(exchange.getRequestMethod())) {
            JsonObject body = readBody(exchange);
            String name = body.has("name") ? body.get("name").getAsString() : "AIBot";
            try {
                BotManager.getServer().execute(() -> BotManager.spawn(name));
                sendJson(exchange, 200, Map.of("status", "spawned", "name", name));
            } catch (Exception e) {
                sendJson(exchange, 500, Map.of("error", e.getMessage()));
            }
        } else if ("DELETE".equals(exchange.getRequestMethod())) {
            JsonObject body = readBody(exchange);
            String name = body.has("name") ? body.get("name").getAsString() : "";
            BotManager.getServer().execute(() -> BotManager.despawn(name));
            sendJson(exchange, 200, Map.of("status", "despawned", "name", name));
        } else {
            sendJson(exchange, 405, Map.of("error", "Method not allowed"));
        }
    }

    // ── /bot/{name}/{action} ──

    private void handleBotAction(HttpExchange exchange) throws IOException {
        if (!checkAuth(exchange)) return;

        String path = exchange.getRequestURI().getPath();
        // /bot/{name}/{action}
        String[] parts = path.split("/");
        if (parts.length < 3) {
            sendJson(exchange, 400, Map.of("error", "Expected /bot/{name}/{action}"));
            return;
        }
        String botName = parts[2];
        String action = parts.length >= 4 ? parts[3] : "status";

        BotPlayer bot = BotManager.getBot(botName);
        if (bot == null) {
            sendJson(exchange, 404, Map.of("error", "Bot not found: " + botName));
            return;
        }

        JsonObject body = "GET".equals(exchange.getRequestMethod()) ? new JsonObject() : readBody(exchange);

        try {
        switch (action) {
            case "status" -> sendJson(exchange, 200, bot.getCachedStatus());
            case "chat" -> {
                String message = body.get("message").getAsString();
                BotManager.getServer().execute(() -> bot.chat(message));
                sendJson(exchange, 200, Map.of("status", "sent"));
            }
            case "goto" -> {
                double x = body.get("x").getAsDouble();
                double y = body.get("y").getAsDouble();
                double z = body.get("z").getAsDouble();
                double dist = body.has("distance") ? body.get("distance").getAsDouble() : 2.0;
                boolean sprint = body.has("sprint") && body.get("sprint").getAsBoolean();
                BotManager.getServer().execute(() ->
                        bot.getActionQueue().enqueue(new GoToAction(x, y, z, dist, sprint)));
                sendJson(exchange, 200, Map.of("status", "moving", "target", Map.of("x", x, "y", y, "z", z)));
            }
            case "fly_to" -> {
                double x = body.get("x").getAsDouble();
                double y = body.get("y").getAsDouble();
                double z = body.get("z").getAsDouble();
                double dist = body.has("distance") ? body.get("distance").getAsDouble() : 2.0;
                double speed = body.has("speed") ? body.get("speed").getAsDouble() : 0.5;
                BotManager.getServer().execute(() ->
                        bot.getActionQueue().enqueue(new FlyToAction(x, y, z, dist, speed)));
                sendJson(exchange, 200, Map.of("status", "flying", "target", Map.of("x", x, "y", y, "z", z)));
            }
            case "attack" -> {
                String target = body.get("target").getAsString();
                double radius = body.has("radius") ? body.get("radius").getAsDouble() : 16.0;
                BotManager.getServer().execute(() ->
                        bot.getActionQueue().enqueue(new AttackAction(target, radius)));
                sendJson(exchange, 200, Map.of("status", "attacking", "target", target));
            }
            case "mine" -> {
                int x = body.get("x").getAsInt();
                int y = body.get("y").getAsInt();
                int z = body.get("z").getAsInt();
                BotManager.getServer().execute(() ->
                        bot.getActionQueue().enqueue(new MineBlockAction(x, y, z)));
                sendJson(exchange, 200, Map.of("status", "mining", "position", Map.of("x", x, "y", y, "z", z)));
            }
            case "place" -> {
                int x = body.get("x").getAsInt();
                int y = body.get("y").getAsInt();
                int z = body.get("z").getAsInt();
                BotManager.getServer().execute(() ->
                        bot.getActionQueue().enqueue(new PlaceBlockAction(x, y, z)));
                sendJson(exchange, 200, Map.of("status", "placing", "position", Map.of("x", x, "y", y, "z", z)));
            }
            case "look" -> {
                double x = body.get("x").getAsDouble();
                double y = body.get("y").getAsDouble();
                double z = body.get("z").getAsDouble();
                BotManager.getServer().execute(() -> bot.lookAt(x, y, z));
                sendJson(exchange, 200, Map.of("status", "looking"));
            }
            case "teleport" -> {
                double x = body.get("x").getAsDouble();
                double y = body.get("y").getAsDouble();
                double z = body.get("z").getAsDouble();
                String dim = body.has("dimension") ? body.get("dimension").getAsString() : null;
                if (dim != null) {
                    var dimKey = net.minecraft.resources.ResourceKey.create(
                            net.minecraft.core.registries.Registries.DIMENSION,
                            net.minecraft.resources.ResourceLocation.parse(dim));
                    var future = new java.util.concurrent.CompletableFuture<Boolean>();
                    BotManager.getServer().execute(() -> {
                        try { future.complete(bot.teleportToDimension(dimKey, x, y, z)); }
                        catch (Exception e) { future.complete(false); AIPlayerMod.LOGGER.error("teleportDimension error", e); }
                    });
                    boolean ok = future.join();
                    sendJson(exchange, ok ? 200 : 500, Map.of("status", ok ? "teleported" : "failed", "dimension", dim));
                } else {
                    BotManager.getServer().execute(() -> bot.teleport(x, y, z));
                    sendJson(exchange, 200, Map.of("status", "teleported"));
                }
            }
            case "inventory" -> sendJson(exchange, 200, Map.of("inventory", bot.getCachedInventory()));
            case "entities" -> sendJson(exchange, 200, Map.of("entities", bot.getCachedEntities()));
            case "blocks" -> sendJson(exchange, 200, Map.of("blocks", bot.getCachedBlocks()));
            case "actions" -> sendJson(exchange, 200, Map.of(
                    "current", bot.getActionQueue().currentAction(),
                    "queued", bot.getActionQueue().queueSize()
            ));
            case "craft" -> {
                String item = body.get("item").getAsString();
                int count = body.has("count") ? body.get("count").getAsInt() : 1;
                BotManager.getServer().execute(() ->
                        bot.getActionQueue().enqueue(new CraftAction(item, count)));
                sendJson(exchange, 200, Map.of("status", "crafting", "item", item, "count", count));
            }
            case "equip" -> {
                int slot = body.get("slot").getAsInt();
                var equipFuture = new java.util.concurrent.CompletableFuture<Map<String, Object>>();
                BotManager.getServer().execute(() -> {
                    new EquipAction(slot).tick(bot);
                    var equip = bot.getEquipment();
                    equipFuture.complete(Map.of("status", "equipped", "slot", slot, "equipment", equip));
                });
                try {
                    sendJson(exchange, 200, equipFuture.get(5, java.util.concurrent.TimeUnit.SECONDS));
                } catch (Exception e) {
                    sendJson(exchange, 200, Map.of("status", "equipped", "slot", slot));
                }
            }
            case "use" -> {
                BotManager.getServer().execute(() ->
                        bot.getActionQueue().enqueue(new UseItemAction()));
                sendJson(exchange, 200, Map.of("status", "using_item"));
            }
            case "drop" -> {
                int slot = body.get("slot").getAsInt();
                int count = body.has("count") ? body.get("count").getAsInt() : 64;
                BotManager.getServer().execute(() ->
                        bot.getActionQueue().enqueue(new DropAction(slot, count)));
                sendJson(exchange, 200, Map.of("status", "dropping", "slot", slot));
            }
            case "collect" -> {
                double radius = body.has("radius") ? body.get("radius").getAsDouble() : 16.0;
                BotManager.getServer().execute(() ->
                        bot.getActionQueue().enqueue(new CollectAction(radius)));
                sendJson(exchange, 200, Map.of("status", "collecting", "radius", radius));
            }
            case "follow" -> {
                String target = body.get("target").getAsString();
                double dist = body.has("distance") ? body.get("distance").getAsDouble() : 3.0;
                double radius = body.has("radius") ? body.get("radius").getAsDouble() : 32.0;
                boolean fSprint = body.has("sprint") && body.get("sprint").getAsBoolean();
                BotManager.getServer().execute(() ->
                        bot.getActionQueue().enqueue(new FollowAction(target, dist, radius, fSprint)));
                sendJson(exchange, 200, Map.of("status", "following", "target", target));
            }
            case "find_blocks" -> {
                String block = body.get("block").getAsString();
                int radius = body.has("radius") ? body.get("radius").getAsInt() : 32;
                int max = body.has("max") ? body.get("max").getAsInt() : 10;
                var blockFuture = new java.util.concurrent.CompletableFuture<List<Map<String, Object>>>();
                BotManager.getServer().execute(() -> {
                    try { blockFuture.complete(bot.findBlocks(block, radius, max)); }
                    catch (Exception e) { blockFuture.complete(List.of()); AIPlayerMod.LOGGER.error("findBlocks error", e); }
                });
                sendJson(exchange, 200, Map.of("blocks", blockFuture.join()));
            }
            case "find_entities" -> {
                String target = body.get("target").getAsString();
                double radius = body.has("radius") ? body.get("radius").getAsDouble() : 32.0;
                var entityFuture = new java.util.concurrent.CompletableFuture<List<Map<String, Object>>>();
                BotManager.getServer().execute(() -> {
                    try { entityFuture.complete(bot.findEntities(target, radius)); }
                    catch (Exception e) { entityFuture.complete(List.of()); AIPlayerMod.LOGGER.error("findEntities error", e); }
                });
                sendJson(exchange, 200, Map.of("entities", entityFuture.join()));
            }
            case "swap" -> {
                int from = body.get("from").getAsInt();
                int to = body.get("to").getAsInt();
                BotManager.getServer().execute(() -> bot.swapSlot(from, to));
                sendJson(exchange, 200, Map.of("status", "swapped", "from", from, "to", to));
            }
            case "chat_inbox" -> {
                sendJson(exchange, 200, Map.of("messages", bot.drainChatInbox()));
            }
            case "inject_chat" -> {
                String sender = body.get("sender").getAsString();
                String message = body.get("message").getAsString();
                bot.addChatMessage(sender, message);
                sendJson(exchange, 200, Map.of("status", "injected", "sender", sender, "message", message));
            }
            case "container" -> {
                int x = body.get("x").getAsInt();
                int y = body.get("y").getAsInt();
                int z = body.get("z").getAsInt();
                var contFuture = new java.util.concurrent.CompletableFuture<List<Map<String, Object>>>();
                BotManager.getServer().execute(() -> {
                    try { contFuture.complete(bot.readContainer(x, y, z)); }
                    catch (Exception e) { contFuture.complete(List.of()); AIPlayerMod.LOGGER.error("readContainer error", e); }
                });
                sendJson(exchange, 200, Map.of("items", contFuture.join(), "position", Map.of("x", x, "y", y, "z", z)));
            }
            case "container_insert" -> {
                int x = body.get("x").getAsInt();
                int y = body.get("y").getAsInt();
                int z = body.get("z").getAsInt();
                int slot = body.get("slot").getAsInt();
                int count = body.has("count") ? body.get("count").getAsInt() : 64;
                var insFuture = new java.util.concurrent.CompletableFuture<Map<String, Object>>();
                BotManager.getServer().execute(() -> {
                    try { insFuture.complete(bot.insertIntoContainer(x, y, z, slot, count)); }
                    catch (Exception e) { insFuture.complete(Map.of("error", e.getMessage())); AIPlayerMod.LOGGER.error("insertContainer error", e); }
                });
                sendJson(exchange, 200, insFuture.join());
            }
            case "container_extract" -> {
                int x = body.get("x").getAsInt();
                int y = body.get("y").getAsInt();
                int z = body.get("z").getAsInt();
                int count = body.has("count") ? body.get("count").getAsInt() : 64;
                var extFuture = new java.util.concurrent.CompletableFuture<Map<String, Object>>();
                if (body.has("item")) {
                    String item = body.get("item").getAsString();
                    BotManager.getServer().execute(() -> {
                        try { extFuture.complete(bot.extractFromContainerByItem(x, y, z, item, count)); }
                        catch (Exception e) { extFuture.complete(Map.of("error", e.getMessage())); AIPlayerMod.LOGGER.error("extractContainer error", e); }
                    });
                } else {
                    int slot = body.get("slot").getAsInt();
                    BotManager.getServer().execute(() -> {
                        try { extFuture.complete(bot.extractFromContainer(x, y, z, slot, count)); }
                        catch (Exception e) { extFuture.complete(Map.of("error", e.getMessage())); AIPlayerMod.LOGGER.error("extractContainer error", e); }
                    });
                }
                sendJson(exchange, 200, extFuture.join());
            }
            case "list_recipes" -> {
                String filter = body.has("filter") ? body.get("filter").getAsString() : "";
                boolean craftableOnly = body.has("craftable_only") && body.get("craftable_only").getAsBoolean();
                var recFuture = new java.util.concurrent.CompletableFuture<List<Map<String, Object>>>();
                BotManager.getServer().execute(() -> {
                    try { recFuture.complete(bot.listRecipes(filter, craftableOnly)); }
                    catch (Exception e) { recFuture.complete(List.of()); AIPlayerMod.LOGGER.error("listRecipes error", e); }
                });
                sendJson(exchange, 200, Map.of("recipes", recFuture.join()));
            }
            case "craft_chain" -> {
                String item = body.get("item").getAsString();
                int count = body.has("count") ? body.get("count").getAsInt() : 1;
                BotManager.getServer().execute(() ->
                        bot.getActionQueue().enqueue(new CraftChainAction(item, count)));
                sendJson(exchange, 200, Map.of("status", "crafting_chain", "item", item, "count", count));
            }
            case "equipment" -> {
                var eqFuture = new java.util.concurrent.CompletableFuture<Map<String, Object>>();
                BotManager.getServer().execute(() -> {
                    try { eqFuture.complete(bot.getEquipment()); }
                    catch (Exception e) { eqFuture.complete(Map.of("error", e.getMessage())); }
                });
                sendJson(exchange, 200, eqFuture.join());
            }
            case "extended_inventory" -> {
                var extInvFuture = new java.util.concurrent.CompletableFuture<List<Map<String, Object>>>();
                BotManager.getServer().execute(() -> {
                    try { extInvFuture.complete(bot.getExtendedInventoryItems()); }
                    catch (Exception e) { extInvFuture.complete(List.of()); }
                });
                sendJson(exchange, 200, Map.of("items", extInvFuture.join()));
            }
            case "combat_mode" -> {
                double radius = body.has("radius") ? body.get("radius").getAsDouble() : 24.0;
                boolean hostileOnly = !body.has("hostile_only") || body.get("hostile_only").getAsBoolean();
                String target = body.has("target") ? body.get("target").getAsString() : null;
                BotManager.getServer().execute(() -> {
                    bot.getActionQueue().clear();
                    bot.getActionQueue().enqueue(new CombatModeAction(radius, hostileOnly, target));
                });
                sendJson(exchange, 200, Map.of("status", "combat_mode", "radius", radius,
                        "hostile_only", hostileOnly, "target", target != null ? target : "any hostile"));
            }
            case "stop" -> {
                BotManager.getServer().execute(() -> bot.getActionQueue().clear());
                sendJson(exchange, 200, Map.of("status", "stopped"));
            }
            case "anvil" -> {
                int inputSlot = body.get("input_slot").getAsInt();
                int materialSlot = body.has("material_slot") ? body.get("material_slot").getAsInt() : -1;
                String newName = body.has("name") ? body.get("name").getAsString() : null;
                BotManager.getServer().execute(() ->
                        bot.getActionQueue().enqueue(new AnvilAction(inputSlot, materialSlot, newName)));
                sendJson(exchange, 200, Map.of("status", "anvil", "input_slot", inputSlot));
            }
            case "smithing" -> {
                int templateSlot = body.get("template_slot").getAsInt();
                int baseSlot = body.get("base_slot").getAsInt();
                int additionSlot = body.get("addition_slot").getAsInt();
                BotManager.getServer().execute(() ->
                        bot.getActionQueue().enqueue(new SmithingAction(templateSlot, baseSlot, additionSlot)));
                sendJson(exchange, 200, Map.of("status", "smithing",
                        "template", templateSlot, "base", baseSlot, "addition", additionSlot));
            }
            case "brew" -> {
                int ingredientSlot = body.get("ingredient_slot").getAsInt();
                int fuelSlot = body.has("fuel_slot") ? body.get("fuel_slot").getAsInt() : -1;
                var bottleArr = body.getAsJsonArray("bottle_slots");
                int[] bottleSlots = new int[bottleArr.size()];
                for (int i = 0; i < bottleArr.size(); i++) bottleSlots[i] = bottleArr.get(i).getAsInt();
                BotManager.getServer().execute(() ->
                        bot.getActionQueue().enqueue(new BrewAction(ingredientSlot, bottleSlots, fuelSlot)));
                sendJson(exchange, 200, Map.of("status", "brewing",
                        "ingredient", ingredientSlot, "bottles", bottleSlots.length));
            }
            case "enchant" -> {
                int itemSlot = body.get("item_slot").getAsInt();
                int lapisSlot = body.get("lapis_slot").getAsInt();
                int option = body.has("option") ? body.get("option").getAsInt() : 2;
                BotManager.getServer().execute(() ->
                        bot.getActionQueue().enqueue(new EnchantAction(itemSlot, lapisSlot, option)));
                sendJson(exchange, 200, Map.of("status", "enchanting",
                        "item_slot", itemSlot, "option", option));
            }
            case "xp" -> {
                String method = exchange.getRequestMethod();
                if ("GET".equals(method)) {
                    var player = bot.getPlayer();
                    sendJson(exchange, 200, Map.of(
                            "level", player.experienceLevel,
                            "progress", player.experienceProgress,
                            "total", player.totalExperience,
                            "next_level_cost", player.getXpNeededForNextLevel()
                    ));
                } else {
                    int amount = body.has("levels") ? body.get("levels").getAsInt() : 0;
                    int points = body.has("points") ? body.get("points").getAsInt() : 0;
                    BotManager.getServer().execute(() -> {
                        if (amount != 0) bot.getPlayer().giveExperienceLevels(amount);
                        if (points != 0) bot.getPlayer().giveExperiencePoints(points);
                    });
                    sendJson(exchange, 200, Map.of("status", "xp_updated",
                            "levels_added", amount, "points_added", points));
                }
            }
            default -> sendJson(exchange, 400, Map.of("error", "Unknown action: " + action));
        }
        } catch (Exception e) {
            AIPlayerMod.LOGGER.error("API error in /bot/{}/{}: {}", botName, action, e.getMessage(), e);
            try {
                sendJson(exchange, 500, Map.of("error", e.getMessage() != null ? e.getMessage() : e.getClass().getName()));
            } catch (Exception ignored) {}
        }
    }

    // ── Helpers ──

    private JsonObject readBody(HttpExchange exchange) {
        try (InputStream is = exchange.getRequestBody()) {
            String body = new String(is.readAllBytes(), StandardCharsets.UTF_8);
            if (body.isBlank()) return new JsonObject();
            return JsonParser.parseString(body).getAsJsonObject();
        } catch (Exception e) {
            return new JsonObject();
        }
    }

    private void sendJson(HttpExchange exchange, int status, Object data) throws IOException {
        String json = gson.toJson(data);
        byte[] bytes = json.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream os = exchange.getResponseBody()) {
            os.write(bytes);
        }
    }

    private void sendJson(HttpExchange exchange, int status, Map<String, Object> data) throws IOException {
        sendJson(exchange, status, (Object) data);
    }

}
