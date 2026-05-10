package com.sigmastrain.aiplayermod;

import com.sigmastrain.aiplayermod.bot.BotEquipmentMenu;
import net.minecraft.core.registries.Registries;
import net.minecraft.world.inventory.MenuType;
import net.neoforged.neoforge.common.extensions.IMenuTypeExtension;
import net.neoforged.neoforge.registries.DeferredRegister;

import java.util.function.Supplier;

public class ModMenuTypes {
    public static final DeferredRegister<MenuType<?>> MENUS =
            DeferredRegister.create(Registries.MENU, AIPlayerMod.MOD_ID);

    public static final Supplier<MenuType<BotEquipmentMenu>> BOT_EQUIPMENT =
            MENUS.register("bot_equipment", () -> IMenuTypeExtension.create(BotEquipmentMenu::fromNetwork));
}
