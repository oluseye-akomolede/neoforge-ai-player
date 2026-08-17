package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import com.sigmastrain.aiplayermod.compat.superbwarfare.SwVehicleCompat;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.Entity;

/** Leave whatever the bot is riding (vehicle, boat, mount). */
public class DismountVehicleBehavior implements Behavior {

    private final ProgressReport progress = new ProgressReport();

    @Override
    public void start(BotPlayer bot, Directive directive) {
        progress.reset();
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        ServerPlayer player = bot.getPlayer();
        Entity v = player.getVehicle();
        if (v == null) {
            progress.logEvent("Not aboard anything");
            bot.systemChat("Not aboard anything", "yellow");
            return BehaviorResult.SUCCESS;
        }
        String name = SwVehicleCompat.isVehicle(v) ? SwVehicleCompat.displayName(v) : v.getName().getString();
        if (SwVehicleCompat.isVehicle(v)) SwVehicleCompat.clearInputs(v);
        player.stopRiding();
        progress.logEvent("Dismounted " + name);
        bot.systemChat("Dismounted " + name, "aqua");
        return BehaviorResult.SUCCESS;
    }

    @Override
    public String describeState() { return "Dismounting"; }

    @Override
    public ProgressReport getProgress() { return progress; }

    @Override
    public void stop() {}
}
