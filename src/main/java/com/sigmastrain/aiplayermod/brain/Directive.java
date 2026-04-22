package com.sigmastrain.aiplayermod.brain;

import java.util.LinkedHashMap;
import java.util.Map;

public class Directive {
    private final DirectiveType type;
    private final String target;
    private final int radius;
    private final int count;
    private final double x, y, z;
    private final boolean hasLocation;
    private final Map<String, String> extra;

    private DirectiveStatus status = DirectiveStatus.ACTIVE;
    private String failureReason;

    private Directive(Builder builder) {
        this.type = builder.type;
        this.target = builder.target;
        this.radius = builder.radius;
        this.count = builder.count;
        this.x = builder.x;
        this.y = builder.y;
        this.z = builder.z;
        this.hasLocation = builder.hasLocation;
        this.extra = builder.extra;
    }

    public DirectiveType getType() { return type; }
    public String getTarget() { return target; }
    public int getRadius() { return radius; }
    public int getCount() { return count; }
    public double getX() { return x; }
    public double getY() { return y; }
    public double getZ() { return z; }
    public boolean hasLocation() { return hasLocation; }
    public Map<String, String> getExtra() { return extra; }
    public DirectiveStatus getStatus() { return status; }
    public String getFailureReason() { return failureReason; }

    public void complete() { this.status = DirectiveStatus.COMPLETED; }

    public void fail(String reason) {
        this.status = DirectiveStatus.FAILED;
        this.failureReason = reason;
    }

    public void cancel() { this.status = DirectiveStatus.CANCELLED; }

    public Map<String, Object> toMap() {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("type", type.name());
        map.put("status", status.name());
        if (target != null) map.put("target", target);
        if (hasLocation) {
            map.put("x", x);
            map.put("y", y);
            map.put("z", z);
        }
        if (radius > 0) map.put("radius", radius);
        if (count > 0) map.put("count", count);
        if (!extra.isEmpty()) map.put("extra", extra);
        if (failureReason != null) map.put("failure_reason", failureReason);
        return map;
    }

    public static Builder builder(DirectiveType type) {
        return new Builder(type);
    }

    public static class Builder {
        private final DirectiveType type;
        private String target;
        private int radius = 128;
        private int count = -1;
        private double x, y, z;
        private boolean hasLocation = false;
        private final Map<String, String> extra = new LinkedHashMap<>();

        private Builder(DirectiveType type) {
            this.type = type;
        }

        public Builder target(String target) { this.target = target; return this; }
        public Builder radius(int radius) { this.radius = radius; return this; }
        public Builder count(int count) { this.count = count; return this; }

        public Builder location(double x, double y, double z) {
            this.x = x; this.y = y; this.z = z;
            this.hasLocation = true;
            return this;
        }

        public Builder extra(String key, String value) {
            this.extra.put(key, value);
            return this;
        }

        public Directive build() { return new Directive(this); }
    }
}
