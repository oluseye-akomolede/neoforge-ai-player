package com.sigmastrain.aiplayermod.api;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * The dedicated listener's reason for existing: it answers while the API's own
 * executor is fully occupied by handlers that are blocked on the server thread.
 *
 * <p>The 2026-10-27 and 2026-10-28 stalls are the regression this guards. In
 * both, {@code /health} went silent rather than answering 503, because it was
 * queued behind blocked handlers in a shared four-thread pool.
 */
class HealthProbeListenerTest {

    private static int freePort() throws IOException {
        try (ServerSocket s = new ServerSocket(0)) {
            return s.getLocalPort();
        }
    }

    /** A handler that answers 503 stalled, and counts how often it ran. */
    private static HttpApiServer.HealthHandler answering503(AtomicInteger runs) {
        return exchange -> {
            runs.incrementAndGet();
            byte[] body = "{\"status\":\"stalled\"}".getBytes();
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(503, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        };
    }

    @Test
    void answersWhileTheApiPoolIsFullyBlocked() throws Exception {
        // The API: a four-thread pool, every thread parked inside a handler, on
        // an unrelated port. This is the production shape of a stall.
        int apiPort = freePort();
        HttpServer api = HttpServer.create(new InetSocketAddress("127.0.0.1", apiPort), 0);
        api.setExecutor(Executors.newFixedThreadPool(4));
        CountDownLatch release = new CountDownLatch(1);
        CountDownLatch allBlocked = new CountDownLatch(4);
        api.createContext("/server/players", exchange -> {
            allBlocked.countDown();
            try {
                // Stands in for the join() onto a held server thread.
                release.await(60, TimeUnit.SECONDS);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
            exchange.sendResponseHeaders(200, -1);
            exchange.close();
        });
        api.start();

        try {
            // Occupy all four threads.
            HttpClient client = HttpClient.newBuilder()
                    .connectTimeout(Duration.ofSeconds(5)).build();
            List<Thread> blocked = new ArrayList<>();
            for (int i = 0; i < 4; i++) {
                Thread t = new Thread(() -> {
                    try {
                        client.send(HttpRequest.newBuilder()
                                        .uri(URI.create("http://127.0.0.1:" + apiPort + "/server/players"))
                                        .timeout(Duration.ofSeconds(30)).build(),
                                HttpResponse.BodyHandlers.discarding());
                    } catch (Exception ignored) {
                        // The point is the parking, not the response.
                    }
                });
                t.setDaemon(true);
                t.start();
                blocked.add(t);
            }
            assertTrue(allBlocked.await(10, TimeUnit.SECONDS), "all four API pool threads blocked");

            // The probe listener on its own port.
            int probePort = freePort();
            assertNotEquals(apiPort, probePort);
            AtomicInteger runs = new AtomicInteger();
            HealthProbeListener probe = new HealthProbeListener(probePort, answering503(runs));
            List<String> errors = new ArrayList<>();
            assertTrue(probe.start(errors::add), "probe listener should bind: " + errors);

            try {
                long started = System.nanoTime();
                HttpResponse<String> r = client.send(
                        HttpRequest.newBuilder()
                                .uri(URI.create("http://127.0.0.1:" + probePort + "/health"))
                                .timeout(Duration.ofSeconds(10)).build(),
                        HttpResponse.BodyHandlers.ofString());
                long elapsedMs = (System.nanoTime() - started) / 1_000_000;

                assertEquals(503, r.statusCode(), "a stalled tick answers 503, not a timeout");
                assertTrue(r.body().contains("stalled"), r.body());
                assertTrue(elapsedMs < 5_000, "answered in " + elapsedMs + " ms, not queued behind the stall");

                // The API endpoint is still blocked - proving the two executors
                // are genuinely independent and the probe did not get lucky.
                HttpClient shortClient = HttpClient.newBuilder()
                        .connectTimeout(Duration.ofSeconds(2)).build();
                boolean apiTimedOut = false;
                try {
                    shortClient.send(HttpRequest.newBuilder()
                                    .uri(URI.create("http://127.0.0.1:" + apiPort + "/server/players"))
                                    .timeout(Duration.ofSeconds(2)).build(),
                            HttpResponse.BodyHandlers.discarding());
                } catch (java.net.http.HttpTimeoutException e) {
                    apiTimedOut = true;
                }
                assertTrue(apiTimedOut, "the API pool is still saturated, so the two are independent");
            } finally {
                probe.stop();
                release.countDown();
            }
        } finally {
            api.stop(0);
        }
    }

    @Test
    void servesOnlyHealth() throws Exception {
        int probePort = freePort();
        HealthProbeListener probe = new HealthProbeListener(probePort, ex -> {
            ex.sendResponseHeaders(200, -1);
            ex.close();
        });
        assertTrue(probe.start(msg -> { }));
        try {
            HttpClient client = HttpClient.newHttpClient();
            HttpResponse<String> missing = client.send(
                    HttpRequest.newBuilder()
                            .uri(URI.create("http://127.0.0.1:" + probePort + "/server/players"))
                            .timeout(Duration.ofSeconds(5)).build(),
                    HttpResponse.BodyHandlers.ofString());
            // A 404 is the whole point: the key-free probe port must not widen
            // into key-free access to the rest of the API.
            assertEquals(404, missing.statusCode());
        } finally {
            probe.stop();
        }
    }

    @Test
    void unavailablePortReportsOneErrorAndBindsNothing() throws Exception {
        int taken;
        try (ServerSocket held = new ServerSocket(0)) {
            taken = held.getLocalPort();
            List<String> errors = new ArrayList<>();
            HealthProbeListener probe = new HealthProbeListener(taken,
                    ex -> { ex.sendResponseHeaders(200, -1); ex.close(); });
            assertFalse(probe.start(errors::add), "binding an occupied port must fail");
            assertEquals(1, errors.size(), "exactly one error: " + errors);
            assertTrue(errors.get(0).contains(String.valueOf(taken)), errors.get(0));
            assertFalse(probe.isServing());
            probe.stop(); // safe after a failed start
        }
    }

    @Test
    void stopClosesThePortAndIsIdempotent() throws Exception {
        int probePort = freePort();
        HealthProbeListener probe = new HealthProbeListener(probePort, ex -> {
            ex.sendResponseHeaders(200, -1);
            ex.close();
        });
        assertTrue(probe.start(msg -> { }));
        assertTrue(probe.isServing());
        probe.stop();
        assertFalse(probe.isServing());
        probe.stop(); // second call must not throw
        // The port is free again.
        try (ServerSocket again = new ServerSocket(probePort)) {
            assertEquals(probePort, again.getLocalPort());
        }
    }

    @Test
    void stopAfterFailedStartDoesNotThrow() throws IOException {
        int taken;
        try (ServerSocket held = new ServerSocket(0)) {
            taken = held.getLocalPort();
            HealthProbeListener probe = new HealthProbeListener(taken, HealthProbeListenerTest::unused);
            assertFalse(probe.start(msg -> { }));
            probe.stop();
        }
    }

    private static void unused(HttpExchange exchange) throws IOException {
        exchange.close();
    }
}
