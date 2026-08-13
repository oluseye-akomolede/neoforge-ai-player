package com.sigmastrain.aiplayermod.telemetry;

/**
 * Directive schemas, pushed by the agent at startup.
 *
 * <p>The agent owns the directive vocabulary (`agent/dashboard/schemas.py`);
 * the mod and overlay must not hardcode a copy that drifts. On boot the
 * agent POSTs the schemas as one JSON document; the overlay's directive
 * builder renders its form from it. Version-bumped so subscribed clients
 * get exactly one resend per push.
 */
public final class SchemaStore {

    private SchemaStore() {}

    private static volatile String json = "";
    private static volatile long version = 0;

    public static void put(String schemasJson) {
        json = schemasJson == null ? "" : schemasJson;
        version++;
    }

    public static String json() { return json; }

    public static long version() { return version; }

    public static boolean isEmpty() { return json.isEmpty(); }
}
