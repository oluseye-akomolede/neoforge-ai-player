package com.sigmastrain.aiplayermod.bot;

import org.junit.jupiter.api.Test;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * The nearby-block list: nearest-K per id, real ids, no dedup by name.
 *
 * <p>The ordering test is the one that matters. A scan-order implementation
 * passes every other test here and fails that one, because the cube is walked
 * from the negative corner, so "first K" is "nearest the far corner".
 */
class NearbyBlockIndexTest {

    /** A cube with a few blocks placed at offsets from the bot. */
    private static NearbyBlockIndex.Blocks cube(
            Map<Integer, NearbyBlockIndex.Block> byOffset) {
        return (dx, dy, dz) -> byOffset.get(offset(dx, dy, dz));
    }

    private static int offset(int dx, int dy, int dz) {
        return (dx + 100) * 1_000_000 + (dy + 100) * 1_000 + (dz + 100);
    }

    private static Map<Integer, NearbyBlockIndex.Block> blocks(Object... spec) {
        Map<Integer, NearbyBlockIndex.Block> map = new HashMap<>();
        for (int i = 0; i < spec.length; i += 4) {
            map.put(offset((int) spec[i], (int) spec[i + 1], (int) spec[i + 2]),
                    (NearbyBlockIndex.Block) spec[i + 3]);
        }
        return map;
    }

    private static NearbyBlockIndex.Block chest() {
        return new NearbyBlockIndex.Block("minecraft:chest", "Chest");
    }

    /** KILLS: first-K in scan order keeps the (-5,-5,-5) chest, not the (2,0,2) one. */
    @Test
    void theNearestChestIsKeptNotTheFirstInScanOrder() {
        List<Map<String, Object>> found = NearbyBlockIndex.select(
                cube(blocks(
                        2, 0, 2, chest(),
                        -5, -5, -5, chest())),
                5, 1, 0, 0, 0);

        assertEquals(1, found.size(), "K=1 keeps exactly one chest");
        Map<String, Object> kept = found.get(0);
        Map<?, ?> position = (Map<?, ?>) kept.get("position");
        assertEquals(2, position.get("x"));
        assertEquals(0, position.get("y"));
        assertEquals(2, position.get("z"),
                "kept the chest 2.83 blocks away, not the one at 8.66");
    }

    /** KILLS: deduplicating by display name emits one chest where two exist. */
    @Test
    void twoChestsAreBothListed() {
        List<Map<String, Object>> found = NearbyBlockIndex.select(
                cube(blocks(
                        1, 0, 0, chest(),
                        2, 0, 0, chest())),
                5, 4, 0, 0, 0);

        assertEquals(2, found.size(), "two distinct chests, not one name");
        assertEquals("Chest", found.get(0).get("block"));
        assertEquals("Chest", found.get(1).get("block"));
    }

    /** KILLS: emitting the display name as id gives "Chest", not "minecraft:chest". */
    @Test
    void everyEntryCarriesTheRegistryId() {
        List<Map<String, Object>> found = NearbyBlockIndex.select(
                cube(blocks(1, 0, 0, chest())),
                5, 4, 0, 0, 0);

        assertEquals("minecraft:chest", found.get(0).get("id"));
        assertEquals("Chest", found.get(0).get("block"));
    }

    /** KILLS: sorting only by insertion keeps K+1 entries instead of evicting. */
    @Test
    void kBoundsTheListPerId() {
        List<Map<String, Object>> found = NearbyBlockIndex.select(
                cube(blocks(
                        1, 0, 0, chest(),
                        2, 0, 0, chest(),
                        3, 0, 0, chest())),
                5, 2, 0, 0, 0);

        assertEquals(2, found.size(), "K=2 drops the farthest chest");
    }

    /** KILLS: position reporting offsets instead of absolute coordinates. */
    @Test
    void positionIsTheAbsoluteWorldCoordinate() {
        List<Map<String, Object>> found = NearbyBlockIndex.select(
                cube(blocks(1, 0, 0, chest())),
                5, 4, 100, 64, -200);

        Map<?, ?> position = (Map<?, ?>) found.get(0).get("position");
        assertEquals(101, position.get("x"));
        assertEquals(64, position.get("y"));
        assertEquals(-200, position.get("z"));
    }

    /** KILLS: ties broken by "closer than or equal", which flips equal-distance blocks. */
    @Test
    void equalDistancesKeepScanOrderSoTheResultIsStable() {
        List<Map<String, Object>> first = NearbyBlockIndex.select(
                cube(blocks(
                        1, 0, 0, chest(),
                        -1, 0, 0, chest())),
                5, 1, 0, 0, 0);
        List<Map<String, Object>> second = NearbyBlockIndex.select(
                cube(blocks(
                        1, 0, 0, chest(),
                        -1, 0, 0, chest())),
                5, 1, 0, 0, 0);

        assertEquals(first, second, "same world, same list");
        Map<?, ?> position = (Map<?, ?>) first.get(0).get("position");
        assertEquals(-1, position.get("x"),
                "both are 1 away; scan order reaches -1 first and keeps it");
    }

    @Test
    void aNegativeRadiusIsRejectedRatherThanScanned() {
        assertThrows(IllegalArgumentException.class,
                () -> NearbyBlockIndex.select(cube(blocks()), -1, 1, 0, 0, 0));
    }

    @Test
    void airIsSkipped() {
        List<Map<String, Object>> found = NearbyBlockIndex.select(
                cube(blocks()), 2, 4, 0, 0, 0);
        assertTrue(found.isEmpty());
    }
}
