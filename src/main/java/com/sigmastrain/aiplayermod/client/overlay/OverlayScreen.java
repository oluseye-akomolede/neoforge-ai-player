package com.sigmastrain.aiplayermod.client.overlay;

import com.sigmastrain.aiplayermod.network.OverlayPayloads;
import net.minecraft.ChatFormatting;
import net.minecraft.client.gui.GuiGraphics;
import net.minecraft.client.gui.components.Button;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.network.chat.Component;
import net.neoforged.neoforge.network.PacketDistributor;

import java.util.ArrayList;
import java.util.List;

/**
 * The overlay — the player's seat in the network.
 *
 * <p>Phase 1 scope: fleet view, per-bot directive card, interrupt. It never
 * pauses the game and keeps the world visible (translucent fill, no blur):
 * this is a HUD you stand inside, not a menu you hide in.
 *
 * <p>Keys: H toggles (tap latches, hold-release peeks), 1–9 jump to a bot,
 * 0/TAB back to fleet, ESC closes.
 */
public class OverlayScreen extends Screen {

    // ── palette ──────────────────────────────────────────────────────────
    private static final int PANEL_BG = 0xC008090C;
    private static final int PANEL_EDGE = 0xFF1E3A3A;
    private static final int ROW_BG = 0x66101820;
    private static final int ROW_HOVER = 0x8817303A;
    private static final int ACCENT = 0xFF54E8E0;
    private static final int TEXT_DIM = 0xFF7A8B8B;
    private static final int TEXT = 0xFFDDE8E8;

    private final long openedAt = System.currentTimeMillis();
    /** -1 = fleet view; -2 = inbox; <= -10 = extension tab (-10 - index);
     *  otherwise index into the snapshot's bot list. */
    private int selected = -1;
    private static final int VIEW_INBOX = -2;
    private static final int VIEW_DRONES = -3;
    private static final int VIEW_EXT_BASE = -10;

    private OverlayTab activeExtension() {
        if (selected > VIEW_EXT_BASE) return null;
        var tabs = OverlayExtensions.tabs();
        int i = VIEW_EXT_BASE - selected;
        return i < tabs.size() ? tabs.get(i) : null;
    }

    // Inbox state. Selecting an item opens a MODAL: full-panel takeover
    // with the error text scrollable and every ruling control inside it.
    // ESC steps back to the list, never out of the overlay.
    private OverlayPayloads.InboxState inbox = OverlayClientState.inbox();
    private String inboxSelectedId = "";
    private boolean inboxModalOpen = false;
    private int inboxTextScroll = 0;
    private net.minecraft.client.gui.components.EditBox inboxAnswer;
    // The failing directive, field-by-field editable. Keys are directive
    // fields; edits ride the ruling (or the L5 consult) as a JSON envelope.
    private final java.util.Map<String, net.minecraft.client.gui.components.EditBox>
            inboxDirBoxes = new java.util.LinkedHashMap<>();
    private String inboxDirKind = "";

    private enum UnitTab { STATUS, VAULT, CHANNEL, COMMAND, MIND, TALK, STANDING }
    private UnitTab unitTab = UnitTab.STATUS;

    private OverlayPayloads.FleetSnapshot snapshot = OverlayClientState.snapshot();
    private Button interruptButton;

    private net.minecraft.client.gui.components.EditBox fleetInput;

    // Vault tab state
    private net.minecraft.client.gui.components.EditBox vaultSearch;
    private OverlayPayloads.VaultSnapshot vault;
    private String selectedItem = "";
    private int vaultScroll = 0;
    private static final int VAULT_ROWS = 8;

    /**
     * Two-step confirm for destructive orders: the first click arms the
     * button (label goes red) for 3 s; only a second click inside the window
     * fires. No modals — the same button asks its own question.
     */
    private String armedKey = "";
    private long armedUntil = 0;

    private boolean confirmGate(String key, Button b, String armedLabel) {
        long now = System.currentTimeMillis();
        if (key.equals(armedKey) && now < armedUntil) {
            armedKey = "";
            return true;
        }
        armedKey = key;
        armedUntil = now + 3000;
        if (b != null) b.setMessage(Component.literal(armedLabel));
        return false;
    }

    /** Restore any armed button whose window lapsed (called from render). */
    private void tickConfirmArm() {
        if (!armedKey.isEmpty() && System.currentTimeMillis() >= armedUntil) {
            armedKey = "";
            buildWidgets(); // restore original labels
        }
    }

    // Channel tab state
    private net.minecraft.client.gui.components.EditBox channelItem;
    private net.minecraft.client.gui.components.EditBox channelCount;
    private net.minecraft.client.gui.components.Checkbox channelInterrupt;
    private Button channelCommit;
    private OverlayPayloads.ChannelQuoteReply quote;

    // ── expansion card: click any transcript/inbox/mind line to read ALL
    // of it, word-wrapped, on top of the panel. Click again to dismiss. ──
    private String expandedText = null;

    // ── dropdown: a real picker for the Cmd tab (kinds, item options) ──
    private List<String> ddItems = null;
    private List<String> ddAll = null;
    private String ddTitle = "";
    private String ddFilter = "";
    private int ddScroll = 0;
    private java.util.function.Consumer<String> ddPick = null;

    private void openDropdown(String title, List<String> items,
                              java.util.function.Consumer<String> pick) {
        ddTitle = title;
        ddAll = items;
        ddItems = items;
        ddFilter = "";
        ddScroll = 0;
        ddPick = pick;
    }

    private void applyDdFilter() {
        if (ddAll == null) return;
        String f = ddFilter.toLowerCase();
        ddItems = f.isEmpty() ? ddAll
                : ddAll.stream().filter(i -> i.toLowerCase().contains(f)).toList();
        ddScroll = 0;
    }

    private static final int DD_ROWS = 10;

    private void renderOverlays(GuiGraphics g, int mouseX, int mouseY) {
        int px = panelX(), py = panelY(), pw = panelW(), ph = panelH();
        // Tooltip-level Z so the pickers always draw ABOVE widgets — without
        // this, batched widget rendering could sit on top of the card
        // (live report: "the text opens behind the overlay window").
        g.pose().pushPose();
        g.pose().translate(0, 0, 400);
        try {
        if (ddItems != null) {
            int w = Math.min(260, pw - 40);
            int rows = Math.min(DD_ROWS, ddItems.size());
            int h = 18 + rows * 12 + 6;
            int x = px + (pw - w) / 2, y = py + 40;
            g.fill(x, y, x + w, y + h, 0xF0090D12);
            g.fill(x, y, x + w, y + 1, ACCENT);
            g.drawString(font, "§b" + ddTitle + " §8(" + ddItems.size() + ")"
                    + (ddFilter.isEmpty() ? " §8· type to search" : " §e" + ddFilter + "_"),
                    x + 6, y + 5, TEXT);
            for (int i = 0; i < rows; i++) {
                int idx = ddScroll + i;
                if (idx >= ddItems.size()) break;
                int ry = y + 18 + i * 12;
                boolean hover = mouseX >= x && mouseX < x + w && mouseY >= ry && mouseY < ry + 12;
                if (hover) g.fill(x + 2, ry, x + w - 2, ry + 12, ROW_HOVER);
                g.drawString(font, trim(ddItems.get(idx), w - 16), x + 6, ry + 2,
                        hover ? ACCENT : TEXT);
            }
            if (ddItems.size() > DD_ROWS) {
                g.drawString(font, "§8scroll · " + (ddScroll + 1) + "-"
                        + Math.min(ddItems.size(), ddScroll + DD_ROWS), x + 6, y + h - 4, TEXT_DIM);
            }
        } else if (expandedText != null) {
            int w = pw - 32;
            var lines = font.split(net.minecraft.network.chat.FormattedText.of(expandedText), w - 16);
            int h = Math.min(lines.size(), 14) * 10 + 16;
            int x = px + 16, y = py + 50;
            g.fill(x, y, x + w, y + h, 0xF0090D12);
            g.fill(x, y, x + w, y + 1, ACCENT);
            for (int i = 0; i < Math.min(lines.size(), 14); i++) {
                g.drawString(font, lines.get(i), x + 8, y + 8 + i * 10, TEXT);
            }
        }
        } finally {
            g.pose().popPose();
        }
    }

    /** True = the click was consumed by an overlay (dropdown / expansion). */
    private boolean overlayClicked(double mouseX, double mouseY) {
        if (ddItems != null) {
            int px = panelX(), pw = panelW(), py = panelY();
            int w = Math.min(260, pw - 40);
            int rows = Math.min(DD_ROWS, ddItems.size());
            int x = px + (pw - w) / 2, y = py + 40;
            for (int i = 0; i < rows; i++) {
                int idx = ddScroll + i;
                if (idx >= ddItems.size()) break;
                int ry = y + 18 + i * 12;
                if (mouseX >= x && mouseX < x + w && mouseY >= ry && mouseY < ry + 12) {
                    var pick = ddPick;
                    String v = ddItems.get(idx);
                    ddItems = null;
                    ddAll = null;
                    ddPick = null;
                    if (pick != null) pick.accept(v);
                    return true;
                }
            }
            ddItems = null;
            ddAll = null;
            ddPick = null;
            return true; // any click outside the list closes it
        }
        if (expandedText != null) {
            expandedText = null;
            return true;
        }
        return false;
    }

    public OverlayScreen() {
        super(Component.literal("Hive Overlay"));
    }

    // ── lifecycle ────────────────────────────────────────────────────────

    @Override
    protected void init() {
        PacketDistributor.sendToServer(new OverlayPayloads.OverlaySubscribe(true));
        buildWidgets();
    }

    @Override
    public void removed() {
        PacketDistributor.sendToServer(new OverlayPayloads.OverlaySubscribe(false));
        super.removed();
    }

    @Override
    public boolean isPauseScreen() { return false; }

    /** Translucent fill only — no vanilla blur; the world stays readable. */
    @Override
    public void renderBackground(GuiGraphics g, int mouseX, int mouseY, float partialTick) {
        g.fill(0, 0, this.width, this.height, 0x50000000);
    }

    private Button anchorBtn;

    public void onSnapshot(OverlayPayloads.FleetSnapshot snap) {
        this.snapshot = snap;
        if (selected >= snap.bots().size()) selected = -1;
        refreshInterruptButton();
        OverlayPayloads.BotEntry cur = selectedBot();
        if (anchorBtn != null && cur != null) {
            anchorBtn.setMessage(Component.literal(
                    cur.anchored() ? "§b⚓ Anchored" : "§8⚓ Anchor"));
        }
    }

    public void onVault(OverlayPayloads.VaultSnapshot snap) {
        this.vault = snap;
        vaultScroll = 0;
    }

    public void onQuote(OverlayPayloads.ChannelQuoteReply reply) {
        this.quote = reply;
        if (channelCommit != null) {
            // Known is the only gate: the CHANNEL directive meditates for
            // any missing XP, so "can't afford" just means "takes longer".
            channelCommit.active = reply.known();
            channelCommit.setMessage(Component.literal(
                    reply.known() && !reply.affordable() ? "§d🧘 Meditate+Channel" : "⚡ Channel"));
        }
    }

    // ── widgets ──────────────────────────────────────────────────────────

    private void buildWidgets() {
        clearWidgets();
        int px = panelX(), py = panelY(), pw = panelW();

        // Tab strip: [Fleet] [Inbox(n)] then one per bot.
        int tx = px + 8;
        int ty = py + 22;
        addTab(tx, ty, 44, "Fleet", -1);
        tx += 48;
        int pending = inbox.items().size();
        String inboxLabel = pending > 0 ? "Inbox §6(" + pending + ")" : "Inbox";
        int iw = Math.max(48, font.width(inboxLabel) + 14);
        addTab(tx, ty, iw, inboxLabel, VIEW_INBOX);
        tx += iw + 4;
        var extTabs = OverlayExtensions.tabs();
        for (int i = 0; i < extTabs.size(); i++) {
            int ew = Math.max(44, font.width(extTabs.get(i).label()) + 14);
            addTab(tx, ty, ew, extTabs.get(i).label(), VIEW_EXT_BASE - i);
            tx += ew + 4;
        }
        List<OverlayPayloads.BotEntry> bots = snapshot.bots();
        int droneCount = 0;
        for (int i = 0; i < bots.size(); i++) {
            if (isDrone(bots.get(i))) {
                droneCount++;
                continue;
            }
            int w = Math.max(44, font.width(bots.get(i).name()) + 14);
            addTab(tx, ty, w, bots.get(i).name(), i);
            tx += w + 4;
        }
        // The swarm shares ONE tab however large it grows (design ruling:
        // the UI must survive 20+ drones). Individuals are reached through
        // it — and the currently selected drone earns a temporary tab.
        if (droneCount > 0) {
            String dl = "§fDrones (" + droneCount + ")";
            int dw = Math.max(44, font.width(dl) + 14);
            addTab(tx, ty, dw, dl, VIEW_DRONES);
            tx += dw + 4;
        }
        if (selected >= 0 && selected < bots.size() && isDrone(bots.get(selected))) {
            String dn = bots.get(selected).name();
            int dw = Math.max(44, font.width(dn) + 14);
            addTab(tx, ty, dw, "§b" + dn, selected);
        }

        // Interrupt — only meaningful on a bot tab with an ACTIVE directive.
        // Destructive (kills in-flight work), so it asks itself twice.
        interruptButton = Button.builder(Component.literal("■ Interrupt"), b -> {
                    OverlayPayloads.BotEntry e = selectedBot();
                    if (e != null && e.directiveId() >= 0
                            && confirmGate("interrupt", interruptButton, "§c■ confirm?")) {
                        PacketDistributor.sendToServer(
                                new OverlayPayloads.InterruptDirective(e.id(), e.directiveId()));
                        interruptButton.setMessage(Component.literal("■ Interrupt"));
                    }
                })
                .bounds(px + pw - 96, py + 22, 88, 18)
                .build();
        addRenderableWidget(interruptButton);
        refreshInterruptButton();

        if (activeExtension() != null) return;

        if (selected == VIEW_INBOX) {
            buildInboxWidgets(px, py, pw);
            return;
        }
        if (selected == VIEW_DRONES) return;

        // Fleet view: one order box for the whole fleet. Typed orders fan
        // out verbatim; plain language is partitioned per bot by the hive.
        if (selected == -1) {
            int fy = py + 46 + snapshotRows() * 30 + 6;
            fleetInput = new net.minecraft.client.gui.components.EditBox(
                    font, px + 8, fy, pw - 96, 14, Component.literal("fleet order"));
            fleetInput.setHint(Component.literal("order the whole fleet, plainly…"));
            fleetInput.setMaxLength(300);
            addRenderableWidget(fleetInput);
            addRenderableWidget(Button.builder(Component.literal("§6Fleet ▶"), b -> {
                        String text = fleetInput.getValue().trim();
                        if (text.isEmpty()) return;
                        var params = new com.google.gson.JsonObject();
                        params.addProperty("text", text);
                        PacketDistributor.sendToServer(new OverlayPayloads.SubmitOrder(
                                "fleet", "TEXT", params.toString()));
                        fleetInput.setValue("");
                    })
                    .bounds(px + pw - 84, fy, 76, 14).build());
        }

        // Unit sub-tabs + their widgets.
        OverlayPayloads.BotEntry unit = selectedBot();
        if (unit != null) {
            int sy = py + 44;
            addTabSmall(px + 8, sy, "Status", () -> switchUnitTab(UnitTab.STATUS));
            addTabSmall(px + 58, sy, "Vault", () -> switchUnitTab(UnitTab.VAULT));
            addTabSmall(px + 108, sy, "Channel", () -> switchUnitTab(UnitTab.CHANNEL));
            addTabSmall(px + 158, sy, "Cmd", () -> switchUnitTab(UnitTab.COMMAND));
            addTabSmall(px + 208, sy, "Mind", () -> switchUnitTab(UnitTab.MIND));
            addTabSmall(px + 258, sy, "Talk", () -> switchUnitTab(UnitTab.TALK));
            addTabSmall(px + 308, sy, "Stand", () -> switchUnitTab(UnitTab.STANDING));

            switch (unitTab) {
                case STATUS -> buildStatusWidgets(unit, px, py, pw);
                case VAULT -> buildVaultWidgets(unit, px, py, pw);
                case CHANNEL -> buildChannelWidgets(unit, px, py, pw);
                case COMMAND -> buildCommandWidgets(unit, px, py, pw);
                case MIND -> buildMindWidgets(unit, px, py, pw);
                case TALK -> buildTalkWidgets(unit, px, py, pw);
                case STANDING -> buildStandingWidgets(unit, px, py, pw);
            }
        }
    }

    public void onInbox(OverlayPayloads.InboxState state) {
        this.inbox = state;
        // Keep the selection only if that question is still open.
        if (!inboxSelectedId.isEmpty()
                && state.items().stream().noneMatch(i -> i.id().equals(inboxSelectedId))) {
            inboxSelectedId = "";
        }
        buildWidgets(); // badge count + item buttons
    }

    private OverlayPayloads.InboxItem selectedInboxItem() {
        return inbox.items().stream()
                .filter(i -> i.id().equals(inboxSelectedId))
                .findFirst().orElse(null);
    }

    private static final int INBOX_LIST_ROWS = 5;

    private void buildInboxWidgets(int px, int py, int pw) {
        if (inboxModalOpen && selectedInboxItem() != null) {
            buildInboxModalWidgets(px, py, pw);
            return;
        }
        inboxModalOpen = false;
        List<OverlayPayloads.InboxItem> items = inbox.items();

        // Item list — one button per open question.
        int y = py + 46;
        for (int i = 0; i < Math.min(items.size(), INBOX_LIST_ROWS); i++) {
            OverlayPayloads.InboxItem item = items.get(i);
            String label = (item.id().equals(inboxSelectedId) ? "§b" : "")
                    + item.bot() + "§8: §7" + item.question();
            addRenderableWidget(Button.builder(
                            Component.literal(trim(label, pw - 30)), b -> {
                                inboxSelectedId = item.id();
                                inboxModalOpen = true;
                                inboxTextScroll = 0;
                                buildWidgets();
                            })
                    .bounds(px + 8, y + i * 17, pw - 16, 15).build());
        }

        // Selecting an item opens the modal; list mode holds no editor state.
        inboxDirBoxes.clear();
        inboxDirKind = "";
        inboxAnswer = null;
    }

    /** The ruling payload: plain text when nothing was edited, a JSON
     *  envelope carrying the edited directive when it was. */
    private String inboxEnvelope() {
        String note = inboxAnswer != null ? inboxAnswer.getValue().trim() : "";
        if (inboxDirBoxes.isEmpty()) return note;
        var d = new com.google.gson.JsonObject();
        d.addProperty("kind", inboxDirKind);
        for (var e : inboxDirBoxes.entrySet()) {
            String v = e.getValue().getValue().trim();
            if (!v.isEmpty()) d.addProperty(e.getKey(), v);
        }
        var env = new com.google.gson.JsonObject();
        env.add("directive", d);
        if (!note.isEmpty()) env.addProperty("note", note);
        return env.toString();
    }

    private static final int MODAL_TEXT_ROWS = 8;

    private void buildInboxModalWidgets(int px, int py, int pw) {
        OverlayPayloads.InboxItem sel = selectedInboxItem();
        if (sel == null) return;
        int ph = panelH();
        int dy = py + 52 + MODAL_TEXT_ROWS * 10 + 8;

        addRenderableWidget(Button.builder(Component.literal("§7← Back"), b -> {
                    inboxModalOpen = false;
                    inboxSelectedId = "";
                    buildWidgets();
                })
                .bounds(px + 8, py + 26, 52, 14).build());

        int bx = px + 8;
        for (String opt : sel.options().subList(0, Math.min(sel.options().size(), 6))) {
            int w = Math.min(font.width(opt) + 14, (pw - 16) / 2);
            if (bx + w > px + pw - 8) { bx = px + 8; dy += 18; }
            addRenderableWidget(Button.builder(Component.literal(opt), b ->
                            respond(sel.id(), "choose", opt))
                    .bounds(bx, dy, w, 16).build());
            bx += w + 4;
        }
        if (!sel.options().isEmpty()) dy += 20;

        inboxDirBoxes.clear();
        inboxDirKind = "";
        if (!sel.directiveJson().isEmpty()) {
            try {
                var d = com.google.gson.JsonParser.parseString(sel.directiveJson())
                        .getAsJsonObject();
                inboxDirKind = d.has("kind") ? d.get("kind").getAsString() : "?";
                int fx = px + 8;
                for (var entry : d.entrySet()) {
                    if (entry.getKey().equals("kind")) continue;
                    if (!entry.getValue().isJsonPrimitive()) continue;
                    if (inboxDirBoxes.size() >= 4) break;
                    var box = new net.minecraft.client.gui.components.EditBox(
                            font, fx + 46, dy, 92, 12, Component.literal(entry.getKey()));
                    box.setValue(entry.getValue().getAsString());
                    box.setMaxLength(80);
                    inboxDirBoxes.put(entry.getKey(), box);
                    addRenderableWidget(box);
                    fx += 150;
                    if (fx > px + pw - 150) { fx = px + 8; dy += 16; }
                }
                dy += 18;
            } catch (Exception ignored) {
            }
        }

        inboxAnswer = new net.minecraft.client.gui.components.EditBox(
                font, px + 8, dy, pw - 150, 14, Component.literal("answer"));
        inboxAnswer.setHint(Component.literal("type, then pick where it goes →"));
        inboxAnswer.setMaxLength(200);
        addRenderableWidget(inboxAnswer);
        addRenderableWidget(Button.builder(Component.literal("§a▶ Rule"), b ->
                        respond(sel.id(), "answer", inboxEnvelope()))
                .bounds(px + pw - 138, dy, 44, 14).build());
        addRenderableWidget(Button.builder(Component.literal("§d? L5"), b ->
                        respond(sel.id(), "escalate_l5", inboxEnvelope()))
                .bounds(px + pw - 90, dy, 30, 14).build());
        addRenderableWidget(Button.builder(Component.literal("§c✕"), b ->
                        respond(sel.id(), "cancel", ""))
                .bounds(px + pw - 56, dy, 18, 14).build());
    }

    private void renderInboxModal(GuiGraphics g, int px, int py, int pw) {
        OverlayPayloads.InboxItem sel = selectedInboxItem();
        if (sel == null) return;
        long ageSec = Math.max(0, (System.currentTimeMillis() - sel.atMillis()) / 1000);
        g.drawString(font, "§b" + sel.bot() + " §8" + sel.kind()
                + " · waiting " + ageSec + "s · ESC back", px + 68, py + 29, TEXT);

        // the scrollable error text — the whole point of the modal
        var lines = font.split(net.minecraft.network.chat.FormattedText.of(
                sel.question()), pw - 28);
        int maxScroll = Math.max(0, lines.size() - MODAL_TEXT_ROWS);
        inboxTextScroll = Math.max(0, Math.min(inboxTextScroll, maxScroll));
        int ty = py + 52;
        g.fill(px + 6, ty - 3, px + pw - 6, ty + MODAL_TEXT_ROWS * 10 + 3, ROW_BG);
        for (int i = 0; i < MODAL_TEXT_ROWS; i++) {
            int idx = inboxTextScroll + i;
            if (idx >= lines.size()) break;
            g.drawString(font, lines.get(idx), px + 12, ty + i * 10, TEXT);
        }
        if (lines.size() > MODAL_TEXT_ROWS) {
            g.drawString(font, "§8" + (inboxTextScroll + 1) + "-"
                    + Math.min(lines.size(), inboxTextScroll + MODAL_TEXT_ROWS)
                    + "/" + lines.size() + " scroll", px + pw - 80, ty - 13, TEXT_DIM);
        }
        if (!inboxDirBoxes.isEmpty()) {
            g.drawString(font, "§6✎ " + inboxDirKind + " §8(edit + Rule = resubmit)",
                    px + 8, ty + MODAL_TEXT_ROWS * 10 + 10, TEXT_DIM);
            for (var e : inboxDirBoxes.entrySet()) {
                var box = e.getValue();
                g.drawString(font, "§7" + e.getKey(), box.getX() - 44, box.getY() + 2, TEXT_DIM);
            }
        }
    }

    private void respond(String id, String action, String text) {
        PacketDistributor.sendToServer(new OverlayPayloads.InboxRespond(id, action, text));
        inboxSelectedId = "";
        inboxModalOpen = false;
    }

    private void renderInbox(GuiGraphics g, int px, int y, int pw) {
        List<OverlayPayloads.InboxItem> items = inbox.items();
        if (items.isEmpty()) {
            g.drawString(font, "§8no open questions — the network is certain of itself",
                    px + 10, y + 6, TEXT_DIM);
            return;
        }
        int dy = y + Math.min(items.size(), INBOX_LIST_ROWS) * 17 + 4;
        g.drawString(font, "§8click a question to open it — full error, options,", px + 10, dy + 4, TEXT_DIM);
        g.drawString(font, "§8directive editor and rulings live in that window", px + 10, dy + 15, TEXT_DIM);
    }

    private void switchUnitTab(UnitTab tab) {
        unitTab = tab;
        buildWidgets();
        OverlayPayloads.BotEntry e = selectedBot();
        if (e == null) return;
        if (tab == UnitTab.VAULT) {
            PacketDistributor.sendToServer(new OverlayPayloads.RequestVault(e.id(), ""));
        } else if (tab == UnitTab.CHANNEL) {
            // A fresh quote names the directive the channel would interrupt.
            requestQuote();
        } else if (tab == UnitTab.MIND) {
            PacketDistributor.sendToServer(new OverlayPayloads.RequestThoughts(e.id()));
        } else if (tab == UnitTab.TALK) {
            PacketDistributor.sendToServer(new OverlayPayloads.RequestTalk(e.id()));
        }
    }

    public void onTalk(String bot) {
        // Transcript lives in OverlayClientState; render reads the tail.
    }

    public void onThoughts(String bot) {
        // Data lands in OverlayClientState; render pulls it. Nothing scrolls
        // on its own — newest renders first, the user owns the scroll.
    }

    private void addTabSmall(int x, int y, String label, Runnable action) {
        addRenderableWidget(Button.builder(Component.literal(label), b -> action.run())
                .bounds(x, y, 46, 14).build());
    }

    private void buildStatusWidgets(OverlayPayloads.BotEntry unit, int px, int py, int pw) {
        addRenderableWidget(Button.builder(Component.literal("Equipment…"), b ->
                        PacketDistributor.sendToServer(new OverlayPayloads.OpenEquipment(unit.id())))
                .bounds(px + pw - 96, py + 44, 88, 14)
                .build());

        anchorBtn = addRenderableWidget(Button.builder(
                        Component.literal(unit.anchored() ? "§b⚓ Anchored" : "§8⚓ Anchor"), b -> {
                            OverlayPayloads.BotEntry cur = selectedBot();
                            if (cur == null) return;
                            PacketDistributor.sendToServer(new OverlayPayloads.SubmitOrder(
                                    cur.id(),
                                    cur.anchored() ? "ANCHOR_OFF" : "ANCHOR_ON",
                                    "{}"));
                        })
                .bounds(px + pw - 96, py + 82, 88, 14)
                .build());

        OverlayPayloads.JackState js = OverlayClientState.jackState();
        if (js.active()) {
            addRenderableWidget(Button.builder(Component.literal("§d⏏ Eject"), b -> {
                        PacketDistributor.sendToServer(OverlayPayloads.EjectRequest.INSTANCE);
                        onClose();
                    })
                    .bounds(px + pw - 96, py + 62, 88, 16)
                    .build());
        } else {
            addRenderableWidget(Button.builder(Component.literal("§d◈ Jack in"), b -> {
                        PacketDistributor.sendToServer(new OverlayPayloads.JackIn(unit.id()));
                        // Close so the camera switch isn't hidden behind the panel.
                        onClose();
                    })
                    .bounds(px + pw - 96, py + 62, 88, 16)
                    .build());
        }
    }

    private void buildVaultWidgets(OverlayPayloads.BotEntry unit, int px, int py, int pw) {
        vaultSearch = new net.minecraft.client.gui.components.EditBox(
                font, px + 8, py + 62, pw - 120, 14, Component.literal("search"));
        vaultSearch.setHint(Component.literal("search holdings…"));
        vaultSearch.setResponder(q ->
                PacketDistributor.sendToServer(new OverlayPayloads.RequestVault(unit.id(), q)));
        addRenderableWidget(vaultSearch);

        // Stow all sweeps the whole pack — destructive enough to ask twice.
        addRenderableWidget(Button.builder(Component.literal("Stow all"), b -> {
                    if (confirmGate("stow_all", b, "§cstow ALL?")) {
                        PacketDistributor.sendToServer(
                                new OverlayPayloads.VaultOp(unit.id(), "", 0, true));
                        b.setMessage(Component.literal("Stow all"));
                    }
                })
                .bounds(px + pw - 104, py + 62, 96, 14).build());

        int by = py + 62 + 18 + VAULT_ROWS * 12 + 6;
        addRenderableWidget(Button.builder(Component.literal("↓ Stow 64"), b -> vaultOp(unit, true, 64))
                .bounds(px + 8, by, 76, 14).build());
        addRenderableWidget(Button.builder(Component.literal("↑ Take 16"), b -> vaultOp(unit, false, 16))
                .bounds(px + 88, by, 76, 14).build());
        addRenderableWidget(Button.builder(Component.literal("↑ Take 64"), b -> vaultOp(unit, false, 64))
                .bounds(px + 168, by, 76, 14).build());
        addRenderableWidget(Button.builder(Component.literal("⚡ Channel…"), b -> {
                    switchUnitTab(UnitTab.CHANNEL);
                })
                .bounds(px + 248, by, 84, 14).build());

        // The fabric row — only rendered when a linked terminal is online.
        boolean meOnline = vault != null && "online".equals(vault.meStatus());
        if (meOnline) {
            int my = by + 18;
            addRenderableWidget(Button.builder(Component.literal("§b⇊ ME→bot 64"), b -> meOp(unit, false, 64))
                    .bounds(px + 8, my, 96, 14).build());
            addRenderableWidget(Button.builder(Component.literal("§b⇈ bot→ME 64"), b -> meOp(unit, true, 64))
                    .bounds(px + 108, my, 96, 14).build());
        }

        // Send-to strip: the selected item can leave this bot entirely —
        // to the player's hands or straight into a sibling's vault.
        int ty2 = by + (meOnline ? 36 : 18);
        addRenderableWidget(Button.builder(Component.literal("§e→ You 64"), b ->
                        transfer(unit, "player", 64))
                .bounds(px + 8, ty2, 72, 14).build());
        int bx = px + 84;
        for (OverlayPayloads.BotEntry other : snapshot.bots()) {
            if (other.id().equals(unit.id())) continue;
            int w = Math.max(56, font.width("→ " + other.name()) + 12);
            if (bx + w > px + pw - 8) break; // fleet outgrew the row — v-next: wrap
            addRenderableWidget(Button.builder(Component.literal("§e→ " + other.name()), b ->
                            transfer(unit, "bot:" + other.id(), 64))
                    .bounds(bx, ty2, w, 14).build());
            bx += w + 4;
        }

        // Worn (curios): equip the selected carried item; click a worn row
        // in the list below to take it off (see renderVault + mouseClicked).
        addRenderableWidget(Button.builder(Component.literal("§d⊕ Wear selected"), b -> {
                    if (!selectedItem.isEmpty()) {
                        PacketDistributor.sendToServer(new OverlayPayloads.CuriosOp(
                                unit.id(), true, selectedItem, "", 0));
                    }
                })
                .bounds(px + 8, ty2 + 18, 104, 14).build());
    }

    private void transfer(OverlayPayloads.BotEntry unit, String dest, int count) {
        if (selectedItem.isEmpty()) return;
        PacketDistributor.sendToServer(new OverlayPayloads.VaultTransfer(
                unit.id(), selectedItem, count, dest));
    }

    private void meOp(OverlayPayloads.BotEntry unit, boolean toME, int count) {
        if (selectedItem.isEmpty()) return;
        PacketDistributor.sendToServer(
                new OverlayPayloads.MEOp(unit.id(), selectedItem, count, toME));
    }

    private void vaultOp(OverlayPayloads.BotEntry unit, boolean toVault, int count) {
        if (selectedItem.isEmpty()) return;
        PacketDistributor.sendToServer(
                new OverlayPayloads.VaultOp(unit.id(), selectedItem, count, toVault));
    }

    private void buildChannelWidgets(OverlayPayloads.BotEntry unit, int px, int py, int pw) {
        channelItem = new net.minecraft.client.gui.components.EditBox(
                font, px + 8, py + 62, pw - 116, 14, Component.literal("item"));
        channelItem.setHint(Component.literal("item id (e.g. minecraft:quartz_block)"));
        channelItem.setMaxLength(80);
        if (!selectedItem.isEmpty()) channelItem.setValue(selectedItem);
        channelItem.setResponder(s -> invalidateQuote());
        addRenderableWidget(channelItem);

        channelCount = new net.minecraft.client.gui.components.EditBox(
                font, px + pw - 86, py + 62, 34, 14, Component.literal("count"));
        channelCount.setValue("16");
        channelCount.setMaxLength(3);
        channelCount.setFilter(s -> s.isEmpty() || s.chars().allMatch(Character::isDigit));
        channelCount.setResponder(s -> invalidateQuote());
        addRenderableWidget(channelCount);

        addRenderableWidget(Button.builder(Component.literal("§b▾"), b -> {
                    parseSchemas();
                    for (KindDef k : kinds) {
                        if (!k.type().equals("CHANNEL")) continue;
                        for (ParamDef prm : k.params()) {
                            if (prm.name().equals("target") && !prm.options().isEmpty()) {
                                openDropdown("conjurable items", prm.options(), v -> {
                                    channelItem.setValue(v);
                                    requestQuote();
                                });
                                return;
                            }
                        }
                    }
                })
                .bounds(px + pw - 100, py + 62, 14, 14).build());

        addRenderableWidget(Button.builder(Component.literal("Quote"), b -> requestQuote())
                .bounds(px + pw - 48, py + 62, 40, 14).build());

        channelInterrupt = net.minecraft.client.gui.components.Checkbox.builder(
                        Component.literal("interrupt current directive"), font)
                .pos(px + 8, py + 112)
                .selected(false)
                .build();
        addRenderableWidget(channelInterrupt);

        channelCommit = Button.builder(Component.literal("⚡ Channel"), b -> {
                    OverlayPayloads.ChannelQuoteReply q = quote;
                    if (q == null || !q.known()) return;
                    // Channeling OVER an active directive kills work — that
                    // variant asks twice. A clean channel fires immediately.
                    if (channelInterrupt.selected() && q.activeDirectiveId() >= 0
                            && !confirmGate("channel_interrupt", b, "§c⚡ interrupt + channel?")) {
                        return;
                    }
                    PacketDistributor.sendToServer(new OverlayPayloads.ChannelExecute(
                            q.bot(), q.item(), q.count(),
                            channelInterrupt.selected(), q.activeDirectiveId()));
                    b.setMessage(Component.literal("⚡ Channel"));
                    invalidateQuote();
                })
                .bounds(px + 8, py + 134, 100, 18)
                .build();
        channelCommit.active = false;
        addRenderableWidget(channelCommit);
    }

    // ── Command tab: the schema-driven directive builder ─────────────────

    /** Parsed once per schema push; the agent owns the vocabulary. */
    private record ParamDef(String name, String type, String label,
                            boolean required, List<String> options, String def) {}
    private record KindDef(String type, String label, List<ParamDef> params) {}

    private List<KindDef> kinds = List.of();
    private long kindsParsedFrom = -1;
    private int kindIndex = 0;
    private final java.util.Map<String, net.minecraft.client.gui.components.EditBox>
            paramBoxes = new java.util.LinkedHashMap<>();
    private final java.util.Map<String, Integer> optionCycle = new java.util.HashMap<>();

    private void parseSchemas() {
        String json = OverlayClientState.schemasJson();
        if (json.isEmpty()) { kinds = List.of(); return; }
        if (json.hashCode() == kindsParsedFrom) return;
        kindsParsedFrom = json.hashCode();
        List<KindDef> out = new ArrayList<>();
        try {
            var root = com.google.gson.JsonParser.parseString(json).getAsJsonObject();
            for (var el : root.getAsJsonArray("directives")) {
                var d = el.getAsJsonObject();
                List<ParamDef> params = new ArrayList<>();
                if (d.has("params")) {
                    for (var pe : d.getAsJsonArray("params")) {
                        var p = pe.getAsJsonObject();
                        List<String> options = new ArrayList<>();
                        if (p.has("options")) {
                            for (var o : p.getAsJsonArray("options")) {
                                options.add(o.getAsString());
                            }
                        }
                        params.add(new ParamDef(
                                p.get("name").getAsString(),
                                p.has("type") ? p.get("type").getAsString() : "string",
                                p.has("label") ? p.get("label").getAsString() : p.get("name").getAsString(),
                                p.has("required") && p.get("required").getAsBoolean(),
                                options,
                                p.has("default") ? p.get("default").getAsString() : ""));
                    }
                }
                out.add(new KindDef(d.get("type").getAsString(),
                        d.has("label") ? d.get("label").getAsString() : d.get("type").getAsString(),
                        params));
            }
        } catch (Exception e) {
            // A malformed push renders as "no schemas" rather than crashing
            // the overlay; the agent-side push validates before sending.
        }
        kinds = out;
        kindIndex = Math.min(kindIndex, Math.max(0, kinds.size() - 1));
    }

    private void buildCommandWidgets(OverlayPayloads.BotEntry unit, int px, int py, int pw) {
        parseSchemas();
        paramBoxes.clear();
        if (kinds.isEmpty()) return; // render explains why

        KindDef kind = kinds.get(kindIndex);

        // Kind selector: a real dropdown of every directive the agent offers.
        addRenderableWidget(Button.builder(
                        Component.literal("§b" + kind.label() + " §8(" + kind.type() + ") ▾"), b -> {
                            List<String> labels = new ArrayList<>();
                            for (KindDef k : kinds) labels.add(k.label() + " (" + k.type() + ")");
                            openDropdown("directive", labels, picked -> {
                                for (int i = 0; i < kinds.size(); i++) {
                                    KindDef k = kinds.get(i);
                                    if (picked.equals(k.label() + " (" + k.type() + ")")) {
                                        kindIndex = i;
                                        break;
                                    }
                                }
                                buildWidgets();
                            });
                        })
                .bounds(px + 8, py + 62, 170, 14).build());

        int fy = py + 80;
        for (ParamDef p : kind.params()) {
            boolean coord = p.name().equals("x") || p.name().equals("y") || p.name().equals("z");
            int bw = coord ? 60 : (p.type().equals("int") ? 60 : 150);
            var box = new net.minecraft.client.gui.components.EditBox(
                    font, px + 96, fy, bw, 12, Component.literal(p.name()));
            box.setMaxLength(120);
            if (!p.def().isEmpty()) box.setValue(p.def());
            if (p.type().equals("int") || coord) {
                box.setFilter(s -> s.isEmpty() || s.matches("-?\\d*\\.?\\d*"));
            }
            paramBoxes.put(p.name(), box);
            addRenderableWidget(box);

            // Fields whose schema offers choices get a dropdown, not a
            // guess-the-id text box (player feedback: menus must be USABLE).
            if (!p.options().isEmpty()) {
                addRenderableWidget(Button.builder(Component.literal("§b▾"), b ->
                                openDropdown(p.label(), p.options(), box::setValue))
                        .bounds(px + 96 + bw + 4, fy, 14, 12).build());
            }
            fy += 16;
        }

        // Crosshair fill: x/y/z from whatever block the player is looking at.
        boolean hasCoords = paramBoxes.containsKey("x") && paramBoxes.containsKey("y")
                && paramBoxes.containsKey("z");
        if (hasCoords) {
            addRenderableWidget(Button.builder(Component.literal("§b⌖ crosshair"), b -> {
                        var mc = net.minecraft.client.Minecraft.getInstance();
                        if (mc.hitResult instanceof net.minecraft.world.phys.BlockHitResult hit
                                && hit.getType() != net.minecraft.world.phys.HitResult.Type.MISS) {
                            var pos = hit.getBlockPos();
                            paramBoxes.get("x").setValue(String.valueOf(pos.getX()));
                            paramBoxes.get("y").setValue(String.valueOf(pos.getY()));
                            paramBoxes.get("z").setValue(String.valueOf(pos.getZ()));
                        }
                    })
                    .bounds(px + 8, fy, 80, 14).build());
            fy += 18;
        }

        int finalFy = fy;
        addRenderableWidget(Button.builder(Component.literal("§a▶ Order"), b -> {
                    submitOrder(unit, kind);
                })
                .bounds(px + 8, finalFy + 2, 80, 16).build());

        // ⏲ Keep: the same order, made PERMANENT. What it watches depends
        // on the kind: item kinds watch the ME count of the target;
        // MEDITATE watches the bot's own XP level (keep ≥ N levels — the
        // bot self-funds its anchor and rituals). Kinds with neither
        // meaning simply don't offer the button.
        boolean keepXp = kind.type().equals("MEDITATE");
        boolean keepItem = kind.params().stream().anyMatch(pd -> pd.name().equals("target"));
        if (keepXp || keepItem) {
            standingThreshold = new net.minecraft.client.gui.components.EditBox(
                    font, px + 176, finalFy + 4, 56, 12, Component.literal("threshold"));
            standingThreshold.setHint(Component.literal(keepXp ? "≥ lvl" : "keep ≥"));
            standingThreshold.setFilter(t -> t.isEmpty() || t.chars().allMatch(Character::isDigit));
            standingThreshold.setMaxLength(9);
            addRenderableWidget(standingThreshold);
            addRenderableWidget(Button.builder(Component.literal("§b⏲ Keep"), b -> {
                        String thr = standingThreshold.getValue().trim();
                        if (thr.isEmpty()) return;
                        String watchType = keepXp ? "xp_level" : "me_count";
                        String item;
                        if (keepXp) {
                            item = "xp_level";
                        } else {
                            var box = paramBoxes.get("target");
                            item = box == null ? "" : box.getValue().trim();
                            if (item.isEmpty()) return;
                        }
                        var params = new com.google.gson.JsonObject();
                        for (var e : paramBoxes.entrySet()) {
                            String v = e.getValue().getValue().trim();
                            if (!v.isEmpty()) params.addProperty(e.getKey(), v);
                        }
                        PacketDistributor.sendToServer(new OverlayPayloads.StandingOp(
                                unit.id(), "create", "", watchType, item,
                                Long.parseLong(thr), "gte", kind.type(), params.toString()));
                    })
                    .bounds(px + 92, finalFy + 2, 80, 16).build());
        }
    }

    private net.minecraft.client.gui.components.EditBox standingThreshold;

    private void submitOrder(OverlayPayloads.BotEntry unit, KindDef kind) {
        var params = new com.google.gson.JsonObject();
        for (ParamDef p : kind.params()) {
            var box = paramBoxes.get(p.name());
            String v = box == null ? "" : box.getValue().trim();
            if (v.isEmpty()) {
                if (p.required()) return; // incomplete — render marks required fields
                continue;
            }
            if (p.type().equals("int")) {
                try { params.addProperty(p.name(), (long) Double.parseDouble(v)); }
                catch (NumberFormatException ignored) { }
            } else if (p.name().equals("x") || p.name().equals("y") || p.name().equals("z")
                    || p.type().equals("float")) {
                try { params.addProperty(p.name(), Double.parseDouble(v)); }
                catch (NumberFormatException ignored) { }
            } else {
                params.addProperty(p.name(), v);
            }
        }
        PacketDistributor.sendToServer(new OverlayPayloads.SubmitOrder(
                unit.id(), kind.type(), params.toString()));
    }

    private void renderCommand(GuiGraphics g, OverlayPayloads.BotEntry unit,
                               int px, int y, int pw) {
        if (kinds.isEmpty()) {
            g.drawString(font, "§8no directive schemas yet — is the agent up?",
                    px + 10, y + 4, TEXT_DIM);
            return;
        }
        KindDef kind = kinds.get(kindIndex);
        int fy = y + 18;
        for (ParamDef p : kind.params()) {
            String req = p.required() ? "§c*" : "";
            g.drawString(font, "§7" + p.label() + req, px + 10, fy + 2, TEXT_DIM);
            fy += 16;
        }
        // Recent orders: the honest "did it land" trail.
        var lines = OverlayClientState.ordersFor(unit.name());
        if (!lines.isEmpty()) {
            int oy = fy + 40;
            g.drawString(font, "§8recent orders", px + 10, oy, TEXT_DIM);
            int shown = 0;
            for (int i = lines.size() - 1; i >= 0 && shown < 4; i--, shown++) {
                var o = lines.get(i);
                String color = switch (o.status()) {
                    case "COMPLETED" -> "§a";
                    case "FAILED" -> "§c";
                    case "RUNNING" -> "§b";
                    default -> "§7";
                };
                g.drawString(font, trim("§8#" + o.id() + " §7" + o.kind() + " "
                                + color + o.status() + " §8" + o.detail(), pw - 30),
                        px + 10, oy + 10 + shown * 10, TEXT_DIM);
            }
        }
    }

    public void onStanding(String bot) {
        if (unitTab == UnitTab.STANDING) buildWidgets();
    }

    private void buildStandingWidgets(OverlayPayloads.BotEntry unit, int px, int py, int pw) {
        var rows = OverlayClientState.standingFor(unit.name());
        int y = py + 66;
        for (var st : rows) {
            final String id = st.id();
            addRenderableWidget(Button.builder(
                            Component.literal(st.enabled() ? "§a⏸" : "§8▶"), b ->
                                    PacketDistributor.sendToServer(new OverlayPayloads.StandingOp(
                                            unit.id(), "toggle", id, "", "", 0, "", "", "{}")))
                    .bounds(px + pw - 54, y, 20, 14).build());
            addRenderableWidget(Button.builder(Component.literal("§c✕"), b -> {
                        if (confirmGate("del_standing_" + id, b, "§c✕?")) {
                            PacketDistributor.sendToServer(new OverlayPayloads.StandingOp(
                                    unit.id(), "delete", id, "", "", 0, "", "", "{}"));
                        }
                    })
                    .bounds(px + pw - 30, y, 20, 14).build());
            y += 26;
        }
    }

    private void renderStanding(GuiGraphics g, OverlayPayloads.BotEntry unit,
                                int px, int y, int pw) {
        var rows = OverlayClientState.standingFor(unit.name());
        if (rows.isEmpty()) {
            g.drawString(font, "§8no standing orders — the Cmd tab's ⏲ Keep creates one",
                    px + 10, y + 8, TEXT_DIM);
            g.drawString(font, "§8a standing order maintains a condition forever",
                    px + 10, y + 19, TEXT_DIM);
            return;
        }
        int ry = y + 4;
        for (var st : rows) {
            String cond = st.watchType() + " " + shortName(st.item())
                    + (st.comparator().equals("lte") ? " ≤ " : " ≥ ") + st.threshold();
            String reading = st.reading() < 0 ? "?" : String.valueOf(st.reading());
            g.drawString(font, (st.enabled() ? "§a⏲ " : "§8⏸ ") + cond
                    + " §8→ §7" + st.actionKind(), px + 10, ry + 1, TEXT);
            long ago = st.lastFired() <= 0 ? -1
                    : (System.currentTimeMillis() - st.lastFired()) / 1000;
            g.drawString(font, "§8now: §7" + reading + " §8· last: §7"
                    + (ago < 0 ? "never" : ago + "s ago") + " §8· "
                    + trim(st.lastResult(), pw - 220), px + 14, ry + 12, TEXT_DIM);
            ry += 26;
        }
    }

    public void onOrders(String bot) {
        // Data lives in OverlayClientState; render pulls it.
    }

    private void requestQuote() {
        OverlayPayloads.BotEntry e = selectedBot();
        if (e == null || channelItem == null) return;
        String item = channelItem.getValue().trim();
        if (item.isEmpty()) return;
        int n = 1;
        try { n = Integer.parseInt(channelCount.getValue().trim()); } catch (Exception ignored) {}
        PacketDistributor.sendToServer(new OverlayPayloads.ChannelQuote(e.id(), item, n));
    }

    private void invalidateQuote() {
        quote = null;
        if (channelCommit != null) channelCommit.active = false;
    }

    private void addTab(int x, int y, int w, String label, int index) {
        addRenderableWidget(Button.builder(Component.literal(label), b -> {
            selectUnit(index);
        }).bounds(x, y, w, 16).build());
    }

    /** Switching bots resets the sub-tab and per-bot caches. */
    private void selectUnit(int index) {
        if (index != selected) {
            unitTab = UnitTab.STATUS;
            vault = null;
            quote = null;
            selectedItem = "";
            vaultScroll = 0;
            mindScroll = 0;
            mindPaused = false;
            mindFrozen = List.of();
        }
        selected = index;
        buildWidgets();
        OverlayTab ext = activeExtension();
        if (ext != null) ext.onOpen();
    }

    private void refreshInterruptButton() {
        if (interruptButton == null) return;
        OverlayPayloads.BotEntry e = selectedBot();
        interruptButton.visible = e != null;
        interruptButton.active = e != null && "ACTIVE".equals(e.directiveStatus());
    }

    private OverlayPayloads.BotEntry selectedBot() {
        List<OverlayPayloads.BotEntry> bots = snapshot.bots();
        return (selected >= 0 && selected < bots.size()) ? bots.get(selected) : null;
    }

    // ── layout ───────────────────────────────────────────────────────────

    private int panelX() { return Math.max(12, (width - panelW()) / 2); }
    private int panelY() { return Math.max(12, height / 12); }
    private int panelW() { return Math.min(440, width - 24); }
    private int panelH() {
        if (activeExtension() != null || selected == VIEW_DRONES) {
            return height - panelY() - 12;
        }
        return Math.min(50 + 26 + snapshotRows() * 30 + 90, height - panelY() - 12);
    }

    private static final int FLEET_ROWS = 6;
    private static final int DRONE_LIST_ROWS = 10;
    private int fleetScroll = 0;
    private int droneListScroll = 0;

    private int snapshotRows() {
        return Math.max(1, Math.min(FLEET_ROWS, snapshot.bots().size()));
    }

    static boolean isDrone(OverlayPayloads.BotEntry e) {
        return e.name().matches("Drone\\d+");
    }

    /** Fleet, sorted: the five originals first, then drones by number. */
    private List<OverlayPayloads.BotEntry> sortedFleet() {
        List<OverlayPayloads.BotEntry> out = new java.util.ArrayList<>(snapshot.bots());
        out.sort(java.util.Comparator
                .comparing((OverlayPayloads.BotEntry e) -> isDrone(e))
                .thenComparing(e -> isDrone(e)
                        ? String.format("%09d", Long.parseLong(e.name().substring(5)))
                        : e.name()));
        return out;
    }

    private int snapshotIndexOf(OverlayPayloads.BotEntry e) {
        List<OverlayPayloads.BotEntry> bots = snapshot.bots();
        for (int i = 0; i < bots.size(); i++) {
            if (bots.get(i).id().equals(e.id())) return i;
        }
        return -1;
    }

    // ── render ───────────────────────────────────────────────────────────

    @Override
    public void render(GuiGraphics g, int mouseX, int mouseY, float partialTick) {
        super.render(g, mouseX, mouseY, partialTick);

        int px = panelX(), py = panelY(), pw = panelW(), ph = panelH();
        g.fill(px, py, px + pw, py + ph, PANEL_BG);
        g.fill(px, py, px + pw, py + 1, PANEL_EDGE);
        g.fill(px, py + ph - 1, px + pw, py + ph, PANEL_EDGE);

        // Header: title + link state.
        long age = OverlayClientState.ageMillis();
        String link = age > 3000 ? "§cNO LINK" : age > 1200 ? "§e~" : "§a●";
        OverlayPayloads.BotEntry headerBot = selectedBot();
        OverlayTab extHdr = activeExtension();
        String view = extHdr != null ? "§7" + extHdr.label().toLowerCase()
                : selected == VIEW_DRONES ? "§7drone roster"
                : selected == VIEW_INBOX ? "§7inbox"
                : selected < 0 ? "§7fleet"
                : headerBot != null ? "§b" + headerBot.name() : "§7unit";
        g.drawString(font, "§lHIVE§r §8// " + view, px + 8, py + 8, ACCENT);
        g.drawString(font, link, px + pw - 40, py + 8, TEXT);

        String ack = OverlayClientState.recentAck();
        if (!ack.isEmpty()) {
            g.drawString(font, ack, px + 8, py + ph - 12, 0xFFFFD54F);
        }

        OverlayTab ext = activeExtension();
        if (ext != null) {
            ext.render(g, font, px, py + 46, pw, panelH() - 46, mouseX, mouseY);
        } else if (selected == VIEW_INBOX) {
            if (inboxModalOpen && selectedInboxItem() != null) {
                renderInboxModal(g, px, py, pw);
            } else {
                renderInbox(g, px, py + 46, pw);
            }
        } else if (selected == VIEW_DRONES) {
            renderDroneRoster(g, px, py + 46, pw, mouseX, mouseY);
        } else if (selected < 0) {
            renderFleet(g, px, py + 46, pw, mouseX, mouseY);
        } else {
            OverlayPayloads.BotEntry e = selectedBot();
            if (e != null) {
                int contentY = py + 62;
                switch (unitTab) {
                    case STATUS -> renderBotCard(g, e, px, contentY, pw);
                    case VAULT -> renderVault(g, e, px, contentY + 18, pw, mouseX, mouseY);
                    case CHANNEL -> renderChannel(g, e, px, contentY + 20, pw);
                    case COMMAND -> renderCommand(g, e, px, contentY + 2, pw);
                    case MIND -> renderMind(g, e, px, contentY + 2, pw);
                    case TALK -> renderTalk(g, e, px, contentY + 2, pw);
                    case STANDING -> renderStanding(g, e, px, contentY + 2, pw);
                }
            }
        }

        // The agent is the network's spine — say so the moment it goes quiet.
        int silent = OverlayClientState.agentSilentSeconds();
        if (silent > 0) {
            String warn = silent >= 999 ? "§c⚠ agent has never reported"
                    : "§c⚠ agent silent " + silent + "s — orders will queue, nothing executes";
            g.drawString(font, warn, px + 8, py + ph - 36, 0xFFFF6659);
        }

        tickConfirmArm();
        g.drawString(font, "§81-9 unit · 0 fleet · H close", px + 8, py + ph - 24, TEXT_DIM);

        renderOverlays(g, mouseX, mouseY);
    }

    private List<OverlayPayloads.BotEntry> droneList() {
        List<OverlayPayloads.BotEntry> out = new java.util.ArrayList<>();
        for (OverlayPayloads.BotEntry e : sortedFleet()) {
            if (isDrone(e)) out.add(e);
        }
        return out;
    }

    private void renderDroneRoster(GuiGraphics g, int px, int y, int pw, int mouseX, int mouseY) {
        List<OverlayPayloads.BotEntry> ds = droneList();
        if (ds.isEmpty()) {
            g.drawString(font, "§8no drones — gestate them from the Hive tab", px + 10, y + 6, TEXT_DIM);
            return;
        }
        int maxScroll = Math.max(0, ds.size() - DRONE_LIST_ROWS);
        droneListScroll = Math.max(0, Math.min(droneListScroll, maxScroll));
        if (maxScroll > 0) {
            g.drawString(font, "§8" + (droneListScroll + 1) + "-"
                            + Math.min(ds.size(), droneListScroll + DRONE_LIST_ROWS)
                            + "/" + ds.size() + " scroll",
                    px + pw - 76, y - 12, TEXT_DIM);
        }
        for (int i = droneListScroll; i < Math.min(ds.size(), droneListScroll + DRONE_LIST_ROWS); i++) {
            OverlayPayloads.BotEntry e = ds.get(i);
            int ry = y + (i - droneListScroll) * 17;
            boolean hover = mouseX >= px + 4 && mouseX <= px + pw - 4
                    && mouseY >= ry && mouseY < ry + 16;
            g.fill(px + 4, ry, px + pw - 4, ry + 16, hover ? ROW_HOVER : ROW_BG);
            g.drawString(font, "§f" + e.name() + " §8" + shortDim(e.dimension())
                    + " §7" + Math.round(e.health()) + "♥", px + 10, ry + 4, TEXT);
            g.drawString(font, directiveLine(e), px + 170, ry + 4,
                    statusColor(e.directiveStatus()));
        }
    }

    private void renderFleet(GuiGraphics g, int px, int y, int pw, int mouseX, int mouseY) {
        List<OverlayPayloads.BotEntry> bots = sortedFleet();
        if (bots.isEmpty()) {
            g.drawString(font, "no bots reporting", px + 10, y + 6, TEXT_DIM);
            return;
        }
        int maxScroll = Math.max(0, bots.size() - FLEET_ROWS);
        fleetScroll = Math.max(0, Math.min(fleetScroll, maxScroll));
        if (maxScroll > 0) {
            g.drawString(font, "§8" + (fleetScroll + 1) + "-"
                            + Math.min(bots.size(), fleetScroll + FLEET_ROWS)
                            + "/" + bots.size() + " scroll",
                    px + pw - 76, y - 12, TEXT_DIM);
        }
        bots = bots.subList(fleetScroll, Math.min(bots.size(), fleetScroll + FLEET_ROWS));
        for (int i = 0; i < bots.size(); i++) {
            OverlayPayloads.BotEntry e = bots.get(i);
            int ry = y + i * 30;
            boolean hover = mouseX >= px + 4 && mouseX <= px + pw - 4 && mouseY >= ry && mouseY < ry + 28;
            g.fill(px + 4, ry, px + pw - 4, ry + 28, hover ? ROW_HOVER : ROW_BG);

            // name + hp bar (⚓ = holding a chunk anchor)
            g.drawString(font, e.name() + (e.anchored() ? " §b⚓" : ""),
                    px + 10, ry + 4, TEXT);
            int barX = px + 10, barY = ry + 16, barW = 60;
            g.fill(barX, barY, barX + barW, barY + 5, 0xFF2A1010);
            int hpw = (int) (barW * Math.max(0, Math.min(1, e.health() / 20f)));
            int hpColor = e.health() > 12 ? 0xFF4CAF50 : e.health() > 5 ? 0xFFFFC107 : 0xFFF44336;
            g.fill(barX, barY, barX + hpw, barY + 5, hpColor);

            // dimension + position
            g.drawString(font, shortDim(e.dimension()) + " §8" + e.x() + "," + e.y() + "," + e.z(),
                    px + 84, ry + 4, TEXT_DIM);

            // directive summary
            g.drawString(font, directiveLine(e), px + 84, ry + 16, statusColor(e.directiveStatus()));
        }

        // Fleet-order umbrellas: group every bot's recent orders by fleet id
        // and show one row per operation with per-bot status chips.
        java.util.Map<String, java.util.List<String>> umbrellas = new java.util.LinkedHashMap<>();
        for (OverlayPayloads.BotEntry e : snapshot.bots()) {
            for (var o : OverlayClientState.ordersFor(e.name())) {
                if (o.fleetId().isEmpty()) continue;
                String chip = switch (o.status()) {
                    case "COMPLETED" -> "§a" + e.name().charAt(0);
                    case "FAILED" -> "§c" + e.name().charAt(0);
                    case "RUNNING" -> "§b" + e.name().charAt(0);
                    default -> "§7" + e.name().charAt(0);
                };
                umbrellas.computeIfAbsent(o.fleetId(), k -> new java.util.ArrayList<>()).add(chip);
            }
        }
        if (!umbrellas.isEmpty()) {
            int uy = y + bots.size() * 30 + 24;
            int shown = 0;
            var ids = new java.util.ArrayList<>(umbrellas.keySet());
            for (int i = ids.size() - 1; i >= 0 && shown < 2; i--, shown++) {
                String fid = ids.get(i);
                g.drawString(font, "§8op §7" + fid + " §8· "
                        + String.join(" ", umbrellas.get(fid)), px + 10, uy + shown * 11, TEXT_DIM);
            }
        }
    }

    private void renderBotCard(GuiGraphics g, OverlayPayloads.BotEntry e, int px, int y, int pw) {
        g.drawString(font, "§l" + e.name(), px + 10, y, TEXT);
        // Plain-text labels: vanilla's font boxes color emoji, and a stats row
        // full of tofu reads worse than words.
        g.drawString(font, String.format("§cHP %.0f§r  §6Food %d§r  §aLv %d§r  §7Kills %d  Deaths %d",
                e.health(), e.food(), e.xpLevel(), e.kills(), e.deaths()), px + 10, y + 12, TEXT);
        g.drawString(font, shortDim(e.dimension()) + " §8@ " + e.x() + ", " + e.y() + ", " + e.z(),
                px + 10, y + 24, TEXT_DIM);

        int cy = y + 40;
        g.fill(px + 6, cy, px + pw - 6, cy + 46, ROW_BG);
        if (e.directiveId() < 0) {
            g.drawString(font, "standing by — no directive", px + 12, cy + 6, TEXT_DIM);
            return;
        }
        g.drawString(font, "§7directive §8#" + e.directiveId(), px + 12, cy + 6, TEXT_DIM);
        String head = e.directiveType() + (e.target().isEmpty() ? "" : " §7→ §r" + e.target());
        g.drawString(font, head, px + 12, cy + 17, statusColor(e.directiveStatus()));
        g.drawString(font, "§8phase: §7" + e.phase() + "  §8status: " + statusGlyph(e.directiveStatus()),
                px + 12, cy + 28, TEXT_DIM);
        g.drawString(font, trim(e.stateLine(), pw - 30), px + 12, cy + 38, TEXT_DIM);
    }

    private void renderVault(GuiGraphics g, OverlayPayloads.BotEntry unit,
                             int px, int y, int pw, int mouseX, int mouseY) {
        OverlayPayloads.VaultSnapshot v = vault;
        if (v == null || !v.bot().equals(unit.name())) {
            g.drawString(font, "requesting holdings…", px + 10, y + 4, TEXT_DIM);
            return;
        }
        List<OverlayPayloads.HoldingEntry> rows = v.entries();
        if (rows.isEmpty()) {
            g.drawString(font, "nothing matches", px + 10, y + 4, TEXT_DIM);
            return;
        }
        int max = Math.min(rows.size(), vaultScroll + VAULT_ROWS);
        for (int i = vaultScroll; i < max; i++) {
            OverlayPayloads.HoldingEntry e = rows.get(i);
            int ry = y + (i - vaultScroll) * 12;
            boolean sel = e.item().equals(selectedItem);
            boolean hover = mouseX >= px + 6 && mouseX <= px + pw - 6
                    && mouseY >= ry && mouseY < ry + 12;
            if (sel || hover) g.fill(px + 6, ry, px + pw - 6, ry + 12, sel ? ROW_HOVER : ROW_BG);
            g.drawString(font, trim(e.name(), pw - 160), px + 10, ry + 2, sel ? ACCENT : TEXT);
            String counts = "§7" + e.carried() + " §8/ §7" + e.vault()
                    + (e.me() > 0 ? " §8/ §b" + fmtLong(e.me()) : "");
            g.drawString(font, counts, px + pw - 12 - font.width(stripCodes(counts)), ry + 2, TEXT_DIM);
        }
        if (rows.size() > VAULT_ROWS) {
            g.drawString(font, "§8" + (vaultScroll + 1) + "-" + max + " of " + rows.size()
                    + (v.totalEntries() > rows.size() ? " (+" + (v.totalEntries() - rows.size()) + " more)" : ""),
                    px + 10, y + VAULT_ROWS * 12 + 2, TEXT_DIM);
        }
        // Legend + ME state share the row under the list; the search box owns
        // the space above it.
        String legend = "§8carried / vault" + ("online".equals(v.meStatus()) ? " / §bME" : "");
        g.drawString(font, legend, px + pw - 12 - font.width(stripCodes(legend)),
                y + VAULT_ROWS * 12 + 2, TEXT_DIM);
        if (!"online".equals(v.meStatus())) {
            // Where the ME buttons would sit, say why they are not there.
            g.drawString(font, "§8ME: " + v.meStatus(), px + 8, y + VAULT_ROWS * 12 + 26, TEXT_DIM);
        }

        // Worn row (curios): what the bot is wearing, click to take off.
        int wy = wornRowY();
        if (v.worn().isEmpty()) {
            g.drawString(font, "§8worn: nothing", px + 120, wy + 3, TEXT_DIM);
        } else {
            int wx = px + 120;
            g.drawString(font, "§dworn:", px + 92, wy + 3, TEXT_DIM);
            for (OverlayPayloads.WornEntry w : v.worn()) {
                String label = "§d[" + shortName(w.item()) + "§8·" + w.slotType() + "§d]";
                int lw = font.width(stripCodes(label));
                if (wx + lw > px + pw - 8) break;
                g.drawString(font, label, wx, wy + 3, TEXT);
                wx += lw + 6;
            }
        }
    }

    /** Y of the worn row — shared by render and click handling. */
    private int wornRowY() {
        boolean meOnline = vault != null && "online".equals(vault.meStatus());
        int by = panelY() + 62 + 18 + VAULT_ROWS * 12 + 6;
        return by + (meOnline ? 36 : 18) + 18;
    }

    private static String fmtLong(long n) {
        if (n >= 1_000_000) return (n / 1_000_000) + "M";
        if (n >= 10_000) return (n / 1_000) + "k";
        return String.valueOf(n);
    }

    private static String stripCodes(String s) {
        return s.replaceAll("§.", "");
    }

    private void renderChannel(GuiGraphics g, OverlayPayloads.BotEntry unit, int px, int y, int pw) {
        OverlayPayloads.ChannelQuoteReply q = quote;
        if (q == null) {
            g.drawString(font, "§8quote an item to see its cost", px + 10, y, TEXT_DIM);
            return;
        }
        if (!q.known()) {
            g.drawString(font, "§cunknown item: " + q.item(), px + 10, y, TEXT);
            return;
        }
        String afford = q.affordable() ? "§a" : "§c";
        // The red cost + disabled commit already say "can't afford" — no
        // extra warning line; it would collide with the widgets below.
        g.drawString(font, String.format("%dx %s §8→ %s%d levels§8 (bot has %d)",
                q.count(), shortName(q.item()), afford, q.costLevels(), q.botLevels()),
                px + 10, y, TEXT);
        if (!q.activeDirective().isEmpty()) {
            g.drawString(font, "§6would interrupt: " + q.activeDirective()
                    + " §8#" + q.activeDirectiveId(), px + 10, y + 12, TEXT);
        } else {
            g.drawString(font, "§8bot is idle — nothing to interrupt", px + 10, y + 12, TEXT_DIM);
        }
    }

    private static String shortName(String id) {
        return id.contains(":") ? id.substring(id.indexOf(':') + 1) : id;
    }

    private int mindScroll = 0;
    private static final int MIND_ROWS = 12;

    // Replay scrubber: pause freezes a copy of the stream so arriving
    // thoughts can't shift rows under the reader; the slider scrubs the
    // frozen window. Live mode resumes exactly where the stream is now.
    private boolean mindPaused = false;
    private List<OverlayPayloads.Thought> mindFrozen = List.of();
    private net.minecraft.client.gui.components.AbstractSliderButton mindSlider;

    private void buildMindWidgets(OverlayPayloads.BotEntry unit, int px, int py, int pw) {
        int by = py + 64 + MIND_ROWS * 12 + 14;
        addRenderableWidget(Button.builder(
                        Component.literal(mindPaused ? "§a▶ Live" : "§e❚❚ Pause"), b -> {
                            mindPaused = !mindPaused;
                            if (mindPaused) {
                                mindFrozen = new ArrayList<>(
                                        OverlayClientState.thoughtsFor(unit.name()));
                            } else {
                                mindScroll = 0;
                            }
                            buildWidgets();
                        })
                .bounds(px + 8, by, 70, 14).build());

        if (mindPaused && mindFrozen.size() > MIND_ROWS) {
            int maxScroll = mindFrozen.size() - MIND_ROWS;
            mindSlider = new net.minecraft.client.gui.components.AbstractSliderButton(
                    px + 84, by, pw - 96, 14, Component.empty(),
                    Math.min(1.0, (double) mindScroll / maxScroll)) {
                @Override
                protected void updateMessage() {
                    int at = (int) Math.round(value * maxScroll);
                    setMessage(Component.literal("§7−" + at + " thoughts"));
                }

                @Override
                protected void applyValue() {
                    mindScroll = (int) Math.round(value * maxScroll);
                }
            };
            addRenderableWidget(mindSlider);
        }
    }

    // Talk tab state — two lanes, explicitly: Chat converses (no plan,
    // ever); Cmd is natural-language ORDERS through the full planning
    // pipeline. The Talk/Order split made visible instead of implied.
    private net.minecraft.client.gui.components.EditBox talkInput;
    private boolean talkCmdMode = false;
    private static final int TALK_ROWS = 10;

    private void buildTalkWidgets(OverlayPayloads.BotEntry unit, int px, int py, int pw) {
        addRenderableWidget(Button.builder(
                        Component.literal(talkCmdMode ? "§8Chat" : "§bChat"), b -> {
                            talkCmdMode = false;
                            buildWidgets();
                        })
                .bounds(px + 258, py + 62, 40, 12).build());
        addRenderableWidget(Button.builder(
                        Component.literal(talkCmdMode ? "§6Cmd" : "§8Cmd"), b -> {
                            talkCmdMode = true;
                            buildWidgets();
                        })
                .bounds(px + 302, py + 62, 40, 12).build());

        int iy = py + 64 + TALK_ROWS * 12 + 6;
        talkInput = new net.minecraft.client.gui.components.EditBox(
                font, px + 8, iy, pw - 66, 14, Component.literal("say"));
        talkInput.setHint(Component.literal(talkCmdMode
                ? "order " + unit.name() + " in plain words… (plans + executes)"
                : "talk to " + unit.name() + "… (no plan is made)"));
        talkInput.setMaxLength(300);
        addRenderableWidget(talkInput);
        addRenderableWidget(Button.builder(
                        Component.literal(talkCmdMode ? "§6Order" : "Send"), b -> sendTalk(unit))
                .bounds(px + pw - 54, iy, 46, 14).build());
        setInitialFocus(talkInput);
    }

    private void sendTalk(OverlayPayloads.BotEntry unit) {
        if (talkInput == null) return;
        String text = talkInput.getValue().trim();
        if (text.isEmpty()) return;
        if (talkCmdMode) {
            var params = new com.google.gson.JsonObject();
            params.addProperty("text", text);
            PacketDistributor.sendToServer(new OverlayPayloads.SubmitOrder(
                    unit.id(), "TEXT", params.toString()));
        } else {
            PacketDistributor.sendToServer(new OverlayPayloads.TalkSend(unit.id(), text));
        }
        talkInput.setValue("");
    }

    /** Chat-style: tail-anchored, oldest of the visible window at the top. */
    private void renderTalk(GuiGraphics g, OverlayPayloads.BotEntry unit, int px, int y, int pw) {
        if (talkCmdMode) {
            var orders = OverlayClientState.ordersFor(unit.name());
            if (orders.isEmpty()) {
                g.drawString(font, "§8no orders yet — say what you want done, plainly",
                        px + 10, y + 16, TEXT_DIM);
                return;
            }
            int shown = 0;
            for (int i = orders.size() - 1; i >= 0 && shown < TALK_ROWS - 1; i--, shown++) {
                var o = orders.get(i);
                String color = switch (o.status()) {
                    case "COMPLETED" -> "§a";
                    case "FAILED" -> "§c";
                    case "RUNNING" -> "§b";
                    default -> "§7";
                };
                g.drawString(font, trim("§8#" + o.id() + " " + color + o.status()
                        + " §7" + o.detail(), pw - 30), px + 10, y + 16 + shown * 12, TEXT);
            }
            return;
        }
        List<OverlayPayloads.TalkLine> lines = OverlayClientState.talkFor(unit.name());
        if (lines.isEmpty()) {
            g.drawString(font, "§8talk is conversation — orders go through chat or Command",
                    px + 10, y + 4, TEXT_DIM);
            return;
        }
        int from = Math.max(0, lines.size() - TALK_ROWS);
        for (int i = from; i < lines.size(); i++) {
            OverlayPayloads.TalkLine t = lines.get(i);
            int ry = y + (i - from) * 12;
            boolean isBot = t.who().equals(unit.name());
            String who = (isBot ? "§b" : "§e") + t.who() + "§8:";
            g.drawString(font, who, px + 8, ry + 2, TEXT);
            g.drawString(font, trim("§7" + t.text(), pw - 90 - font.width(t.who())),
                    px + 14 + font.width(t.who() + ": "), ry + 2, TEXT);
        }
        g.drawString(font, "§8click a line to read it in full", px + 8,
                y + TALK_ROWS * 12 + 2, TEXT_DIM);
    }

    /**
     * The thought stream — L2 retries, L3 plans, criteria verdicts, rendered
     * NEWEST FIRST so nothing ever auto-scrolls out from under the reader.
     */
    private void renderMind(GuiGraphics g, OverlayPayloads.BotEntry unit, int px, int y, int pw) {
        List<OverlayPayloads.Thought> all = mindPaused
                ? mindFrozen
                : OverlayClientState.thoughtsFor(unit.name());
        if (all.isEmpty()) {
            g.drawString(font, "§8no thoughts yet — the agent reports as it plans",
                    px + 10, y + 4, TEXT_DIM);
            return;
        }
        long now = System.currentTimeMillis();
        int shown = 0;
        for (int i = all.size() - 1 - mindScroll; i >= 0 && shown < MIND_ROWS; i--, shown++) {
            OverlayPayloads.Thought t = all.get(i);
            int ry = y + shown * 12;
            long ageSec = Math.max(0, (now - t.atMillis()) / 1000);
            String age = ageSec < 60 ? ageSec + "s" : (ageSec / 60) + "m";
            g.drawString(font, "§8" + age, px + 8, ry + 2, TEXT_DIM);
            g.drawString(font, thoughtPrefix(t.type()) + " §r"
                            + trim(t.text(), pw - 70), px + 34, ry + 2, TEXT);
        }
        if (all.size() > MIND_ROWS) {
            String mode = mindPaused ? " §e❚❚ frozen" : " (newest first)";
            g.drawString(font, "§8" + (mindScroll + 1) + "-"
                            + Math.min(all.size(), mindScroll + MIND_ROWS) + " of " + all.size()
                            + mode,
                    px + 10, y + MIND_ROWS * 12 + 4, TEXT_DIM);
        }
    }

    private static String thoughtPrefix(String type) {
        return switch (type) {
            case "plan" -> "§d◆";           // L3 planning
            case "subtask" -> "§b▷";
            case "directive" -> "§3→";      // L1 dispatch results
            case "criteria" -> "§a✓";
            case "criteria_fail" -> "§c✗";
            case "l2" -> "§6⟲";             // L2 repair/retry
            case "replan" -> "§e↺";
            case "done" -> "§a◼";
            case "fail" -> "§c◼";
            default -> "§7·";
        };
    }

    // ── input ────────────────────────────────────────────────────────────

    @Override
    public boolean mouseClicked(double mouseX, double mouseY, int button) {
        if (overlayClicked(mouseX, mouseY)) return true;
        if (super.mouseClicked(mouseX, mouseY, button)) return true;
        OverlayTab extClick = activeExtension();
        if (extClick != null && extClick.mouseClicked(mouseX, mouseY, button)) return true;
        int px = panelX(), pw = panelW();
        // Fleet rows are clickable (fleet view only — not the inbox).
        if (selected == -1) {
            int y = panelY() + 46;
            List<OverlayPayloads.BotEntry> sorted = sortedFleet();
            for (int i = fleetScroll; i < Math.min(sorted.size(), fleetScroll + FLEET_ROWS); i++) {
                int ry = y + (i - fleetScroll) * 30;
                if (mouseX >= px + 4 && mouseX <= px + pw - 4 && mouseY >= ry && mouseY < ry + 28) {
                    int idx = snapshotIndexOf(sorted.get(i));
                    if (idx >= 0) selectUnit(idx);
                    return true;
                }
            }
            return false;
        }
        // Drone roster rows select the drone.
        if (selected == VIEW_DRONES) {
            int y = panelY() + 46;
            List<OverlayPayloads.BotEntry> ds = droneList();
            for (int i = droneListScroll; i < Math.min(ds.size(), droneListScroll + DRONE_LIST_ROWS); i++) {
                int ry = y + (i - droneListScroll) * 17;
                if (mouseX >= px + 4 && mouseX <= px + pw - 4 && mouseY >= ry && mouseY < ry + 16) {
                    int idx = snapshotIndexOf(ds.get(i));
                    if (idx >= 0) selectUnit(idx);
                    return true;
                }
            }
            return false;
        }
        // Vault rows select an item.
        if (unitTab == UnitTab.VAULT && vault != null) {
            int y = panelY() + 62 + 18;
            List<OverlayPayloads.HoldingEntry> rows = vault.entries();
            int max = Math.min(rows.size(), vaultScroll + VAULT_ROWS);
            for (int i = vaultScroll; i < max; i++) {
                int ry = y + (i - vaultScroll) * 12;
                if (mouseX >= px + 6 && mouseX <= px + pw - 6 && mouseY >= ry && mouseY < ry + 12) {
                    selectedItem = rows.get(i).item();
                    return true;
                }
            }
            // Worn chips: click = take it off, into the bot's inventory.
            OverlayPayloads.BotEntry unit = selectedBot();
            int wy = wornRowY();
            if (unit != null && mouseY >= wy && mouseY < wy + 12) {
                int wx = px + 120;
                for (OverlayPayloads.WornEntry w : vault.worn()) {
                    String label = "§d[" + shortName(w.item()) + "§8·" + w.slotType() + "§d]";
                    int lw = font.width(stripCodes(label));
                    if (wx + lw > px + pw - 8) break;
                    if (mouseX >= wx && mouseX < wx + lw) {
                        PacketDistributor.sendToServer(new OverlayPayloads.CuriosOp(
                                unit.id(), false, "", w.slotType(), w.index()));
                        return true;
                    }
                    wx += lw + 6;
                }
            }
        }

        // Expansion clicks: any transcript / thought / inbox line opens the
        // full text (player feedback: truncated messages are unreadable).
        OverlayPayloads.BotEntry sel = selectedBot();
        if (sel != null && unitTab == UnitTab.TALK) {
            List<OverlayPayloads.TalkLine> lines = OverlayClientState.talkFor(sel.name());
            int y = panelY() + 64;
            int from = Math.max(0, lines.size() - TALK_ROWS);
            for (int i = from; i < lines.size(); i++) {
                int ry = y + (i - from) * 12;
                if (mouseX >= px + 6 && mouseX <= px + pw - 6 && mouseY >= ry && mouseY < ry + 12) {
                    OverlayPayloads.TalkLine t = lines.get(i);
                    expandedText = (t.who().equals(sel.name()) ? "§b" : "§e")
                            + t.who() + "§r: §7" + t.text();
                    return true;
                }
            }
        }
        if (sel != null && unitTab == UnitTab.MIND) {
            List<OverlayPayloads.Thought> all = mindPaused
                    ? mindFrozen : OverlayClientState.thoughtsFor(sel.name());
            int y = panelY() + 64;
            for (int shown = 0; shown < MIND_ROWS; shown++) {
                int idx = all.size() - 1 - mindScroll - shown;
                if (idx < 0) break;
                int ry = y + shown * 12;
                if (mouseX >= px + 6 && mouseX <= px + pw - 6 && mouseY >= ry && mouseY < ry + 12) {
                    OverlayPayloads.Thought t = all.get(idx);
                    expandedText = thoughtPrefix(t.type()) + " §7" + t.text();
                    return true;
                }
            }
        }
        return false;
    }

    @Override
    public boolean mouseScrolled(double mouseX, double mouseY, double dx, double dy) {
        OverlayTab extScroll = activeExtension();
        if (extScroll != null && extScroll.mouseScrolled(mouseX, mouseY, dx, dy)) return true;
        if (ddItems != null) {
            int maxScroll = Math.max(0, ddItems.size() - DD_ROWS);
            ddScroll = Math.max(0, Math.min(maxScroll, ddScroll - (int) Math.signum(dy)));
            return true;
        }
        if (inboxModalOpen) {
            inboxTextScroll = Math.max(0, inboxTextScroll - (int) Math.signum(dy));
            if (dy < 0) inboxTextScroll += 2; // clamped in render
            return true;
        }
        if (selected == -1) {
            fleetScroll = Math.max(0, fleetScroll - (int) Math.signum(dy));
            if (dy < 0) fleetScroll += 2; // clamped in render
            return true;
        }
        if (selected == VIEW_DRONES) {
            droneListScroll = Math.max(0, droneListScroll - (int) Math.signum(dy));
            if (dy < 0) droneListScroll += 2; // clamped in render
            return true;
        }
        if (unitTab == UnitTab.VAULT && vault != null && selected >= 0) {
            int maxScroll = Math.max(0, vault.entries().size() - VAULT_ROWS);
            vaultScroll = Math.max(0, Math.min(maxScroll, vaultScroll - (int) Math.signum(dy)));
            return true;
        }
        if (unitTab == UnitTab.MIND && selected >= 0) {
            OverlayPayloads.BotEntry e = selectedBot();
            int total = mindPaused ? mindFrozen.size()
                    : e == null ? 0 : OverlayClientState.thoughtsFor(e.name()).size();
            int maxScroll = Math.max(0, total - MIND_ROWS);
            mindScroll = Math.max(0, Math.min(maxScroll, mindScroll - (int) Math.signum(dy)));
            return true;
        }
        return super.mouseScrolled(mouseX, mouseY, dx, dy);
    }

    @Override
    public boolean charTyped(char chr, int modifiers) {
        OverlayTab extChar = activeExtension();
        if (extChar != null && extChar.charTyped(chr, modifiers)) return true;
        if (ddItems != null) {
            ddFilter += chr;
            applyDdFilter();
            return true;
        }
        return super.charTyped(chr, modifiers);
    }

    @Override
    public boolean keyPressed(int keyCode, int scanCode, int modifiers) {
        // Modal + expansion guards come FIRST: while either is open, ESC
        // steps back one layer (never out of the overlay), typed keys go
        // to whatever field is focused, and the overlay hotkey is inert
        // (live report: pressing 'h' mid-reply closed everything).
        OverlayTab extKeys = activeExtension();
        if (extKeys != null && extKeys.keyPressed(keyCode, scanCode, modifiers)) return true;
        if (inboxModalOpen) {
            if (keyCode == 256) {
                inboxModalOpen = false;
                inboxSelectedId = "";
                buildWidgets();
                return true;
            }
            if (getFocused() instanceof net.minecraft.client.gui.components.EditBox) {
                return super.keyPressed(keyCode, scanCode, modifiers);
            }
            return true;
        }
        if (expandedText != null) {
            if (keyCode == 256) expandedText = null;
            return true;
        }
        if (ddItems != null) {
            if (keyCode == 259 && !ddFilter.isEmpty()) { // backspace
                ddFilter = ddFilter.substring(0, ddFilter.length() - 1);
                applyDdFilter();
                return true;
            }
            if (keyCode == 256) { // esc closes the dropdown, not the overlay
                ddItems = null;
                ddAll = null;
                ddPick = null;
                return true;
            }
            // EVERY other key belongs to the type-to-search filter while the
            // picker is open — the filter is virtual (no focused EditBox), so
            // without this the overlay hotkey fell through and closed the
            // whole interface mid-search (live report: typing 'h').
            return true;
        }
        // Text fields swallow everything first — typing "1" into the vault
        // search must not switch tabs, and H must still be typeable.
        boolean typing = getFocused() instanceof net.minecraft.client.gui.components.EditBox;
        if (typing) {
            // Enter sends in the Talk tab.
            if (keyCode == 257 && unitTab == UnitTab.TALK && getFocused() == talkInput) {
                OverlayPayloads.BotEntry e = selectedBot();
                if (e != null) {
                    sendTalk(e);
                    return true;
                }
            }
            return super.keyPressed(keyCode, scanCode, modifiers);
        }
        // Second tap of the hotkey closes.
        if (OverlayKeybind.OPEN_OVERLAY.matches(keyCode, scanCode)) {
            onClose();
            return true;
        }
        // 1-9 selects a bot, 0 returns to fleet.
        if (keyCode >= '1' && keyCode <= '9') {
            int idx = keyCode - '1';
            if (idx < snapshot.bots().size()) {
                selectUnit(idx);
                return true;
            }
        }
        if (keyCode == '0') {
            selectUnit(-1);
            return true;
        }
        return super.keyPressed(keyCode, scanCode, modifiers);
    }

    @Override
    public boolean keyReleased(int keyCode, int scanCode, int modifiers) {
        // Hold-to-peek: if the opening key is released after a long press,
        // this was a peek — close. A quick tap latches. Never while typing,
        // never while a modal/expansion/dropdown is open.
        if (ddItems != null || inboxModalOpen || expandedText != null) return true;
        OverlayTab extRel = activeExtension();
        if (extRel != null && extRel.keyPressed(-1, -1, 0)) return true;
        if (!(getFocused() instanceof net.minecraft.client.gui.components.EditBox)
                && OverlayKeybind.OPEN_OVERLAY.matches(keyCode, scanCode)
                && System.currentTimeMillis() - openedAt > 400) {
            onClose();
            return true;
        }
        return super.keyReleased(keyCode, scanCode, modifiers);
    }

    // ── helpers ──────────────────────────────────────────────────────────

    private String directiveLine(OverlayPayloads.BotEntry e) {
        if (e.directiveId() < 0) return "§8standing by";
        String base = e.directiveType() + (e.target().isEmpty() ? "" : " " + e.target());
        return statusGlyph(e.directiveStatus()) + " §r" + trim(base, 200);
    }

    private static String statusGlyph(String status) {
        return switch (status) {
            case "ACTIVE" -> "§b▶";
            case "COMPLETED" -> "§a✔";
            case "FAILED" -> "§c✖";
            case "CANCELLED" -> "§7∅";
            default -> "§8·";
        };
    }

    private static int statusColor(String status) {
        return switch (status) {
            case "ACTIVE" -> 0xFF54E8E0;
            case "COMPLETED" -> 0xFF81C784;
            case "FAILED" -> 0xFFE57373;
            case "CANCELLED" -> 0xFF9E9E9E;
            default -> TEXT_DIM;
        };
    }

    private static String shortDim(String dim) {
        return switch (dim) {
            case "minecraft:overworld" -> "§2overworld";
            case "minecraft:the_nether" -> "§4nether";
            case "minecraft:the_end" -> "§5end";
            default -> "§7" + (dim.contains(":") ? dim.substring(dim.indexOf(':') + 1) : dim);
        };
    }

    private String trim(String s, int maxWidth) {
        if (font.width(s) <= maxWidth) return s;
        while (!s.isEmpty() && font.width(s + "…") > maxWidth) s = s.substring(0, s.length() - 1);
        return s + "…";
    }
}
