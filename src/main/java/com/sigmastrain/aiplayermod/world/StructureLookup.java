package com.sigmastrain.aiplayermod.world;

import com.mojang.datafixers.util.Pair;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Holder;
import net.minecraft.core.HolderSet;
import net.minecraft.core.Registry;
import net.minecraft.core.registries.Registries;
import net.minecraft.resources.ResourceKey;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.tags.TagKey;
import net.minecraft.world.level.biome.Biome;
import net.minecraft.world.level.levelgen.structure.Structure;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * Structure resolution and nearest-structure search.
 *
 * <p>The End expedition failed because WIDE_SEARCH is a BLOCK scanner: it
 * fuzzy-matches against {@code BuiltInRegistries.BLOCK}, so "end_city" could
 * never match anything. Three bots scanned 5.2 million blocks between them and
 * found nothing, because a structure is not a block.
 *
 * <p>This is the right primitive. It asks the chunk generator where structures
 * were <em>placed</em> — the same query {@code /locate} runs — which answers in
 * one call out to thousands of blocks instead of brute-forcing a volume.
 *
 * <p>Resolution mirrors the item registry's contract: try increasingly loose
 * matches, prefer exactness, and when a loose match hits several structures,
 * search for the nearest of ALL of them rather than guessing one. "village"
 * legitimately means five structures; the useful answer is whichever is closest.
 */
public final class StructureLookup {

    private StructureLookup() {}

    /** Cap on how many structures a fuzzy match may expand to. */
    private static final int MAX_FUZZY_CANDIDATES = 64;

    /** What a name resolved to, and how. */
    public record Resolution(
            HolderSet<Structure> holders,
            List<String> matchedIds,
            String method,
            String error
    ) {
        public boolean ok() { return error == null; }

        public static Resolution fail(String why) {
            return new Resolution(null, List.of(), "none", why);
        }
    }

    /** Where the nearest match is. */
    public record Found(
            BlockPos pos,
            String structureId,
            double distance,
            long elapsedMs
    ) {}

    // ── name → structures ────────────────────────────────────────────────

    public static Resolution resolve(ServerLevel level, String raw) {
        if (raw == null || raw.isBlank()) {
            return Resolution.fail("no structure name given");
        }
        Registry<Structure> registry = level.registryAccess().registryOrThrow(Registries.STRUCTURE);

        boolean tagOnly = raw.trim().startsWith("#");
        String s = raw.trim().toLowerCase(Locale.ROOT)
                .replaceFirst("^#", "")
                .replace(' ', '_')
                .replaceAll("[^a-z0-9_:/\\-.]", "");
        if (s.isEmpty()) {
            return Resolution.fail("structure name '" + raw + "' had no usable characters");
        }

        // Explicit tag request: #minecraft:village
        if (tagOnly) {
            Resolution byTag = asTag(registry, s);
            return byTag != null ? byTag : Resolution.fail("no structure tag '#" + s + "'");
        }

        // 1. exact id — minecraft:end_city
        ResourceLocation exact = ResourceLocation.tryParse(s.contains(":") ? s : "minecraft:" + s);
        if (exact != null) {
            Optional<Holder.Reference<Structure>> holder = registry.getHolder(exact);
            if (holder.isPresent()) {
                return new Resolution(HolderSet.direct(holder.get()),
                        List.of(exact.toString()), "exact", null);
            }
        }

        // 2. exact tag by the same name — "village" is a tag as well as a prefix
        Resolution byTag = asTag(registry, s);

        // 3. bare path across namespaces — "end_city" in any mod's namespace
        String path = s.contains(":") ? s.substring(s.indexOf(':') + 1) : s;
        List<Holder.Reference<Structure>> pathMatches = registry.holders()
                .filter(h -> h.key().location().getPath().equals(path))
                .collect(Collectors.toList());
        if (!pathMatches.isEmpty()) {
            return new Resolution(HolderSet.direct(new ArrayList<>(pathMatches)),
                    ids(pathMatches),
                    pathMatches.size() == 1 ? "path_unique" : "path_multi", null);
        }

        // A tag match is better than a substring guess, so try it before fuzzing.
        if (byTag != null) return byTag;

        // 4. substring — the only hope for a modded id nobody spelled exactly
        List<Holder.Reference<Structure>> subs = registry.holders()
                .filter(h -> h.key().location().getPath().contains(path))
                .limit(MAX_FUZZY_CANDIDATES)
                .collect(Collectors.toList());
        if (!subs.isEmpty()) {
            return new Resolution(HolderSet.direct(new ArrayList<>(subs)),
                    ids(subs),
                    subs.size() == 1 ? "substring" : "substring_multi", null);
        }

        // 5. reverse substring — the NAME is longer than the id. Minecraft's
        // registry ids are terser than the words anyone actually uses:
        // "woodland_mansion" is minecraft:mansion, "ocean_monument" is
        // minecraft:monument, "nether_fortress" is minecraft:fortress. Without
        // this, the three most-named structures in the game all miss.
        List<Holder.Reference<Structure>> rev = registry.holders()
                .filter(h -> {
                    String p = h.key().location().getPath();
                    return p.length() >= 4 && path.contains(p);
                })
                .collect(Collectors.toList());
        if (!rev.isEmpty()) {
            // Keep only the longest ids — the most specific reading of the name.
            int longest = rev.stream().mapToInt(h -> h.key().location().getPath().length()).max().orElse(0);
            List<Holder.Reference<Structure>> best = rev.stream()
                    .filter(h -> h.key().location().getPath().length() == longest)
                    .limit(MAX_FUZZY_CANDIDATES)
                    .collect(Collectors.toList());
            return new Resolution(HolderSet.direct(new ArrayList<>(best)),
                    ids(best),
                    best.size() == 1 ? "name_contains_id" : "name_contains_id_multi", null);
        }

        return Resolution.fail("no structure or tag matches '" + raw + "'");
    }

    /**
     * Resolve, then keep only what can actually generate in this dimension.
     *
     * <p>The single entry point callers should use — it owns the dimension
     * fallback, which neither {@link #resolve} nor {@link #filterToDimension}
     * can do alone: "ruined_portal" resolves exactly to
     * {@code minecraft:ruined_portal}, which is overworld-only, so asking for
     * one in the Nether would dead-end even though
     * {@code minecraft:ruined_portal_nether} is sitting right there. When the
     * precise match can't spawn here, widen to the family before giving up.
     */
    public static Resolution resolveInDimension(ServerLevel level, String raw) {
        Resolution res = resolve(level, raw);
        if (!res.ok()) return res;

        HolderSet<Structure> here = filterToDimension(level, res.holders());
        if (here.size() > 0) {
            return new Resolution(here, res.matchedIds(), res.method(), null);
        }

        Registry<Structure> registry = level.registryAccess().registryOrThrow(Registries.STRUCTURE);
        String s = raw.trim().toLowerCase(Locale.ROOT).replaceFirst("^#", "").replace(' ', '_');
        String path = s.contains(":") ? s.substring(s.indexOf(':') + 1) : s;
        List<Holder.Reference<Structure>> family = registry.holders()
                .filter(h -> {
                    String p = h.key().location().getPath();
                    return p.contains(path) || (p.length() >= 4 && path.contains(p));
                })
                .limit(MAX_FUZZY_CANDIDATES)
                .collect(Collectors.toList());
        if (!family.isEmpty()) {
            HolderSet<Structure> familyHere =
                    filterToDimension(level, HolderSet.direct(new ArrayList<>(family)));
            if (familyHere.size() > 0) {
                List<String> ids = familyHere.stream()
                        .map(h -> h.unwrapKey().map(k -> k.location().toString()).orElse("?"))
                        .collect(Collectors.toList());
                return new Resolution(familyHere, ids,
                        res.method() + "+dimension_variant", null);
            }
        }

        return Resolution.fail("'" + raw + "' does not generate in "
                + level.dimension().location() + " (matched "
                + res.matchedIds().size() + " structure(s), none spawn here)");
    }

    private static Resolution asTag(Registry<Structure> registry, String s) {
        ResourceLocation tagId = ResourceLocation.tryParse(s.contains(":") ? s : "minecraft:" + s);
        if (tagId == null) return null;
        Optional<HolderSet.Named<Structure>> tag = registry.getTag(TagKey.create(Registries.STRUCTURE, tagId));
        if (tag.isEmpty() || tag.get().size() == 0) return null;
        List<String> members = tag.get().stream()
                .map(h -> h.unwrapKey().map(k -> k.location().toString()).orElse("?"))
                .collect(Collectors.toList());
        return new Resolution(tag.get(), members, "tag:" + tagId, null);
    }

    private static List<String> ids(List<Holder.Reference<Structure>> holders) {
        return holders.stream().map(h -> h.key().location().toString()).collect(Collectors.toList());
    }

    // ── dimension pre-filter ─────────────────────────────────────────────

    /**
     * Drop structures that cannot generate in this dimension.
     *
     * <p>Without this, asking for an end_city while standing in the Overworld
     * runs the full multi-thousand-chunk search and returns null — expensive
     * AND uninformative. Every structure declares the biomes it spawns in, and
     * a dimension's biome source is memoized, so the check is nearly free and
     * turns a dead end into a diagnosis.
     */
    public static HolderSet<Structure> filterToDimension(ServerLevel level, HolderSet<Structure> set) {
        Set<ResourceKey<Biome>> possible = level.getChunkSource().getGenerator().getBiomeSource()
                .possibleBiomes().stream()
                .map(h -> h.unwrapKey().orElse(null))
                .filter(Objects::nonNull)
                .collect(Collectors.toSet());
        if (possible.isEmpty()) return set;  // unknown biome source — don't second-guess it

        List<Holder<Structure>> keep = set.stream()
                .filter(h -> h.value().biomes().stream()
                        .anyMatch(b -> b.unwrapKey().map(possible::contains).orElse(false)))
                .collect(Collectors.toList());
        return HolderSet.direct(keep);
    }

    // ── the search ───────────────────────────────────────────────────────

    /**
     * Nearest placement of any structure in {@code set}, or null.
     *
     * <p>{@code chunkRadius} is in CHUNKS, matching {@code /locate} (which uses
     * 100). Runs on the server thread — the chunk generator is not thread-safe —
     * so callers should treat it as a one-shot, not a per-tick operation.
     */
    public static Found findNearest(ServerLevel level, HolderSet<Structure> set,
                                    BlockPos origin, int chunkRadius) {
        long t0 = System.nanoTime();
        Pair<BlockPos, Holder<Structure>> pair = level.getChunkSource().getGenerator()
                .findNearestMapStructure(level, set, origin, chunkRadius, false);
        long elapsedMs = (System.nanoTime() - t0) / 1_000_000L;
        if (pair == null) return null;

        BlockPos pos = pair.getFirst();
        String id = pair.getSecond().unwrapKey()
                .map(k -> k.location().toString())
                .orElse("unknown");
        // Horizontal distance: the returned Y is the structure's generation
        // reference, not a surface, so including it would distort the number.
        double dx = pos.getX() - origin.getX();
        double dz = pos.getZ() - origin.getZ();
        return new Found(pos, id, Math.sqrt(dx * dx + dz * dz), elapsedMs);
    }

    public static boolean structuresEnabled(ServerLevel level) {
        return level.getServer().getWorldData().worldGenOptions().generateStructures();
    }

    // ── registry introspection (used by /server/structures) ──────────────

    public static Map<String, Object> listAll(ServerLevel level, String namespaceFilter, String queryFilter) {
        Registry<Structure> registry = level.registryAccess().registryOrThrow(Registries.STRUCTURE);
        String ns = namespaceFilter == null ? null : namespaceFilter.toLowerCase(Locale.ROOT);
        String q = queryFilter == null ? null : queryFilter.toLowerCase(Locale.ROOT);

        List<String> ids = new ArrayList<>();
        List<String> namespaces = new ArrayList<>();
        for (ResourceLocation id : registry.keySet()) {
            if (!namespaces.contains(id.getNamespace())) namespaces.add(id.getNamespace());
            if (ns != null && !id.getNamespace().equals(ns)) continue;
            String full = id.toString();
            if (q != null && !full.toLowerCase(Locale.ROOT).contains(q)) continue;
            ids.add(full);
        }
        ids.sort(String::compareTo);
        namespaces.sort(String::compareTo);

        List<String> tags = registry.getTags()
                .map(t -> "#" + t.getFirst().location())
                .sorted()
                .collect(Collectors.toList());

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("structures", ids);
        out.put("tags", tags);
        out.put("namespaces", namespaces);
        out.put("count", ids.size());
        return out;
    }
}
