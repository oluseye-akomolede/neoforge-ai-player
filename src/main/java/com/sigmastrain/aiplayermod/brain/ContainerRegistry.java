package com.sigmastrain.aiplayermod.brain;

import net.minecraft.core.BlockPos;
import net.minecraft.resources.ResourceKey;
import net.minecraft.world.level.Level;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Thread-safe shared registry of bot-placed containers.
 * L1 behaviors read/write this in-memory map; L2 agent persists to PostgreSQL.
 * Exposed via HTTP API so the Python agent can sync on startup.
 */
public class ContainerRegistry {
    private static final ContainerRegistry INSTANCE = new ContainerRegistry();

    public static ContainerRegistry get() { return INSTANCE; }

    private final ConcurrentHashMap<Integer, ContainerEntry> containers = new ConcurrentHashMap<>();
    private final AtomicInteger nextId = new AtomicInteger(1);

    public int register(BlockPos pos, String dimension, String placedBy) {
        int id = nextId.getAndIncrement();
        containers.put(id, new ContainerEntry(id, pos, dimension, placedBy, System.currentTimeMillis()));
        return id;
    }

    public void registerWithId(int id, BlockPos pos, String dimension, String placedBy) {
        containers.put(id, new ContainerEntry(id, pos, dimension, placedBy, System.currentTimeMillis()));
        nextId.updateAndGet(current -> Math.max(current, id + 1));
    }

    public boolean remove(int id) {
        return containers.remove(id) != null;
    }

    public ContainerEntry get(int id) {
        return containers.get(id);
    }

    public List<ContainerEntry> getAll() {
        return new ArrayList<>(containers.values());
    }

    public List<ContainerEntry> getByDimension(String dimension) {
        List<ContainerEntry> result = new ArrayList<>();
        for (ContainerEntry e : containers.values()) {
            if (e.dimension().equals(dimension)) result.add(e);
        }
        return result;
    }

    public List<ContainerEntry> getRandom(String dimension, int count) {
        List<ContainerEntry> dimContainers = getByDimension(dimension);
        if (dimContainers.size() <= count) return dimContainers;
        Collections.shuffle(dimContainers);
        return dimContainers.subList(0, count);
    }

    public int size() { return containers.size(); }

    public void clear() { containers.clear(); }

    public List<Map<String, Object>> toMapList() {
        List<Map<String, Object>> list = new ArrayList<>();
        for (ContainerEntry e : containers.values()) {
            list.add(e.toMap());
        }
        return list;
    }

    public record ContainerEntry(int id, BlockPos pos, String dimension, String placedBy, long createdAt) {
        public Map<String, Object> toMap() {
            Map<String, Object> map = new LinkedHashMap<>();
            map.put("id", id);
            map.put("x", pos.getX());
            map.put("y", pos.getY());
            map.put("z", pos.getZ());
            map.put("dimension", dimension);
            map.put("placed_by", placedBy);
            map.put("created_at", createdAt);
            return map;
        }
    }
}
