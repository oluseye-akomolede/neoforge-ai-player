package com.sigmastrain.aiplayermod.brain;

import java.util.*;

public class ProgressReport {
    private final Map<String, Integer> counters = new LinkedHashMap<>();
    private final List<String> eventLog = new ArrayList<>();
    private final List<Map<String, Object>> scanData = new ArrayList<>();
    private String phase = "idle";
    private String failureReason;

    private static final int MAX_EVENTS = 50;
    private static final int MAX_SCAN_DATA = 500;

    public void increment(String key) {
        counters.merge(key, 1, Integer::sum);
    }

    public void increment(String key, int amount) {
        counters.merge(key, amount, Integer::sum);
    }

    public int getCounter(String key) {
        return counters.getOrDefault(key, 0);
    }

    public void setPhase(String phase) {
        this.phase = phase;
    }

    public String getPhase() {
        return phase;
    }

    public void logEvent(String event) {
        eventLog.add(event);
        if (eventLog.size() > MAX_EVENTS) {
            eventLog.remove(0);
        }
    }

    public void recordBlock(int x, int y, int z, String blockId) {
        if (scanData.size() < MAX_SCAN_DATA) {
            scanData.add(Map.of("x", x, "y", y, "z", z, "block", blockId));
        }
    }

    public List<Map<String, Object>> drainScanData() {
        if (scanData.isEmpty()) return List.of();
        var copy = new ArrayList<>(scanData);
        scanData.clear();
        return copy;
    }

    public void setFailureReason(String reason) {
        this.failureReason = reason;
    }

    public void reset() {
        counters.clear();
        eventLog.clear();
        scanData.clear();
        phase = "idle";
        failureReason = null;
    }

    public Map<String, Object> toMap() {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("phase", phase);
        if (!counters.isEmpty()) map.put("counters", new LinkedHashMap<>(counters));
        if (!eventLog.isEmpty()) {
            int start = Math.max(0, eventLog.size() - 10);
            map.put("recent_events", new ArrayList<>(eventLog.subList(start, eventLog.size())));
        }
        if (failureReason != null) map.put("failure_reason", failureReason);
        if (!scanData.isEmpty()) map.put("scan_data_pending", scanData.size());
        return map;
    }
}
