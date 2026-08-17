package com.sigmastrain.aiplayermod.bot;

import com.sigmastrain.aiplayermod.ModMenuTypes;
import net.minecraft.network.RegistryFriendlyByteBuf;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.Container;
import net.minecraft.world.SimpleContainer;
import net.minecraft.world.entity.player.Inventory;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.inventory.AbstractContainerMenu;
import net.minecraft.world.inventory.Slot;
import net.minecraft.world.item.ItemStack;

import java.util.ArrayList;
import java.util.List;

/**
 * A bot's Curios inventory as a grid — the editor the equipment window opens
 * via its ◈ button. Curios is not a plain container, so the server backs the
 * slots with a {@link CuriosContainer} (write-through to the Curios API) while
 * the client backs them with a placeholder {@link SimpleContainer}; the slot
 * count + type labels ride the open buffer so both sides build the same grid.
 */
public class BotCuriosMenu extends AbstractContainerMenu {

    private static final int COLS = 8;
    private static final int GRID_X = 8;
    private static final int GRID_Y = 20;

    private final Container curiosContainer;
    private final List<String> curioLabels;
    private final int curioCount;
    private final int botEntityId;
    private final String botName;

    public int getCurioCount() { return curioCount; }
    public List<String> getCurioLabels() { return curioLabels; }
    public int getBotEntityId() { return botEntityId; }
    public String getBotName() { return botName; }

    /** Server constructor — backs the grid with the bot's real curios. */
    public BotCuriosMenu(int containerId, Inventory playerInventory, ServerPlayer bot, int botEntityId) {
        super(ModMenuTypes.BOT_CURIOS.get(), containerId);
        this.botEntityId = botEntityId;
        this.botName = bot.getGameProfile().getName();
        CuriosContainer cc = new CuriosContainer(bot);
        this.curiosContainer = cc;
        this.curioCount = cc.getContainerSize();
        this.curioLabels = new ArrayList<>(cc.labels());
        addCurioSlots();
        addPlayerSlots(playerInventory);
    }

    /** Client constructor — a placeholder container sized from the buffer. */
    private BotCuriosMenu(int containerId, Inventory playerInventory, Container curiosContainer,
                          List<String> labels, int botEntityId, String botName) {
        super(ModMenuTypes.BOT_CURIOS.get(), containerId);
        this.botEntityId = botEntityId;
        this.botName = botName;
        this.curiosContainer = curiosContainer;
        this.curioCount = curiosContainer.getContainerSize();
        this.curioLabels = labels;
        addCurioSlots();
        addPlayerSlots(playerInventory);
    }

    public static BotCuriosMenu fromNetwork(int containerId, Inventory playerInventory,
                                            RegistryFriendlyByteBuf buf) {
        int entityId = buf.readVarInt();
        String botName = buf.readUtf();
        int count = buf.readVarInt();
        List<String> labels = new ArrayList<>(count);
        for (int i = 0; i < count; i++) labels.add(buf.readUtf());
        return new BotCuriosMenu(containerId, playerInventory,
                new SimpleContainer(count), labels, entityId, botName);
    }

    private void addCurioSlots() {
        for (int i = 0; i < curioCount; i++) {
            int col = i % COLS;
            int row = i / COLS;
            addSlot(new Slot(curiosContainer, i, GRID_X + col * 18, GRID_Y + row * 18));
        }
    }

    private void addPlayerSlots(Inventory playerInventory) {
        int rows = (curioCount + COLS - 1) / COLS;
        int top = GRID_Y + rows * 18 + 14;
        for (int r = 0; r < 3; r++) {
            for (int c = 0; c < 9; c++) {
                addSlot(new Slot(playerInventory, 9 + r * 9 + c, 8 + c * 18, top + r * 18));
            }
        }
        for (int c = 0; c < 9; c++) {
            addSlot(new Slot(playerInventory, c, 8 + c * 18, top + 3 * 18 + 4));
        }
    }

    @Override
    public ItemStack quickMoveStack(Player player, int index) {
        Slot slot = this.slots.get(index);
        if (!slot.hasItem()) return ItemStack.EMPTY;

        ItemStack stack = slot.getItem();
        ItemStack result = stack.copy();
        int playerStart = curioCount;
        int playerEnd = curioCount + 36; // 27 main + 9 hotbar

        if (index < curioCount) {
            // From curios → player inventory.
            if (!this.moveItemStackTo(stack, playerStart, playerEnd, true)) {
                return ItemStack.EMPTY;
            }
        } else {
            // From player → curios (mayPlace gates which slot accepts it).
            if (!this.moveItemStackTo(stack, 0, curioCount, false)) {
                return ItemStack.EMPTY;
            }
        }

        if (stack.isEmpty()) {
            slot.setByPlayer(ItemStack.EMPTY);
        } else {
            slot.setChanged();
        }
        return result;
    }

    @Override
    public boolean stillValid(Player player) {
        return true;
    }
}
