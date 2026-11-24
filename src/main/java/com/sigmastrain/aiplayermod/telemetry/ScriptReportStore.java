package com.sigmastrain.aiplayermod.telemetry;

import com.google.gson.JsonObject;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * The latest script report per bot, and nothing older (coded-agents 5.7).
 *
 * <p>Deliberately latest-only. {@code design.md} rules out mod-side history, and
 * the sender compensates by carrying {@code previous_code_hours} on the one
 * report that shows a fall, so history is never needed to read one. Keeping a
 * list here would be the thing that made the design's reset rule unworkable.
 *
 * <p>Every report carries the sender's own {@code observed_at}, and staleness is
 * judged against THAT, not against the mod's clock. The two are different hosts
 * in general; dating a report by the receiver's clock would make a clock skew
 * look like a dead agent.
 *
 * <p>This class holds no server state and touches no world, so it is safe to
 * read from the HTTP pool -- unlike anything that would need a server-thread hop.
 */
public final class ScriptReportStore {

    /** A report is stale after this long without a fresh one. */
    public static final long STALE_AFTER_MS = 45_000L;

    /** The receiver refuses a figure beyond this, rather than trusting it. */
    public static final double MAX_CODE_HOURS = 100_000.0;

    private static final Map<String, Entry> LATEST = new ConcurrentHashMap<>();

    private ScriptReportStore() {}

    /**
     * One retained report. {@code previousCodeHours} is {@code null} when the
     * sender omitted it, which means "no fall claimed" -- absence, not zero.
     */
    public record Entry(
            String scriptState,
            double codeHours,
            Double previousCodeHours,
            long ticks,
            String observedAt,
            String revision,
            long receivedAtMillis) {

        public boolean staleAt(long nowMillis) {
            // The SENDER's stamp decides, as the design requires: dating a
            // report by the receiver's clock would make clock skew look like a
            // dead agent. `receivedAtMillis` is a FALLBACK for an unparseable
            // stamp, not a floor -- `Math.max` here was my bug: it let a fresh
            // receipt launder an hour-old stamp into looking current. The
            // no-laundering guarantee comes from the parser instead: a stamp
            // that does not parse is refused at record() time, so the fallback
            // never has to defend against a hostile one.
            long observed = observedAtMillis(this);
            long basis = observed >= 0 ? observed : receivedAtMillis;
            return (nowMillis - basis) > STALE_AFTER_MS;
        }

        private static long observedAtMillis(Entry e) {
            return parseIso(e.observedAt());
        }
    }

    /**
     * Records a report. Returns {@code false} if the bot is unknown, so the
     * caller can answer 404 rather than inventing a status for a name nothing
     * owns.
     *
     * <p>Note this does NOT reject a report that appears older than the one it
     * replaces: an out-of-order arrival is a fact about the network, and dropping
     * it would leave the store showing a value the sender has already superseded.
     */
    public static boolean record(String botName, JsonObject body, long nowMillis) {
        if (botName == null || botName.isEmpty()) return false;
        String state = stringOr(body, "script_state", "");
        String observedAt = stringOr(body, "observed_at", "");
        if (state.isEmpty() || observedAt.isEmpty()) return false;
        // A stamp the sender's own format cannot produce is refused here rather
        // than stored and later guessed at. This is what lets staleAt() trust
        // the parsed stamp instead of defending against a hostile one.
        if (parseIso(observedAt) < 0) return false;

        double hours = body.has("code_hours") ? body.get("code_hours").getAsDouble() : -1;
        if (hours < 0 || !Double.isFinite(hours) || hours > MAX_CODE_HOURS) return false;

        Double previous = null;
        if (body.has("previous_code_hours")
                && !body.get("previous_code_hours").isJsonNull()) {
            double p = body.get("previous_code_hours").getAsDouble();
            if (!Double.isFinite(p) || p < 0 || p > MAX_CODE_HOURS) return false;
            previous = p;
        }
        long ticks = body.has("ticks") ? body.get("ticks").getAsLong() : 0L;
        if (ticks < 0) return false;

        LATEST.put(botName, new Entry(state, hours, previous, ticks, observedAt,
                stringOr(body, "revision", ""), nowMillis));
        return true;
    }

    /** The retained report for {@code botName}, or {@code null}. */
    public static Entry get(String botName) {
        return LATEST.get(botName);
    }

    /** Everything retained, for the status surface. Insertion order, not recency. */
    public static Map<String, Entry> all() {
        return new LinkedHashMap<>(LATEST);
    }

    /** Test seam: forget everything. */
    public static void clear() {
        LATEST.clear();
    }

    /**
     * How this report reads to a player: {@code script}, {@code fallback} or
     * {@code stale}. A stale report's own state is not shown, because showing
     * "script" for an agent that stopped reporting is the failure the staleness
     * rule exists to prevent.
     */
    public static String displayState(Entry e, long nowMillis) {
        if (e == null) return "none";
        if (e.staleAt(nowMillis)) return "stale";
        return switch (e.scriptState()) {
            case "script" -> "script";
            case "fallback_timeout", "fallback_refused" -> "fallback";
            case "stalled" -> "stalled";
            case "stopped" -> "stopped";
            default -> "none";
        };
    }

    /** A JSON view of one bot's report for the status surface. */
    public static JsonObject toJson(String botName, Entry e, long nowMillis) {
        JsonObject o = new JsonObject();
        o.addProperty("bot", botName);
        o.addProperty("state", displayState(e, nowMillis));
        if (e != null) {
            o.addProperty("script_state", e.scriptState());
            o.addProperty("code_hours", e.codeHours());
            if (e.previousCodeHours() != null) {
                o.addProperty("previous_code_hours", e.previousCodeHours());
            }
            o.addProperty("ticks", e.ticks());
            o.addProperty("observed_at", e.observedAt());
            o.addProperty("revision", e.revision());
            o.addProperty("stale", e.staleAt(nowMillis));
        }
        return o;
    }

    private static String stringOr(JsonObject o, String key, String dflt) {
        return o.has(key) && !o.get(key).isJsonNull() ? o.get(key).getAsString() : dflt;
    }

    /**
     * Parses the sender's {@code %Y-%m-%dT%H:%M:%SZ} into epoch millis, or -1.
     * Hand-rolled rather than pulling in a formatter: the shape is fixed by the
     * sender's own test, and a lenient parser would accept stamps the sender
     * cannot produce.
     */
    static long parseIso(String s) {
        if (s == null || s.length() != 20 || s.charAt(4) != '-'
                || s.charAt(7) != '-' || s.charAt(10) != 'T'
                || s.charAt(13) != ':' || s.charAt(16) != ':' || s.charAt(19) != 'Z') {
            return -1L;
        }
        try {
            int y = Integer.parseInt(s.substring(0, 4));
            int mo = Integer.parseInt(s.substring(5, 7));
            int d = Integer.parseInt(s.substring(8, 10));
            int h = Integer.parseInt(s.substring(11, 13));
            int mi = Integer.parseInt(s.substring(14, 16));
            int se = Integer.parseInt(s.substring(17, 19));
            if (mo < 1 || mo > 12 || d < 1 || d > 31 || h > 23 || mi > 59 || se > 60) {
                return -1L;
            }
            return java.time.Instant.parse(s).toEpochMilli();
        } catch (RuntimeException e) {
            return -1L;
        }
    }
}
