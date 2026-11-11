package com.sigmastrain.aiplayermod.api;

import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

/**
 * A wait on a {@link CompletableFuture} that cannot last forever.
 *
 * <p>The API server hands every route one fixed pool of four threads. A handler
 * that hops to the main server thread and blocks on {@code join()} holds its pool
 * thread for the whole wait, so four stalled waits take the entire pool and every
 * other route queues behind them. The requester then gets no answer at all rather
 * than an error, which is worse than a failure for a caller that has its own
 * timeout. That is what happened on 2026-10-27: {@code /health} answered nothing
 * for 22 consecutive 15 s attempts and the pod was killed on liveness timeout.
 *
 * <p>This class holds the bound itself, so the value exists once rather than as a
 * literal at each of the call sites, and so it can be tested without a Minecraft
 * classpath. Bounding does not stop four handlers occupying the pool; it bounds
 * how long they can, and lets each caller be told what happened.
 */
public final class BoundedWait {

    /**
     * The default bound in milliseconds.
     *
     * <p>Ten seconds distinguishes "the server is stalled" from "the server is
     * slow": ordinary handler work finishes in milliseconds. It must stay far
     * above ordinary latency, because a bound that fires on a healthy server
     * would turn normal answers into errors.
     */
    public static final int DEFAULT_TIMEOUT_MS = 10_000;

    private BoundedWait() {
    }

    /**
     * Raised when a wait exceeds its bound.
     *
     * <p>Carries no stack trace. This is a control signal describing one request,
     * not a fault in the JVM, and a stalled server can raise it at all 47 call
     * sites at once; a stack trace per occurrence would bury the stall in noise
     * rather than report it.
     */
    public static final class Timeout extends RuntimeException {
        private final long timeoutMs;

        public Timeout(long timeoutMs) {
            super("timed out after " + timeoutMs + " ms waiting for the server thread",
                    null, false, false);
            this.timeoutMs = timeoutMs;
        }

        public long timeoutMs() {
            return timeoutMs;
        }
    }

    /**
     * Wait for {@code future}, but not past {@code timeoutMs}.
     *
     * @throws Timeout           if the bound expires, or if this thread is interrupted
     *                           while waiting (the interrupt flag is restored first)
     * @throws RuntimeException  wrapping a checked failure from the future; an
     *                           unchecked failure is rethrown as it is
     */
    public static <T> T await(CompletableFuture<T> future, long timeoutMs) {
        try {
            return future.get(timeoutMs, TimeUnit.MILLISECONDS);
        } catch (TimeoutException e) {
            throw new Timeout(timeoutMs);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new Timeout(timeoutMs);
        } catch (ExecutionException e) {
            Throwable cause = e.getCause();
            if (cause instanceof RuntimeException re) {
                throw re;
            }
            if (cause instanceof Error err) {
                throw err;
            }
            throw new RuntimeException(cause);
        }
    }
}
