package com.sigmastrain.aiplayermod.brain.behavior;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

/**
 * WIDE_SEARCH must honour a supplied radius.
 *
 * <p>The live case: "find X within 4 blocks, do not walk". Before this, the
 * radius was read only from the directive's top-level field and never from
 * {@code extra.radius}, so the request walked a 25-cell, 32-block sweep. The
 * cell arithmetic below is the whole point: radius 4 is one cell, the default
 * first shell of 32 is twenty-five.
 *
 * <p>These drive {@code resolveMaxRadius}, the same function {@code start()}
 * calls, rather than re-deriving the rule here.
 */
class WideSearchRadiusTest {

    private static final int DEFAULT_FIRST_SHELL = 32;
    private static final int CELL_SIZE = 16;

    /** Cells in a square cube of the given radius at the behaviour's cell size. */
    private static int cells(int radius) {
        int perSide = 2 * (radius / CELL_SIZE) + 1;
        return perSide * perSide;
    }

    @Test
    void extra_radius_wins_over_the_top_level_field() {
        // The script surface teaches "extra", so it must not be shadowed by a
        // builder default that says 256.
        assertEquals(16, WideSearchBehavior.resolveMaxRadius("16", 256));
    }

    @Test
    void the_top_level_field_is_used_when_extra_is_absent() {
        assertEquals(64, WideSearchBehavior.resolveMaxRadius(null, 64));
    }

    @Test
    void an_unparseable_extra_falls_back_to_the_top_level_field() {
        assertEquals(64, WideSearchBehavior.resolveMaxRadius("wide", 64));
    }

    /**
     * The live case. A radius of 4 must search one cell, not the 25-cell
     * 32-block sweep — and the sweep is 25 only because the default first shell
     * is 32, so both numbers are asserted to keep this honest.
     */
    @Test
    void a_four_block_radius_searches_one_cell_not_the_twenty_five_cell_sweep() {
        int maxRadius = WideSearchBehavior.resolveMaxRadius("4", 256);
        int firstShell = Math.min(DEFAULT_FIRST_SHELL, maxRadius);

        assertEquals(4, firstShell, "first shell must be clamped to the request");
        assertEquals(1, cells(firstShell), "radius 4 must scan exactly one cell");
        assertEquals(25, cells(DEFAULT_FIRST_SHELL),
                "the default first shell is the 25-cell sweep this fixes");
    }

    @Test
    void no_radius_keeps_the_default_first_shell_of_thirty_two() {
        int maxRadius = WideSearchBehavior.resolveMaxRadius(null, 256);
        assertEquals(DEFAULT_FIRST_SHELL, Math.min(DEFAULT_FIRST_SHELL, maxRadius));
    }

    @Test
    void a_zero_radius_is_treated_as_unset_not_clamped_to_one() {
        // Directive's builder defaults to 256 and only records positive radii,
        // so 0 means "not supplied". Clamping it to 1 would silently turn the
        // default search into a single cell.
        assertEquals(256, WideSearchBehavior.resolveMaxRadius(null, 0));
        assertEquals(256, WideSearchBehavior.resolveMaxRadius("0", 256));
    }

    @Test
    void a_negative_radius_is_treated_as_unset() {
        assertEquals(256, WideSearchBehavior.resolveMaxRadius("-5", 256));
    }

    /**
     * The ceiling must not be AreaLoot's 64: WIDE_SEARCH exists to reach the
     * far shells up to 1024.
     */
    @Test
    void a_large_radius_is_capped_at_the_last_shell_not_sixty_four() {
        assertEquals(1024, WideSearchBehavior.resolveMaxRadius("5000", 256));
        assertEquals(512, WideSearchBehavior.resolveMaxRadius("512", 256));
    }

    @Test
    void whitespace_in_the_extra_value_is_tolerated() {
        assertEquals(8, WideSearchBehavior.resolveMaxRadius("  8  ", 256));
    }
}
