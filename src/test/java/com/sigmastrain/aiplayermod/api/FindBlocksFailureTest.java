package com.sigmastrain.aiplayermod.api;

import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Tests for the answer a {@code find_blocks} / {@code find_entities} handler
 * builds, so that a search that <em>failed</em> is distinguishable from one that
 * ran and <em>found nothing</em>.
 *
 * <p>These cover the api-http scenarios "A search that throws answers with an
 * error key", "A genuine empty result carries no error key", "The success path is
 * unchanged" and their entity twins, plus "Both verbs are proved the same way":
 * each verb is exercised under its own key ({@code blocks}, {@code entities})
 * here, so a test written for one cannot be read as covering the other. The
 * end-to-end answer — a real search throwing in a live world — is a deploy
 * run-plan check, not this test.
 *
 * <p><b>What these tests do not see.</b> Every case calls
 * {@link HttpApiServer#searchAnswer} directly. They prove the answer-building
 * rule is correct; they do <em>not</em> prove the handlers call it. Reverting a
 * handler's {@code sendJson(...)} back to a bare {@code Map.of(listKey, ...)}
 * leaves this whole class green, because the handler needs a live server and a
 * real BotPlayer to enter. That wiring is witnessed by the reviewer's read of
 * the diff and by the deploy run-plan probe, not here — stated so a green run
 * is not mistaken for end-to-end coverage.
 *
 * <p>No Minecraft classpath: {@link HttpApiServer#searchAnswer} is static and
 * takes plain lists, in the shape {@link BoundedWaitTest} already establishes.
 */
class FindBlocksFailureTest {

    /** Something a failed search would throw; the text is what the agent's normaliser keys on. */
    private static final RuntimeException BOOM = new IllegalStateException("findBlocks error: level not loaded");

    // ---- find_blocks ----------------------------------------------------

    @Test
    void blocksFailureAndEmptyAreDistinguishable() {
        Map<String, Object> failed = HttpApiServer.searchAnswer("blocks", List.of(), BOOM);
        Map<String, Object> empty = HttpApiServer.searchAnswer("blocks", List.of(), null);

        assertTrue(failed.containsKey("error"),
                "a failed search MUST carry an error key, or it is the same bytes as an empty one");
        assertFalse(empty.containsKey("error"),
                "a genuine empty search MUST NOT carry an error key");
        // The core promise: the two outcomes are different bytes.
        assertTrue(!failed.equals(empty),
                "failure and empty answers must differ; they are indistinguishable today");
    }

    @Test
    void blocksFailureCarriesTheExceptionText() {
        Map<String, Object> failed = HttpApiServer.searchAnswer("blocks", List.of(), BOOM);

        String error = (String) failed.get("error");
        assertNotNull(error);
        assertTrue(error.contains("findBlocks error"),
                "the error text must carry the mod's own message so the planner can read it: " + error);
    }

    @Test
    void blocksFailureStillCarriesTheListKey() {
        Map<String, Object> failed = HttpApiServer.searchAnswer("blocks", List.of(), BOOM);

        assertTrue(failed.containsKey("blocks"),
                "a caller that reads only 'blocks' must not break");
        assertEquals(List.of(), failed.get("blocks"));
    }

    @Test
    void blocksFailureWithNullMessageFallsBackToTheClassName() {
        RuntimeException blank = new RuntimeException();
        Map<String, Object> failed = HttpApiServer.searchAnswer("blocks", List.of(), blank);

        String error = (String) failed.get("error");
        assertNotNull(error);
        assertFalse(error.isBlank(),
                "the error key must never be blank, even when the exception has no message");
        assertEquals("RuntimeException", error);
    }

    @Test
    void blocksSuccessPathIsUnchanged() {
        List<Map<String, Object>> two = List.of(
                Map.of("x", 1, "y", 2, "z", 3),
                Map.of("x", 4, "y", 5, "z", 6));
        Map<String, Object> ok = HttpApiServer.searchAnswer("blocks", two, null);

        // Exactly one entry, the list key; if a field were added the size would change.
        assertEquals(1, ok.size(), "the success answer must carry its list key and nothing else");
        assertEquals(two, ok.get("blocks"));
        assertFalse(ok.containsKey("error"));
    }

    // ---- find_entities --------------------------------------------------
    // Deliberately separate tests under the entities key: the api-http scenario
    // "a test written for find_blocks MUST NOT be counted as covering
    // find_entities" is the reason these are not a parameterised reuse.

    @Test
    void entitiesFailureAndEmptyAreDistinguishable() {
        Map<String, Object> failed = HttpApiServer.searchAnswer("entities", List.of(), BOOM);
        Map<String, Object> empty = HttpApiServer.searchAnswer("entities", List.of(), null);

        assertTrue(failed.containsKey("error"),
                "a failed ENTITY search MUST carry an error key");
        assertFalse(empty.containsKey("error"),
                "a genuine empty ENTITY search MUST NOT carry an error key");
        assertTrue(!failed.equals(empty));
    }

    @Test
    void entitiesFailureCarriesTheExceptionText() {
        Map<String, Object> failed = HttpApiServer.searchAnswer("entities", List.of(), BOOM);

        String error = (String) failed.get("error");
        assertNotNull(error);
        assertTrue(error.contains("findBlocks error"));
    }

    @Test
    void entitiesFailureStillCarriesTheListKey() {
        Map<String, Object> failed = HttpApiServer.searchAnswer("entities", List.of(), BOOM);

        assertTrue(failed.containsKey("entities"),
                "a caller that reads only 'entities' must not break");
        assertEquals(List.of(), failed.get("entities"));
        assertFalse(failed.containsKey("blocks"),
                "the entity answer must carry the entities key, never the blocks key");
    }

    @Test
    void entitiesSuccessPathIsUnchanged() {
        List<Map<String, Object>> two = List.of(Map.of("id", "minecraft:cow"));
        Map<String, Object> ok = HttpApiServer.searchAnswer("entities", two, null);

        assertEquals(1, ok.size());
        assertEquals(two, ok.get("entities"));
        assertFalse(ok.containsKey("error"));
    }
}
