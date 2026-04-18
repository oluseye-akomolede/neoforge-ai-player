package com.sigmastrain.aiplayermod;

import com.mojang.brigadier.CommandDispatcher;
import com.mojang.brigadier.arguments.StringArgumentType;
import com.sigmastrain.aiplayermod.bot.BotManager;
import com.sigmastrain.aiplayermod.bot.BotPlayer;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.commands.Commands;
import net.minecraft.network.chat.Component;

public class ModCommands {

    public static void register(CommandDispatcher<CommandSourceStack> dispatcher) {
        dispatcher.register(Commands.literal("aibot")
                .requires(source -> source.hasPermission(2))
                .then(Commands.literal("spawn")
                        .then(Commands.argument("name", StringArgumentType.word())
                                .executes(ctx -> {
                                    String name = StringArgumentType.getString(ctx, "name");
                                    BotManager.spawn(name);
                                    ctx.getSource().sendSuccess(() ->
                                            Component.literal("Spawned AI bot: " + name), true);
                                    return 1;
                                })))
                .then(Commands.literal("despawn")
                        .then(Commands.argument("name", StringArgumentType.word())
                                .executes(ctx -> {
                                    String name = StringArgumentType.getString(ctx, "name");
                                    BotManager.despawn(name);
                                    ctx.getSource().sendSuccess(() ->
                                            Component.literal("Despawned AI bot: " + name), true);
                                    return 1;
                                })))
                .then(Commands.literal("list")
                        .executes(ctx -> {
                            var bots = BotManager.getAllBots();
                            if (bots.isEmpty()) {
                                ctx.getSource().sendSuccess(() ->
                                        Component.literal("No AI bots active"), false);
                            } else {
                                bots.forEach((name, bot) -> {
                                    var status = bot.getStatus();
                                    ctx.getSource().sendSuccess(() ->
                                            Component.literal(String.format("[%s] HP:%.0f Pos:%s Action:%s",
                                                    name, status.get("health"), status.get("position"),
                                                    bot.getActionQueue().currentAction())), false);
                                });
                            }
                            return 1;
                        }))
        );
    }
}
