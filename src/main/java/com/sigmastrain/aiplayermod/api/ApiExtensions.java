package com.sigmastrain.aiplayermod.api;

import com.sun.net.httpserver.HttpHandler;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * Server-API seam: other mods mount HTTP routes into the bot API so the
 * agent reaches them through the one host:port it already knows. Hive
 * uses this for unit gestation (SPAWN_DRONES rides the same order lane
 * as every other directive). Register during mod construction — routes
 * are bound once when the server starts.
 */
public final class ApiExtensions {

    private ApiExtensions() {}

    public record Route(String path, HttpHandler handler) {}

    private static final List<Route> ROUTES = new ArrayList<>();

    public static synchronized void register(String path, HttpHandler handler) {
        ROUTES.add(new Route(path, handler));
    }

    public static synchronized List<Route> routes() {
        return Collections.unmodifiableList(new ArrayList<>(ROUTES));
    }
}
