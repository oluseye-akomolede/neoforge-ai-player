package com.sigmastrain.aiplayermod.brain.behavior;

import com.sigmastrain.aiplayermod.bot.BotPlayer;
import com.sigmastrain.aiplayermod.brain.BehaviorResult;
import com.sigmastrain.aiplayermod.brain.Directive;
import com.sigmastrain.aiplayermod.brain.DirectiveType;
import com.sigmastrain.aiplayermod.brain.ProgressReport;
import com.sigmastrain.aiplayermod.brain.skill.SkillCondition;
import com.sigmastrain.aiplayermod.brain.skill.SkillNode;
import com.sigmastrain.aiplayermod.brain.skill.SkillParams;
import com.sigmastrain.aiplayermod.brain.skill.SkillRegistry;
import com.sigmastrain.aiplayermod.brain.skill.SkillSpec;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * The meta-behavior that runs a declarative skill (Decision 2 of the v10
 * design). A skill is a tree of {@link SkillNode}s over ordinary directives;
 * this class is a small tick-budgeted interpreter that walks the tree and
 * drives one child {@link Behavior} at a time — the same {@code BehaviorFactory}
 * the brain uses for a single directive.
 *
 * Execution model: a stack of composite frames (sequence / fallback / loop);
 * {@code if} and skill-ref nodes are transparent. A directive leaf starts a
 * child behavior; each tick drives that child until it settles, then the result
 * is propagated up the frame stack. Termination is guaranteed because every
 * loop carries {@code max_iterations}, self-references are rejected at
 * validation, and two runtime backstops (a synchronous skill-ref depth cap and
 * a total leaf-execution budget) bound pathological specs.
 */
public class SkillBehavior implements Behavior {

    private static final int MAX_SKILL_DEPTH = 32;      // nested synchronous skill-ref recursion
    private static final int MAX_LEAF_EXECUTIONS = 500; // total directive leaves per skill run

    private final ProgressReport progress = new ProgressReport();

    private final java.util.function.Function<DirectiveType, Behavior> behaviorFactory;

    private BotPlayer bot;
    private Directive directive;
    private SkillSpec spec;
    private Map<String, String> params = Map.of();

    private final Deque<Frame> stack = new ArrayDeque<>();
    private Behavior child;
    private SkillNode leafNode;
    private int skillDepth;
    private int leavesExecuted;

    private boolean finished;
    private BehaviorResult terminal = BehaviorResult.FAILED;

    public SkillBehavior() {
        this(BehaviorFactory::create);
    }

    /** Test seam: inject stub child behaviors so the interpreter runs headless. */
    SkillBehavior(java.util.function.Function<DirectiveType, Behavior> behaviorFactory) {
        this.behaviorFactory = behaviorFactory;
    }

    private enum EnterResult { STARTED, EMPTY_SUCCESS, FAILED }

    private static final class Frame {
        final SkillNode node;
        int index;       // next child index (sequence / fallback)
        int iterations;  // loop iterations completed
        Frame(SkillNode node) { this.node = node; }
    }

    @Override
    public void start(BotPlayer bot, Directive directive) {
        this.bot = bot;
        this.directive = directive;
        this.progress.reset();
        this.stack.clear();
        this.child = null;
        this.leafNode = null;
        this.skillDepth = 0;
        this.leavesExecuted = 0;
        this.finished = false;

        String skillId = directive.getTarget();
        this.params = directive.getExtra() == null ? Map.of()
                : new LinkedHashMap<>(directive.getExtra());
        this.spec = SkillRegistry.get(skillId);
        if (spec == null) {
            fail("unknown skill: " + skillId);
            return;
        }

        progress.setPhase("skill:" + skillId);
        progress.logEvent("skill: " + skillId);
        EnterResult r = enterNode(spec.root);
        if (r == EnterResult.EMPTY_SUCCESS) finish(true);
        else if (r == EnterResult.FAILED) { /* reason already set */ }
        // STARTED → child behavior is running; wait for tick()
    }

    @Override
    public BehaviorResult tick(BotPlayer bot) {
        if (finished) return terminal;
        if (child == null) {
            // A skill whose root resolved synchronously in start() is finished;
            // anything else mid-run always has a child. Guard defensively.
            finish(false);
            return terminal;
        }

        BehaviorResult r = child.tick(bot);
        if (r == BehaviorResult.RUNNING) return BehaviorResult.RUNNING;

        boolean success = r == BehaviorResult.SUCCESS;
        if (leafNode != null) {
            progress.logEvent(leafNode.kind() + (success ? " ✓" : " ✗"));
        }
        child.stop();
        child = null;
        leafNode = null;

        consumeResult(success);
        return finished ? terminal : BehaviorResult.RUNNING;
    }

    // ── interpreter ────────────────────────────────────────────────────────

    /** Descend to the first executable directive leaf, pushing composite frames. */
    private EnterResult enterNode(SkillNode node) {
        switch (node.type()) {
            case DIRECTIVE -> {
                return startLeaf(node) ? EnterResult.STARTED : EnterResult.FAILED;
            }
            case SEQUENCE -> {
                var kids = node.children();
                if (kids.isEmpty()) return EnterResult.EMPTY_SUCCESS;
                Frame f = new Frame(node);
                stack.push(f);
                for (int i = 0; i < kids.size(); i++) {
                    f.index = i;
                    EnterResult r = enterNode(kids.get(i));
                    if (r == EnterResult.STARTED) return EnterResult.STARTED;
                    if (r == EnterResult.FAILED) { stack.pop(); return EnterResult.FAILED; }
                    // EMPTY_SUCCESS → next child
                }
                stack.pop();
                return EnterResult.EMPTY_SUCCESS;
            }
            case FALLBACK -> {
                var kids = node.children();
                if (kids.isEmpty()) return EnterResult.EMPTY_SUCCESS;
                Frame f = new Frame(node);
                stack.push(f);
                for (int i = 0; i < kids.size(); i++) {
                    f.index = i;
                    EnterResult r = enterNode(kids.get(i));
                    if (r == EnterResult.STARTED) return EnterResult.STARTED;
                    if (r == EnterResult.EMPTY_SUCCESS) { stack.pop(); return EnterResult.EMPTY_SUCCESS; }
                    // FAILED → try next child
                }
                stack.pop();
                return EnterResult.FAILED;
            }
            case LOOP -> {
                if (node.condition() != null && !node.condition().evaluate(bot, params)) {
                    return EnterResult.EMPTY_SUCCESS; // zero iterations
                }
                Frame f = new Frame(node);
                stack.push(f);
                int iters = 0;
                while (true) {
                    EnterResult r = enterNode(node.body());
                    if (r == EnterResult.STARTED) { f.iterations = iters; return EnterResult.STARTED; }
                    if (r == EnterResult.FAILED) { stack.pop(); return EnterResult.FAILED; }
                    iters++; // body empty-succeeded → one iteration done
                    if (iters >= node.maxIterations()
                            || (node.condition() != null && !node.condition().evaluate(bot, params))) {
                        stack.pop();
                        return EnterResult.EMPTY_SUCCESS;
                    }
                }
            }
            case IF -> {
                boolean c = node.condition() != null && node.condition().evaluate(bot, params);
                SkillNode branch = c ? node.thenBranch() : node.elseBranch();
                if (branch == null) return EnterResult.EMPTY_SUCCESS;
                return enterNode(branch);
            }
            case SKILL_REF -> {
                if (skillDepth >= MAX_SKILL_DEPTH) {
                    fail("skill-ref depth exceeded (" + node.ref() + ")");
                    return EnterResult.FAILED;
                }
                SkillSpec ref = SkillRegistry.get(node.ref());
                if (ref == null) {
                    fail("unknown skill ref: " + node.ref());
                    return EnterResult.FAILED;
                }
                skillDepth++;
                progress.logEvent("skill: " + node.ref());
                EnterResult r = enterNode(ref.root);
                skillDepth--;
                return r;
            }
        }
        return EnterResult.FAILED;
    }

    /** Consume a completed leaf's result and advance the frame stack. */
    private void consumeResult(boolean success) {
        boolean s = success;
        while (child == null && !finished) {
            if (stack.isEmpty()) {
                finish(s);
                return;
            }
            Frame f = stack.peek();
            EnterResult entered = null;
            switch (f.node.type()) {
                case SEQUENCE -> {
                    if (!s) {
                        stack.pop();
                    } else {
                        f.index++;
                        if (f.index >= f.node.children().size()) stack.pop();
                        else entered = enterNode(f.node.children().get(f.index));
                    }
                }
                case FALLBACK -> {
                    if (s) {
                        stack.pop();
                    } else {
                        f.index++;
                        if (f.index >= f.node.children().size()) stack.pop();
                        else entered = enterNode(f.node.children().get(f.index));
                    }
                }
                case LOOP -> {
                    if (!s) {
                        stack.pop();
                    } else {
                        f.iterations++;
                        if (f.iterations >= f.node.maxIterations()
                                || (f.node.condition() != null && !f.node.condition().evaluate(bot, params))) {
                            stack.pop();
                        } else {
                            entered = enterNode(f.node.body());
                        }
                    }
                }
                default -> stack.pop();
            }
            if (entered == null) continue; // frame popped → propagate same s
            if (entered == EnterResult.STARTED) return; // leaf running
            s = (entered == EnterResult.EMPTY_SUCCESS); // empty subtree → propagate its result
        }
    }

    private boolean startLeaf(SkillNode node) {
        if (leavesExecuted >= MAX_LEAF_EXECUTIONS) {
            fail("skill leaf budget exceeded");
            return false;
        }
        Directive leaf;
        try {
            leaf = buildDirective(node);
        } catch (RuntimeException e) {
            fail("bad leaf directive: " + e.getMessage());
            return false;
        }
        Behavior b = behaviorFactory.apply(leaf.getType());
        leafNode = node;
        leavesExecuted++;
        progress.setPhase(node.kind().toLowerCase());
        progress.logEvent(node.kind());
        b.start(bot, leaf);
        child = b;
        return true;
    }

    private Directive buildDirective(SkillNode node) {
        DirectiveType type = DirectiveType.valueOf(node.kind());
        Directive.Builder b = Directive.builder(type);

        String target = SkillParams.substitute(node.target(), params);
        if (target != null && !target.isEmpty()) b.target(target);
        if (node.count() != null) {
            String v = SkillParams.substitute(node.count(), params);
            if (!v.isBlank()) b.count((int) Double.parseDouble(v.trim()));
        }
        if (node.radius() != null) {
            String v = SkillParams.substitute(node.radius(), params);
            if (!v.isBlank()) b.radius((int) Double.parseDouble(v.trim()));
        }
        if (node.hasLocation()) {
            double x = Double.parseDouble(SkillParams.substitute(node.x(), params).trim());
            double y = Double.parseDouble(SkillParams.substitute(node.y(), params).trim());
            double z = Double.parseDouble(SkillParams.substitute(node.z(), params).trim());
            b.location(x, y, z);
        }
        for (var e : node.extra().entrySet()) {
            b.extra(e.getKey(), SkillParams.substitute(e.getValue(), params));
        }
        return b.build();
    }

    private void finish(boolean success) {
        if (success && spec != null && spec.verify != null) {
            boolean verified = spec.verify.evaluate(bot, params);
            if (!verified) {
                progress.setFailureReason("verify failed: " + spec.verify.predicate);
                progress.setPhase("skill:verify_failed");
                finished = true;
                terminal = BehaviorResult.FAILED;
                return;
            }
        }
        finished = true;
        terminal = success ? BehaviorResult.SUCCESS : BehaviorResult.FAILED;
        progress.setPhase(success ? "skill:done" : "skill:failed");
        if (!success && progress.toMap().get("failure_reason") == null) {
            progress.setFailureReason("skill failed");
        }
    }

    private void fail(String reason) {
        progress.setFailureReason(reason);
        progress.setPhase("skill:failed");
        finished = true;
        terminal = BehaviorResult.FAILED;
    }

    // ── Behavior surface ───────────────────────────────────────────────────

    @Override
    public String describeState() {
        String base = "skill" + (spec != null ? " " + spec.id : "");
        if (finished) return base + " (done)";
        if (child != null) return base + " → " + child.describeState();
        return base;
    }

    @Override
    public ProgressReport getProgress() {
        return progress;
    }

    @Override
    public void stop() {
        if (child != null) {
            child.stop();
            child = null;
        }
        leafNode = null;
        finished = true;
        terminal = BehaviorResult.FAILED;
    }
}
