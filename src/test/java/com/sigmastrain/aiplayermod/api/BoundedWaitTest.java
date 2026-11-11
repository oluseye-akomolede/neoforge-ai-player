package com.sigmastrain.aiplayermod.api;

import org.junit.jupiter.api.Test;

import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Tests for the bounded wait that keeps a stalled server thread from holding an
 * API pool thread indefinitely.
 *
 * <p>These cover the api-http scenarios "A blocked handler releases its pool
 * thread at the bound", "Four blocked handlers no longer hold the pool
 * open-endedly" and "Timed-out request returns an error, not a hang". The last
 * is covered here only at the wait layer; the 503 body itself is produced by the
 * server and is checked in the deploy run plan.
 */
class BoundedWaitTest {

    /** A future that never completes - the stalled server thread, as a caller sees it. */
    private static CompletableFuture<String> neverCompletes() {
        return new CompletableFuture<>();
    }

    @Test
    void expiredBoundRaisesTimeoutRatherThanHanging() {
        long boundMs = 100;
        long started = System.nanoTime();

        BoundedWait.Timeout e = assertThrows(BoundedWait.Timeout.class,
                () -> BoundedWait.await(neverCompletes(), boundMs));

        long elapsedMs = (System.nanoTime() - started) / 1_000_000;
        assertEquals(boundMs, e.timeoutMs(), "the raised timeout must name the bound it used");
        assertTrue(elapsedMs >= boundMs,
                "must not give up before the bound: elapsed " + elapsedMs + " ms < " + boundMs + " ms");
        // Generous upper bound: this asserts "bounded", not a precise schedule.
        assertTrue(elapsedMs < boundMs + 5_000,
                "must not wait far past the bound: elapsed " + elapsedMs + " ms");
    }

    /**
     * The bound must be <em>honoured</em>, not merely applied.
     *
     * <p>The short-bound test above uses 100 ms with seconds of slack, so it can
     * only show that a bound exists: an implementation that waited
     * {@code timeoutMs * 20} still passed it. Here the bound is large enough
     * (2000 ms) that a 20x error would overshoot by 38 s, so the margin proves the
     * value is used rather than merely consulted. Both sides are asserted: not
     * early (which would be a spurious timeout on a healthy server) and not late
     * (which is the bug this whole change exists to prevent).
     */
    @Test
    void theBoundIsHonouredNotMerelyApplied() {
        long boundMs = 2_000;
        long started = System.nanoTime();

        BoundedWait.Timeout e = assertThrows(BoundedWait.Timeout.class,
                () -> BoundedWait.await(neverCompletes(), boundMs));

        long elapsedMs = (System.nanoTime() - started) / 1_000_000;
        assertEquals(boundMs, e.timeoutMs());
        assertTrue(elapsedMs >= boundMs,
                "gave up before the bound: " + elapsedMs + " ms < " + boundMs + " ms");
        // 500 ms of slack dominates CI jitter but is nowhere near the 38 s that a
        // 20x-errored bound would add. This is the assertion that makes the
        // elapsed-time check bite.
        assertTrue(elapsedMs < boundMs + 500,
                "bound was not honoured: waited " + elapsedMs + " ms for a " + boundMs
                        + " ms bound, which is " + (elapsedMs - boundMs) + " ms over");
    }

    @Test
    void completedFutureReturnsItsValueWithoutWaiting() {
        CompletableFuture<String> done = CompletableFuture.completedFuture("ok");

        assertEquals("ok", BoundedWait.await(done, 10_000));
    }

    @Test
    void valueArrivingInsideTheBoundIsReturned() throws Exception {
        CompletableFuture<String> future = new CompletableFuture<>();
        Thread completer = new Thread(() -> {
            try {
                Thread.sleep(50);
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt();
            }
            future.complete("late but in time");
        });
        completer.start();

        assertEquals("late but in time", BoundedWait.await(future, 5_000));
        completer.join();
    }

    @Test
    void aThreadFailingUncheckedPropagatesThatExceptionUnchanged() {
        CompletableFuture<String> future = new CompletableFuture<>();
        IllegalStateException cause = new IllegalStateException("server thread blew up");
        future.completeExceptionally(cause);

        IllegalStateException thrown = assertThrows(IllegalStateException.class,
                () -> BoundedWait.await(future, 5_000));
        assertEquals("server thread blew up", thrown.getMessage());
    }

    @Test
    void aCheckedFailureIsWrappedNotLost() {
        CompletableFuture<String> future = new CompletableFuture<>();
        future.completeExceptionally(new java.io.IOException("disk gone"));

        RuntimeException thrown = assertThrows(RuntimeException.class,
                () -> BoundedWait.await(future, 5_000));
        assertInstanceOf(java.io.IOException.class, thrown.getCause());
    }

    @Test
    void interruptedWaiterRaisesTimeoutAndRestoresTheInterruptFlag() {
        AtomicReference<Boolean> flagAfter = new AtomicReference<>();
        AtomicReference<Throwable> raised = new AtomicReference<>();

        Thread waiter = new Thread(() -> {
            try {
                BoundedWait.await(neverCompletes(), 60_000);
            } catch (Throwable t) {
                raised.set(t);
            }
            flagAfter.set(Thread.currentThread().isInterrupted());
        });
        waiter.start();
        // Let the waiter reach the get() before interrupting it.
        try {
            Thread.sleep(100);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        waiter.interrupt();
        try {
            waiter.join(5_000);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }

        assertInstanceOf(BoundedWait.Timeout.class, raised.get());
        assertEquals(Boolean.TRUE, flagAfter.get(), "the interrupt flag must be restored, not swallowed");
    }

    /**
     * The pool-starvation scenario, at the layer that can be tested here: four
     * threads waiting on a stalled server thread must all give up at the bound,
     * so a four-thread pool is usable again.
     */
    @Test
    void fourBlockedWaitersAllReleaseAtTheBound() throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(4);
        CompletableFuture<String> stalled = neverCompletes();
        CountDownLatch allDone = new CountDownLatch(4);
        AtomicReference<Throwable> unexpected = new AtomicReference<>();

        long boundMs = 300;
        long started = System.nanoTime();
        for (int i = 0; i < 4; i++) {
            pool.submit(() -> {
                try {
                    BoundedWait.await(stalled, boundMs);
                    unexpected.set(new AssertionError("wait should have timed out"));
                } catch (BoundedWait.Timeout expected) {
                    // the defined outcome
                } catch (Throwable t) {
                    unexpected.set(t);
                } finally {
                    allDone.countDown();
                }
            });
        }

        assertTrue(allDone.await(boundMs + 10_000, TimeUnit.MILLISECONDS),
                "all four waits must return after the bound, not hang the pool");
        long elapsedMs = (System.nanoTime() - started) / 1_000_000;
        assertTrue(elapsedMs < boundMs + 10_000, "all four must release near the bound: " + elapsedMs + " ms");
        assertEquals(null, unexpected.get(), "no waiter may end with an unexpected outcome");

        // The pool must accept new work now that the four threads are free.
        String after = pool.submit(() -> "pool usable").get(5, TimeUnit.SECONDS);
        assertEquals("pool usable", after);

        pool.shutdownNow();
    }

    @Test
    void defaultTimeoutIsFarAboveOrdinaryLatency() {
        // A bound that fires on a healthy server would turn normal answers into
        // errors. This is a guard on the constant, not a timing measurement.
        assertTrue(BoundedWait.DEFAULT_TIMEOUT_MS >= 1_000,
                "default bound must leave room for normal handler latency");
    }
}
