package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.brain.DirectiveType;
import com.sigmastrain.aiplayermod.compat.ModCompat;

/**
 * Single source of truth mapping a {@link DirectiveType} to a {@link Behavior}.
 * Extracted from {@code BotBrain.createBehavior} so both the brain and the
 * skill interpreter ({@code SkillBehavior}) instantiate directives the same way.
 *
 * A leaf directive that names {@code SKILL} is rejected at skill-validation
 * time; nesting a skill uses a skill-ref node, and {@code SKILL} here starts
 * the meta-behavior interpreter.
 *
 * GATHER and PATROL intentionally fall through to an idle behavior (they have
 * no dedicated implementation yet — a known gap, flagged separately).
 */
public final class BehaviorFactory {

    private BehaviorFactory() {}

    public static Behavior create(DirectiveType type) {
        return switch (type) {
            case MINE -> new MineBehavior();
            case GOTO -> new GotoBehavior();
            case FOLLOW -> new FollowBehavior();
            case CRAFT -> new CraftBehavior();
            case SMELT -> new SmeltBehavior();
            case ENCHANT -> new EnchantBehavior();
            case BREW -> new BrewBehavior();
            case COMBAT -> new CombatBehavior();
            case CHANNEL -> new ChannelBehavior();
            case SEND_ITEM -> new SendItemBehavior();
            case BUILD -> new BuildBehavior();
            case FARM -> new FarmBehavior();
            case CONTAINER_PLACE -> new ContainerPlaceBehavior();
            case CONTAINER_SEARCH -> new ContainerSearchBehavior();
            case CONTAINER_STORE -> new ContainerStoreBehavior();
            case CONTAINER_WITHDRAW -> new ContainerWithdrawBehavior();
            case TELEPORT -> new TeleportBehavior();
            case WIDE_SEARCH -> new WideSearchBehavior();
            case AREA_LOOT -> new AreaLootBehavior();
            case LOCATE -> new LocateBehavior();
            case STORE_ALL -> new StoreAllBehavior();
            case ME_STORE -> ModCompat.isAE2Loaded() ? new MEStoreBehavior() : new FailFastBehavior("AE2 not loaded");
            case ME_WITHDRAW -> ModCompat.isAE2Loaded() ? new MEWithdrawBehavior() : new FailFastBehavior("AE2 not loaded");
            case CRAFT_REQUEST -> ModCompat.isAE2Loaded() ? new CraftRequestBehavior() : new FailFastBehavior("AE2 not loaded");
            case MEDITATE -> new MeditateBehavior();
            case CULTIVATE -> new CultivateBehavior();
            case MOUNT_VEHICLE -> ModCompat.isSuperbWarfareLoaded() ? new MountVehicleBehavior() : new FailFastBehavior("Superb Warfare not loaded");
            case DISMOUNT_VEHICLE -> new DismountVehicleBehavior();
            case DRIVE_VEHICLE -> ModCompat.isSuperbWarfareLoaded() ? new DriveVehicleBehavior() : new FailFastBehavior("Superb Warfare not loaded");
            case SKILL -> new SkillBehavior();
            case IDLE -> new IdleBehavior();
            default -> new IdleBehavior(); // GATHER, PATROL — no impl yet
        };
    }
}
