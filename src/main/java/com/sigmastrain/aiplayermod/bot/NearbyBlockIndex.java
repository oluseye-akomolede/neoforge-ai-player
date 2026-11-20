package com.sigmastrain.aiplayermod.bot;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Turns a cube of block positions into the nearby-block list the agent sees,
 * keeping the K nearest instances of each block id.
 *
 * <p>The obvious implementation — walk the cube and keep the first K of each
 * name — is wrong in a way that looks fine: the walk goes x, then y, then z
 * upward from the negative corner, so the first K it meets are the ones nearest
 * that corner, which is diagonal from the bot and can be most of a radius away.
 * A bot asked for "the nearest chest" then gets one across the room while the
 * chest beside it is dropped. This class ranks by squared distance instead.
 *
 * <p>Distance is the squared integer {@code dx*dx + dy*dy + dz*dz} from the
 * bot's block position, so it needs no square root and no allocation. Ties are
 * broken by scan order: an incumbent is only replaced when the candidate is
 * strictly closer, so equal distances keep whichever the walk met first and the
 * same world always produces the same list.
 */
public final class NearbyBlockIndex {

    /** What one scanned position holds. */
    public record Block(String id, String name) {}

    /** Supplies the block at a position, or null when it is air. */
    @FunctionalInterface
    public interface Blocks {
        Block at(int dx, int dy, int dz);
    }

    /** One kept block, with the squared distance that earned its place. */
    private record Candidate(String id, String name,
                             int dx, int dy, int dz, long distanceSq) {}

    private NearbyBlockIndex() {}

    /**
     * The {@code perId} nearest non-air blocks for each id in the cube,
     * ordered by first appearance so the payload is stable.
     *
     * <p>{@code center} is the bot's block position: offsets are relative to it
     * for the distance, but the reported {@code position} is the absolute world
     * coordinate, matching what the rest of the snapshot emits.
     */
    public static List<Map<String, Object>> select(Blocks blocks, int radius, int perId,
                                                   int centerX, int centerY, int centerZ) {
        if (radius < 0) {
            throw new IllegalArgumentException("radius must be >= 0, was " + radius);
        }
        if (perId < 1) {
            throw new IllegalArgumentException("perId must be >= 1, was " + perId);
        }

        Map<String, List<Candidate>> kept = new LinkedHashMap<>();

        for (int x = -radius; x <= radius; x++) {
            for (int y = -radius; y <= radius; y++) {
                for (int z = -radius; z <= radius; z++) {
                    Block block = blocks.at(x, y, z);
                    if (block == null) {
                        continue;
                    }
                    Candidate candidate = new Candidate(
                            block.id(), block.name(),
                            x, y, z, (long) x * x + (long) y * y + (long) z * z);
                    insert(kept, candidate, perId);
                }
            }
        }

        List<Map<String, Object>> result = new ArrayList<>();
        for (List<Candidate> candidates : kept.values()) {
            for (Candidate candidate : candidates) {
                Map<String, Object> info = new LinkedHashMap<>();
                info.put("id", candidate.id());
                info.put("block", candidate.name());
                info.put("position", positionOf(candidate, centerX, centerY, centerZ));
                result.add(info);
            }
        }
        return result;
    }

    /**
     * K-bounded insertion: K is tiny, so this walks at most K entries rather
     * than sorting the whole cube's worth of blocks.
     */
    private static void insert(Map<String, List<Candidate>> kept,
                               Candidate candidate, int perId) {
        List<Candidate> forId = kept.computeIfAbsent(candidate.id(), k -> new ArrayList<>(perId));

        int place = 0;
        while (place < forId.size()
                && forId.get(place).distanceSq() <= candidate.distanceSq()) {
            place++;
        }
        if (place >= perId) {
            return;
        }
        forId.add(place, candidate);
        if (forId.size() > perId) {
            forId.remove(forId.size() - 1);
        }
    }

    /** Absolute world coordinate, the same {@code {x,y,z}} map the rest emits. */
    private static Map<String, Integer> positionOf(Candidate candidate,
                                                   int centerX, int centerY, int centerZ) {
        Map<String, Integer> position = new LinkedHashMap<>();
        position.put("x", centerX + candidate.dx());
        position.put("y", centerY + candidate.dy());
        position.put("z", centerZ + candidate.dz());
        return position;
    }

    /** The ids this list mentions, for callers that only need the kinds present. */
    public static Set<String> idsOf(List<Map<String, Object>> nearby) {
        Set<String> ids = new LinkedHashSet<>();
        for (Map<String, Object> entry : nearby) {
            Object id = entry.get("id");
            if (id != null) {
                ids.add(id.toString());
            }
        }
        return ids;
    }
}
