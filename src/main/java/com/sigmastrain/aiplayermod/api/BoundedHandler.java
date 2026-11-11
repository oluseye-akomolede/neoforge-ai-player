package com.sigmastrain.aiplayermod.api;

import com.google.gson.Gson;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;

import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.function.Consumer;

/**
 * Wraps a handler so a bounded-wait expiry becomes the 503 the api-http spec
 * defines, rather than a dropped connection or an unhandled exception on a pool
 * thread.
 *
 * <p>The catch lives here, at the single boundary every API route passes through,
 * so it cannot be forgotten at one of the 47 waiting call sites. This class holds
 * no Minecraft types: the whole point is that the timeout path can be tested
 * without a game classpath. A caller that needs a different reporting channel
 * supplies the warn sink.
 */
public final class BoundedHandler implements HttpHandler {

    /** Where an unrepairable second send is reported. Never silent. */
    public interface Warn extends Consumer<String> {
    }

    private final HttpHandler delegate;
    private final long joinTimeoutMs;
    private final Gson gson;
    private final Warn warn;

    public BoundedHandler(HttpHandler delegate, long joinTimeoutMs, Gson gson, Warn warn) {
        this.delegate = delegate;
        this.joinTimeoutMs = joinTimeoutMs;
        this.gson = gson;
        this.warn = warn;
    }

    @Override
    public void handle(HttpExchange exchange) throws IOException {
        try {
            delegate.handle(exchange);
        } catch (BoundedWait.Timeout e) {
            reportTimeout(exchange, e);
        }
    }

    private void reportTimeout(HttpExchange exchange, BoundedWait.Timeout e) {
        // The request may already have been answered if the timeout raced a send
        // that then completed. HttpExchange.sendResponseHeaders declares only
        // IOException; on a second send the JDK raises IOException("headers already
        // sent") and the client keeps the FIRST response, so swallowing it here is
        // safe rather than lossy. Anything else escaping would be an unhandled
        // exception on a pool thread, so RuntimeException is caught too.
        try {
            byte[] body = gson.toJson(Map.of(
                    "error", "server thread did not respond within " + joinTimeoutMs + " ms",
                    "timeout_ms", joinTimeoutMs)).getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(503, body.length);
            try (OutputStream os = exchange.getResponseBody()) {
                os.write(body);
            }
        } catch (IOException | RuntimeException unanswered) {
            warn.accept("API timeout could not be reported to client: " + unanswered);
        }
    }
}
