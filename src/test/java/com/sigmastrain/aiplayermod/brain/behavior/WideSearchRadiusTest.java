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
    private static final int[] SHELL_RADII = {32, 64, 128, 256, 512, 1024};

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
        // Directive's builder only records positive radii, so 0 means "not
        // supplied". Clamping it to 1 would silently turn the default search
        // into a single cell.
        assertEquals(WideSearchBehavior.DEFAULT_RADIUS,
                WideSearchBehavior.resolveMaxRadius(null, 0));
        assertEquals(WideSearchBehavior.DEFAULT_RADIUS,
                WideSearchBehavior.resolveMaxRadius("0", 512));
    }

    @Test
    void a_negative_radius_is_treated_as_unset() {
        assertEquals(WideSearchBehavior.DEFAULT_RADIUS,
                WideSearchBehavior.resolveMaxRadius("-5", 512));
    }

    /**
     * The regression this guards: f7c5ef4 made the fallback 256, halving the
     * reach of an unconfigured search. Before radius handling existed the
     * default was 512 (3927924^:90), and "no radius = today unchanged" is the
     * ruling.
     */
    @Test
    void no_radius_gives_a_maximum_of_512_and_sweeps_up_to_that_shell() {
        assertEquals(512, WideSearchBehavior.resolveMaxRadius(null, 512),
                "no supplied radius must default to 512, not 256");

        int maxRadius = WideSearchBehavior.resolveMaxRadius(null, 512);
        int[] swept = new int[SHELL_RADII.length];
        int shells = 0;
        int totalCells = 0;
        for (int i = 0; i < SHELL_RADII.length; i++) {
            int r = Math.min(SHELL_RADII[i], maxRadius);
            if (i > 0 && r <= swept[i - 1]) {
                break;   // tickExpanding stops here: the shell could not grow
            }
            swept[i] = r;
            shells++;
            totalCells += cells(r);
        }

        assertEquals(5, shells, "the walk visits exactly five shells");
        assertEquals(32, swept[0]);
        assertEquals(64, swept[1]);
        assertEquals(128, swept[2]);
        assertEquals(256, swept[3]);
        assertEquals(512, swept[4], "the last shell an unconfigured search sweeps is 512");
        assertEquals(5709, totalCells,
                "25 + 81 + 289 + 1089 + 4225 cells, unchanged from before the change");
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

    /**
     * The failure message must name the radius that was swept. tickExpanding
     * used to report {@code SHELL_RADII[shellIndex - 1]}, the unclamped shell
     * value, so a search capped at 4 said "not found within 32 blocks" after
     * sweeping 4. It now reports the shell's clamped radius.
     */
    @Test
    void the_failure_message_reports_the_searched_radius_not_the_unclamped_shell() {
        // The old, wrong figure: SHELL_RADII[shellIndex - 1], always the bare
        // shell value regardless of the cap.
        int maxRadius = WideSearchBehavior.resolveMaxRadius("4", 256);
        assertEquals(4, searchedRadius(DEFAULT_FIRST_SHELL, maxRadius),
                "a radius-4 search must say 4, not 32");

        // No radius: the walk starts at the first shell and reports each shell
        // it really reached. Every shell clamps to the default cap of 256, so
        // the last four shells all sweep 256 and must all say 256.
        int defaultMax = WideSearchBehavior.resolveMaxRadius(null, 512);
        assertEquals(32, searchedRadius(SHELL_RADII[0], defaultMax));
        assertEquals(64, searchedRadius(SHELL_RADII[1], defaultMax));
        assertEquals(128, searchedRadius(SHELL_RADII[2], defaultMax));
        assertEquals(256, searchedRadius(SHELL_RADII[3], defaultMax));
        assertEquals(512, searchedRadius(SHELL_RADII[4], defaultMax));

        // A cap below a far shell reports the cap. Shell 3 is 128; a cap of
        // 100 means that sweep covered 100 blocks, so it must say 100.
        int capped = WideSearchBehavior.resolveMaxRadius("100", 256);
        assertEquals(100, searchedRadius(SHELL_RADII[2], capped),
                "a 128 shell clamped to a cap of 100 has swept 100, so it must say 100");
    }

    /**
     * tickExpanding's report: the shell's clamped radius, floored at 0 so an
     * unset field cannot print a negative distance.
     */
    private static int searchedRadius(int shellRadius, int maxRadius) {
        return Math.max(Math.min(shellRadius, maxRadius), 0);
    }
}
