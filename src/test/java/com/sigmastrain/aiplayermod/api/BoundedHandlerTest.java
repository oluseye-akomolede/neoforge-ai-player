package com.sigmastrain.aiplayermod.api;

import com.google.gson.Gson;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Drives {@link BoundedHandler} through a real {@link HttpServer} on loopback.
 *
 * <p>This closes the gap the 2026-11-06 code review named: every 503 assertion in
 * the suite was about the health probe, so the api-http scenario "a blocked
 * handler releases its pool thread at the bound" was proven only at the
 * {@link BoundedWait} level, never through the handler wrapper. Here the wrapper
 * itself is exercised, end to end, with a client that can see the status code.
 */
class BoundedHandlerTest {

    private static final long BOUND_MS = 400;

    private HttpServer server;
    private ExecutorService pool;
    private int port;
    private final Gson gson = new Gson();
    private final List<String> warnings = new ArrayList<>();
    private final HttpClient client = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(5))
            .build();

    /** A handler that joins a future which never completes, exactly like a stalled server thread. */
    private com.sun.net.httpserver.HttpHandler stalledHandler() {
        return exchange -> BoundedWait.await(new CompletableFuture<String>(), BOUND_MS);
    }

    @BeforeEach
    void startServer() throws IOException {
        // A deliberately small pool: four threads is what the real API server has,
        // so "the pool frees up" is tested against the same constraint.
        pool = Executors.newFixedThreadPool(4);
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.setExecutor(pool);
        server.createContext("/stalled", new BoundedHandler(stalledHandler(), BOUND_MS, gson, warnings::add));
        server.createContext("/healthy", new BoundedHandler(
                exchange -> {
                    byte[] b = "{\"ok\":true}".getBytes();
                    exchange.getResponseHeaders().set("Content-Type", "application/json");
                    exchange.sendResponseHeaders(200, b.length);
                    exchange.getResponseBody().write(b);
                    exchange.getResponseBody().close();
                }, BOUND_MS, gson, warnings::add));
        server.start();
        port = server.getAddress().getPort();
    }

    @AfterEach
    void stopServer() {
        if (server != null) {
            server.stop(0);
        }
        if (pool != null) {
            pool.shutdownNow();
        }
    }

    private HttpResponse<String> get(String path) throws Exception {
        return client.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + path))
                .timeout(Duration.ofSeconds(10)).GET().build(), HttpResponse.BodyHandlers.ofString());
    }

    @Test
    void blockedHandlerReturns503WithAnErrorNamingTheTimeout() throws Exception {
        long started = System.nanoTime();
        HttpResponse<String> r = get("/stalled");
        long elapsedMs = (System.nanoTime() - started) / 1_000_000;

        assertEquals(503, r.statusCode(), "a stalled handler must answer 503, not hang or drop");
        assertTrue(r.body().contains("error"), "the body must carry an error: " + r.body());
        assertTrue(r.body().contains(String.valueOf(BOUND_MS)),
                "the error must name the timeout in ms: " + r.body());
        assertTrue(elapsedMs >= BOUND_MS, "answered before the bound");
        assertTrue(elapsedMs < BOUND_MS + 5_000, "answered far past the bound: " + elapsedMs + " ms");
    }

    @Test
    void healthyHandlerIsUntouchedByTheWrapper() throws Exception {
        HttpResponse<String> r = get("/healthy");

        assertEquals(200, r.statusCode(), "the wrapper must not disturb a healthy response");
        assertEquals("{\"ok\":true}", r.body());
        assertTrue(warnings.isEmpty(), "nothing should have been reported: " + warnings);
    }

    @Test
    void thePoolAcceptsNewWorkAfterBlockedRequestsTimeOut() throws Exception {
        // Fill all four pool threads with stalled requests, which is the 2026-10-27
        // failure: four waits take the whole pool.
        List<CompletableFuture<HttpResponse<String>>> stalled = new ArrayList<>();
        for (int i = 0; i < 4; i++) {
            stalled.add(client.sendAsync(
                    HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + "/stalled"))
                            .timeout(Duration.ofSeconds(15)).GET().build(),
                    HttpResponse.BodyHandlers.ofString()));
        }

        for (CompletableFuture<HttpResponse<String>> f : stalled) {
            assertEquals(503, f.get(15, TimeUnit.SECONDS).statusCode(),
                    "every blocked request must get the timeout outcome");
        }

        // All four threads must now be free: a healthy request has to be served.
        long started = System.nanoTime();
        HttpResponse<String> after = get("/healthy");
        long elapsedMs = (System.nanoTime() - started) / 1_000_000;

        assertEquals(200, after.statusCode(), "the pool must be usable once the blocked waits released");
        assertTrue(elapsedMs < 5_000, "the freed pool answered slowly: " + elapsedMs + " ms");
    }

    @Test
    void aHandlerThatAlreadyAnsweredDoesNotLeakASecondResponse() throws Exception {
        // Answers 200 and then raises the timeout, the race the wrapper must survive.
        server.createContext("/answered-then-timeout", new BoundedHandler(exchange -> {
            byte[] b = "{\"first\":1}".getBytes();
            exchange.sendResponseHeaders(200, b.length);
            exchange.getResponseBody().write(b);
            exchange.getResponseBody().close();
            throw new BoundedWait.Timeout(BOUND_MS);
        }, BOUND_MS, gson, warnings::add));

        HttpResponse<String> r = get("/answered-then-timeout");

        // The client keeps the first response; the second send fails and is reported,
        // not thrown onto the pool thread.
        assertEquals(200, r.statusCode(), "the client keeps the first response");
        assertEquals("{\"first\":1}", r.body());
        assertFalse(warnings.isEmpty(), "the swallowed second send must be reported, not silent");
    }
}
