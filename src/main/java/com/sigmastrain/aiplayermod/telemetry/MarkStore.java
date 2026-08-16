package com.sigmastrain.aiplayermod.telemetry;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * The "marked block" buffer: the operator points at a block, taps the hotkey,
 * and the position lands here for the agent to resolve as "the marked area".
 *
 * <p>Single-owner hive, so one current mark suffices; a fresh mark overwrites.
 * Purely a holder of plain values — no Minecraft types — so the HTTP seam and
 * the C2S packet handler both read it without a server-thread hop.
 */
public final class MarkStore {

    private MarkStore() {}

    private static volatile boolean set;
    private static volatile String player = "";
    private static volatile String dimension = "";
    private static volatile int x;
    private static volatile int y;
    private static volatile int z;

    public static synchronized void set(String playerName, String dim, int px, int py, int pz) {
        player = playerName == null ? "" : playerName;
        dimension = dim == null ? "" : dim;
        x = px;
        y = py;
        z = pz;
        set = true;
    }

    public static synchronized boolean has() {
        return set;
    }

    public static synchronized int x() { return x; }
    public static synchronized int y() { return y; }
    public static synchronized int z() { return z; }
    public static synchronized String dimension() { return dimension; }
    public static synchronized String player() { return player; }

    /** The mark as a JSON-ready map: {@code {"marked":true, x,y,z,dimension,player}}
     *  or {@code {"marked":false}} when nothing has been marked yet. */
    public static synchronized Map<String, Object> toMap() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("marked", set);
        if (set) {
            m.put("player", player);
            m.put("dimension", dimension);
            m.put("x", x);
            m.put("y", y);
            m.put("z", z);
        }
        return m;
    }
}
