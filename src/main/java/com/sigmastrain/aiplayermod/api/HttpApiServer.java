package com.sigmastrain.aiplayermod.api;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.sigmastrain.aiplayermod.AIPlayerMod;
import com.sigmastrain.aiplayermod.actions.*;
import com.sigmastrain.aiplayermod.actions.CraftAction;
import com.sigmastrain.aiplayermod.actions.CollectAction;
import com.sigmastrain.aiplayermod.actions.DropAction;
import com.sigmastrain.aiplayermod.actions.EquipAction;
import com.sigmastrain.aiplayermod.actions.FollowAction;
import com.sigmastrain.aiplayermod.actions.UseItemAction;
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

        switch (action) {
            case "status" -> sendJson(exchange, 200, bot.getStatus());
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
                BotManager.getServer().execute(() ->
                        bot.getActionQueue().enqueue(new GoToAction(x, y, z, dist)));
                sendJson(exchange, 200, Map.of("status", "moving", "target", Map.of("x", x, "y", y, "z", z)));
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
                BotManager.getServer().execute(() -> bot.teleport(x, y, z));
                sendJson(exchange, 200, Map.of("status", "teleported"));
            }
            case "inventory" -> sendJson(exchange, 200, Map.of("inventory", bot.getInventory()));
            case "entities" -> {
                double radius = body.has("radius") ? body.get("radius").getAsDouble() : 16.0;
                sendJson(exchange, 200, Map.of("entities", bot.getNearbyEntities(radius)));
            }
            case "blocks" -> {
                int radius = body.has("radius") ? body.get("radius").getAsInt() : 8;
                sendJson(exchange, 200, Map.of("blocks", bot.getNearbyBlocks(radius)));
            }
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
                BotManager.getServer().execute(() ->
                        bot.getActionQueue().enqueue(new EquipAction(slot)));
                sendJson(exchange, 200, Map.of("status", "equipped", "slot", slot));
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
                BotManager.getServer().execute(() ->
                        bot.getActionQueue().enqueue(new FollowAction(target, dist, radius)));
                sendJson(exchange, 200, Map.of("status", "following", "target", target));
            }
            case "find_blocks" -> {
                String block = body.get("block").getAsString();
                int radius = body.has("radius") ? body.get("radius").getAsInt() : 32;
                int max = body.has("max") ? body.get("max").getAsInt() : 10;
                sendJson(exchange, 200, Map.of("blocks", bot.findBlocks(block, radius, max)));
            }
            case "find_entities" -> {
                String target = body.get("target").getAsString();
                double radius = body.has("radius") ? body.get("radius").getAsDouble() : 32.0;
                sendJson(exchange, 200, Map.of("entities", bot.findEntities(target, radius)));
            }
            case "swap" -> {
                int from = body.get("from").getAsInt();
                int to = body.get("to").getAsInt();
                BotManager.getServer().execute(() -> bot.swapSlot(from, to));
                sendJson(exchange, 200, Map.of("status", "swapped", "from", from, "to", to));
            }
            case "stop" -> {
                BotManager.getServer().execute(() -> bot.getActionQueue().clear());
                sendJson(exchange, 200, Map.of("status", "stopped"));
            }
            default -> sendJson(exchange, 400, Map.of("error", "Unknown action: " + action));
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
