package com.sigmastrain.aiplayermod.api;

import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.function.Consumer;

/**
 * The dedicated {@code /health} listener: one port, one route, its own executor.
 *
 * <p>It exists because sharing a listener with the rest of the API silently
 * defeats the probe. {@code /health} never touches the server thread, but it
 * queues for a thread from the same fixed pool as routes that hop to that thread
 * and block, so when the tick is held the pool fills with handlers waiting on the
 * very stall being detected and the probe times out instead of answering. Two
 * production stalls went silent this way (2026-10-27, 2026-10-28).
 *
 * <p>Nothing else is registered here. The probe port answers {@code /health} and
 * nothing else, so the key-free exception it inherits from the kubelet cannot
 * widen into key-free access to the API.
 */
public final class HealthProbeListener {
    private static final int THREADS = 2;

    private final int port;
    private final HttpApiServer.HealthHandler handler;
    private HttpServer server;
    private ExecutorService executor;

    public HealthProbeListener(int port, HttpApiServer.HealthHandler handler) {
        this.port = port;
        this.handler = handler;
    }

    /**
     * Binds and starts. On failure it logs exactly one ERROR naming the port and
     * leaves nothing bound; it deliberately does not fall back to the main
     * listener, which would restore the shared executor in the one case that
     * matters most.
     *
     * @return true if the listener is serving
     */
    public boolean start(Consumer<String> error) {
        try {
            server = HttpServer.create(new InetSocketAddress("0.0.0.0", port), 0);
            // Two threads: the probe has to answer while a probe request is
            // already in flight. A queued handler here would be the same bug in
            // miniature.
            executor = Executors.newFixedThreadPool(THREADS, r -> {
                Thread t = new Thread(r, "aiplayermod-health-probe");
                t.setDaemon(true);
                return t;
            });
            server.setExecutor(executor);
            // No auth wrapper: the kubelet holds no API key, and this listener
            // serves no route that needs one.
            server.createContext("/health", handler::handle);
            server.start();
            return true;
        } catch (IOException e) {
            error.accept("Failed to start the dedicated /health listener on port " + port
                    + "; /health is not being served. The rest of the API is unaffected: " + e);
            close();
            return false;
        }
    }

    public int port() {
        return port;
    }

    /** True once {@link #start} has returned true and before {@link #stop}. */
    public boolean isServing() {
        return server != null;
    }

    /**
     * Closes whichever listeners were created. Safe to call after a failed
     * start, and safe to call twice.
     */
    public void stop() {
        HttpServer s = server;
        server = null;
        if (s != null) {
            s.stop(0);
        }
        close();
    }

    private void close() {
        ExecutorService e = executor;
        executor = null;
        if (e != null) {
            e.shutdownNow();
        }
    }
}
