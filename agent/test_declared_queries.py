"""The script's declared queries: the parser, the clamps, and the fetch.

Change script-lookups-and-results, owner A2. A script declares its searches
in a LITERAL at the top (`queries = [{name, kind, ...}]`) and reads the
results as `look.queries.<name>`. The agent reads the declaration from the
SOURCE TEXT and never executes it, fetches exactly those searches before the
tick, and installs them on the envelope.

Every refusal below is a case a first prototype ACCEPTED (the prototype is
why these tests exist): the declaration must not run, must not be dynamic,
and must not appear twice.
"""

import json
import sys
import unittest

sys.path.insert(0, __file__.rsplit("/", 1)[0])

import script_tick as st  # noqa: E402


class TestParseAcceptsLiteralDeclarations(unittest.TestCase):
    def test_absent_declaration_is_an_empty_list(self):
        self.assertEqual(st.parse_declared_queries("api.log('hi')"), [])
        self.assertEqual(st.parse_declared_queries(None), [])

    def test_a_full_declaration(self):
        src = (
            "queries = [\n"
            "  {name: 'ore', kind: 'blocks', id: 'minecraft:diamond_ore', radius: 32, max: 5},\n"
            "  {name: 'sheep', kind: 'entities', id: 'minecraft:sheep'},\n"
            "  {name: 'here', kind: 'block_at', x: 1, y: -60, z: 2},\n"
            "  {name: 'village', kind: 'locate', id: 'minecraft:village'},\n"
            "];\n"
            "api.log('start')")
        out = st.parse_declared_queries(src)
        self.assertEqual([q["name"] for q in out], ["ore", "sheep", "here", "village"])
        self.assertEqual(out[0]["radius"], 32)
        self.assertEqual(out[2]["y"], -60)

    def test_const_let_and_var_bindings_are_all_read(self):
        for keyword in ("const", "let", "var"):
            src = f"{keyword} queries = [{{name: 'c', kind: 'blocks', id: 'minecraft:chest'}}];"
            self.assertEqual(st.parse_declared_queries(src)[0]["name"], "c", keyword)

    def test_a_comment_on_the_terminator_line_before_code_is_allowed(self):
        """F-2: `// why` on the `];` line must not refuse the script."""
        for src in ("queries = [{name: 'c', kind: 'blocks', id: 'minecraft:chest'}]; // why\n"
                    "api.log('start')",
                    "queries = [{name: 'c', kind: 'blocks', id: 'minecraft:chest'}]; /* why */\n"
                    "api.log('start')"):
            self.assertEqual(len(st.parse_declared_queries(src)), 1, src)

    def test_code_after_the_terminator_on_its_own_line_is_refused(self):
        """F-1: `;` starts a new statement, so what follows is unvalidated.

        Measured: the old tail rule accepted this and `evil()` ran, because
        the runner service executes the script. The `+ evil()` and
        `, evil()` forms were already refused; the `;` form was the gap.
        """
        for tail in ("; evil()", "; /*x*/ evil()", "; evil();", "; 2"):
            src = "queries = [{name: 'c', kind: 'blocks', id: 'minecraft:chest'}]" + tail
            with self.assertRaises(st.DeclaredQueriesError, msg=tail):
                st.parse_declared_queries(src)

    def test_a_trailing_comment_after_the_bracket_is_allowed(self):
        src = "queries = [{name: 'c', kind: 'blocks', id: 'minecraft:chest'}]  // searched first\n"
        self.assertEqual(len(st.parse_declared_queries(src)), 1)

    def test_the_tail_rule_holds_with_and_without_the_terminator(self):
        """The residual the reviewer found: only the `];` shapes were pinned.

        `] // why` and a bare `]` followed by code were refused while `];`
        equivalents were accepted, so the spec sentence ("a comment followed
        by code stays legal") was false for the no-semicolon form. Both are
        legal now, and both forms are tested.
        """
        L = "queries = [{name: 'c', kind: 'blocks', id: 'minecraft:chest'}]"
        for name, src in {
            "bare bracket, code next line": L + "\napi.log('x')",
            "bracket, // comment, code next line": L + " // why\napi.log('x')",
            "semicolon, // comment, code next line": L + "; // why\napi.log('x')",
            "semicolon, one-line block comment": L + "; /* w */\napi.log('x')",
            "semicolon, CRLF": L + ";\r\napi.log('x')",
            "bare bracket at EOF": L,
            "semicolon at EOF": L + ";",
            "trailing spaces, no code": L + ";   \n",
        }.items():
            self.assertEqual(len(st.parse_declared_queries(src)), 1, name)

    def test_code_on_the_terminator_line_is_refused_without_a_semicolon(self):
        L = "queries = [{name: 'c', kind: 'blocks', id: 'minecraft:chest'}]"
        for name, src in {
            "bare bracket then code": L + " evil()",
            "block comment then code": L + " /*x*/ evil()",
            "semicolon and block comment then code": L + "; /*x*/ evil()",
        }.items():
            with self.assertRaises(st.DeclaredQueriesError, msg=name):
                st.parse_declared_queries(src)

    def test_a_block_comment_may_not_carry_the_statement_across_a_line(self):
        """Measured: treating a multi-line block comment as the line break
        ACCEPTED `]; /* a\\n */ evil()` -- and evil() runs."""
        L = "queries = [{name: 'c', kind: 'blocks', id: 'minecraft:chest'}]"
        for tail in ("; /* a\n */ evil()", "; /* a\n b */\napi.log('x')"):
            with self.assertRaises(st.DeclaredQueriesError, msg=tail):
                st.parse_declared_queries(L + tail)

    def test_an_empty_list_is_an_empty_list(self):
        self.assertEqual(st.parse_declared_queries("queries = []"), [])


class TestParseRefusesAnythingDynamic(unittest.TestCase):
    """Each of these was ACCEPTED by the first prototype."""

    def _refused(self, src, fragment=None):
        with self.assertRaises(st.DeclaredQueriesError) as ctx:
            st.parse_declared_queries(src)
        if fragment is not None:
            self.assertIn(fragment, str(ctx.exception))
        return str(ctx.exception)

    def test_a_call_in_the_array_is_refused(self):
        # The prototype validated `[...]` and let `+ evil()` run after it.
        self._refused(
            "queries = [{name: 'c', kind: 'blocks', id: 'minecraft:chest'}] + evil();")

    def test_a_function_call_as_the_value_is_refused(self):
        self._refused("queries = [{name: 'c', kind: 'blocks', id: get_id()}];")

    def test_a_variable_as_the_value_is_refused(self):
        self._refused("queries = [{name: 'c', kind: 'blocks', id: target}];")

    def test_a_non_array_right_side_is_refused(self):
        self._refused("queries = makeQueries();", "array literal")

    def test_a_second_declaration_is_refused(self):
        msg = self._refused(
            "queries = [{name: 'a', kind: 'blocks', id: 'minecraft:chest'}];\n"
            "queries = [{name: 'b', kind: 'blocks', id: 'minecraft:dirt'}];",
            "more than once")
        self.assertIn("line 2", msg)

    def test_a_property_write_is_not_the_declaration(self):
        self._refused("api.queries = [];", "bare assignment")

    def test_an_unknown_key_is_refused(self):
        self._refused("queries = [{name: 'c', kind: 'blocks', id: 'minecraft:chest', n: 1}];")

    def test_proto_is_refused(self):
        self._refused("queries = [{name: 'c', kind: 'blocks', id: 'minecraft:chest',"
                      " __proto__: {}}];")

    def test_an_unknown_kind_is_refused(self):
        self._refused("queries = [{name: 'c', kind: 'scan', id: 'minecraft:chest'}];",
                      "unknown kind")

    def test_a_missing_required_key_is_refused(self):
        self._refused("queries = [{name: 'c', kind: 'block_at', x: 1, y: 2}];", "needs")

    def test_a_non_identifier_name_is_refused(self):
        self._refused("queries = [{name: 'my ore', kind: 'blocks', id: 'minecraft:chest'}];",
                      "identifier")

    def test_a_duplicate_name_is_refused(self):
        self._refused(
            "queries = [{name: 'c', kind: 'blocks', id: 'minecraft:chest'},"
            " {name: 'c', kind: 'blocks', id: 'minecraft:dirt'}];",
            "twice")

    def test_a_single_quoted_string_with_a_comma_is_not_split(self):
        # The value is odd but the point is structural: the comma is inside a
        # string, so this is ONE query with one id.
        out = st.parse_declared_queries(
            "queries = [{name: 'c', kind: 'blocks', id: 'minecraft:chest,a'}]")
        self.assertEqual(out[0]["id"], "minecraft:chest,a")

    def test_too_many_queries_are_refused(self):
        items = ",".join(f"{{name: 'q{i}', kind: 'blocks', id: 'minecraft:chest'}}"
                         for i in range(st.MAX_DECLARED_QUERIES + 1))
        self._refused(f"queries = [{items}];", "at most")


class _FakeApi:
    def __init__(self, timeout=None, boom=None):
        self.calls = []
        self._timeout = timeout
        self._boom = boom

    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        if self._boom is not None and name == self._boom[0]:
            raise self._boom[1]
        return {"ok": True, "kind": name, "matches": []}

    def find_blocks(self, bot, block, radius=32, max_count=10):
        return self._record("find_blocks", bot, block, radius, max_count)

    def find_entities(self, bot, target, radius=32.0):
        return self._record("find_entities", bot, target, radius)

    def block_at(self, bot, x, y, z):
        return self._record("block_at", bot, x, y, z)

    def locate(self, bot, target, chunk_radius=100, timeout=120):
        return self._record("locate", bot, target, chunk_radius, timeout)


class TestRunDeclaredQueries(unittest.TestCase):
    def queries(self, *entries):
        return st.parse_declared_queries("queries = [" + ",".join(entries) + "]")

    def test_nothing_declared_returns_none_and_reads_nothing(self):
        api = _FakeApi()
        self.assertIsNone(st.run_declared_queries(api, "bot", []))
        self.assertEqual(api.calls, [])

    def test_each_kind_uses_its_read_route_once(self):
        api = _FakeApi()
        out = st.run_declared_queries(api, "bot", self.queries(
            "{name: 'a', kind: 'blocks', id: 'minecraft:chest'},"
            "{name: 'b', kind: 'entities', id: 'minecraft:sheep'},"
            "{name: 'c', kind: 'block_at', x: 1, y: 2, z: 3},"
            "{name: 'd', kind: 'locate', id: 'minecraft:village'}"))
        self.assertEqual(sorted(out), ["a", "b", "c", "d"])
        self.assertEqual([c[0] for c in api.calls],
                         ["find_blocks", "find_entities", "block_at", "locate"])

    def test_locate_uses_the_bounded_timeout(self):
        api = _FakeApi()
        st.run_declared_queries(api, "bot", self.queries(
            "{name: 'd', kind: 'locate', id: 'minecraft:village'}"))
        # locate(bot, target, chunk_radius, timeout): timeout is positional 3.
        self.assertEqual(api.calls[0][1][3], st.LOCATE_TIMEOUT)
        self.assertEqual(api.calls[0][1][1], "minecraft:village")

    def test_a_radius_over_the_clamp_is_narrowed_and_reported(self):
        api = _FakeApi()
        out = st.run_declared_queries(api, "bot", self.queries(
            "{name: 'a', kind: 'blocks', id: 'minecraft:chest', radius: 1000}"))
        # find_blocks(bot, block, radius, max_count): radius is positional.
        self.assertEqual(api.calls[0][1][2], st.MAX_BLOCK_RADIUS)
        self.assertEqual(out["a"]["clamped"], {"radius": st.MAX_BLOCK_RADIUS})

    def test_an_unclamped_query_carries_no_clamped_key(self):
        api = _FakeApi()
        out = st.run_declared_queries(api, "bot", self.queries(
            "{name: 'a', kind: 'blocks', id: 'minecraft:chest'}"))
        self.assertNotIn("clamped", out["a"])

    def test_two_names_for_one_search_pay_one_scan(self):
        api = _FakeApi()
        out = st.run_declared_queries(api, "bot", self.queries(
            "{name: 'a', kind: 'blocks', id: 'minecraft:chest'},"
            "{name: 'b', kind: 'blocks', id: 'minecraft:chest'}"))
        self.assertEqual(len(api.calls), 1)
        self.assertEqual(out["a"], out["b"])

    def test_a_failed_read_is_that_names_failure_and_does_not_raise(self):
        import requests
        api = _FakeApi(boom=("find_blocks", requests.exceptions.Timeout()))
        out = st.run_declared_queries(api, "bot", self.queries(
            "{name: 'a', kind: 'blocks', id: 'minecraft:chest'},"
            "{name: 'b', kind: 'block_at', x: 0, y: 0, z: 0}"))
        self.assertEqual(out["a"]["ok"], False)
        self.assertEqual(out["a"]["reason"], "timeout")
        self.assertNotIn("matches", out["a"])
        self.assertEqual(out["b"]["ok"], True, "a sibling failure is not contagious")

    def test_an_unreachable_mod_is_unavailable(self):
        import requests
        api = _FakeApi(boom=("block_at", requests.exceptions.ConnectionError()))
        out = st.run_declared_queries(api, "bot", self.queries(
            "{name: 'b', kind: 'block_at', x: 0, y: 0, z: 0}"))
        self.assertEqual(out["b"]["reason"], "unavailable")

    def test_over_budget_still_runs_and_logs(self):
        import io
        import contextlib
        api = _FakeApi()
        many = self.queries(*[
            f"{{name: 'q{i}', kind: 'blocks', id: 'minecraft:chest{i}'}}"
            for i in range(st.MAX_DECLARED_QUERIES)])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            out = st.run_declared_queries(api, "bot", many)
        self.assertEqual(len(out), st.MAX_DECLARED_QUERIES, "every query still ran")
        self.assertIn("budget exceeded", buf.getvalue())


class TestEnvelopeCarriesQueries(unittest.TestCase):
    def test_build_envelope_omits_the_key_when_none(self):
        import snapshot
        env = snapshot.build_envelope({"a": 1}, tick=1)
        self.assertNotIn("queries", env)

    def test_build_envelope_carries_a_map(self):
        import snapshot
        env = snapshot.build_envelope({"a": 1}, tick=1, queries={"ore": {"ok": True}})
        self.assertEqual(env["queries"], {"ore": {"ok": True}})
        json.dumps(env)  # serialisable as the runner body requires


class TestParseReadsCodeNotText(unittest.TestCase):
    """Reading a declared query is the FEATURE; only writing one is refused.

    Live A2 E2E failure, 2026-11-27: the parser scanned raw source, so any
    occurrence of `queries` preceded by "." raised "must be a bare
    assignment, not a property" -- which refused every script that READS
    `look.queries.<name>`, and every script whose COMMENT or string mentions
    it. The spec's own documented example could not bind.

    The spec requires the read: "A declared query answers from data fetched
    before the tick" (script-lookups-and-results, bot-coded-agents,
    `#### Scenario: A declared query answers from data fetched before the
    tick`), whose THEN is that `look.queries.ore` MUST be the result of a
    `find_blocks` call made before evaluation and MUST spend no host call.
    """

    # The exact script in the spec delta (script-lookups-and-results,
    # "the searches it wants to run"), which is the example the feature
    # documentation tells an author to write.
    SPEC_EXAMPLE = '''queries = [
  {name: "ore",   kind: "blocks",   id: "minecraft:diamond_ore", radius: 32},
  {name: "cows",  kind: "entities", id: "minecraft:cow"},
]
return look.queries.ore.matches.length
  ? api.do("goto_block", look.queries.ore.matches[0]) : api.done("none");
'''

    def test_the_spec_own_example_binds_and_yields_its_queries(self):
        """(a) The documented example must bind -- it did not."""
        got = st.parse_declared_queries(self.SPEC_EXAMPLE)
        self.assertEqual([q["name"] for q in got], ["ore", "cows"])

    def test_a_declared_query_answers_from_data_fetched_before_the_tick(self):
        """(c) The spec scenario by NAME: reading the result is legal.

        scenario: "A declared query answers from data fetched before the
        tick" -- `look.queries.ore` MUST be readable and MUST spend no host
        call. This test proves the BIND side: a script that reads it parses.
        """
        src = ("queries = [{name: 'ore', kind: 'blocks', "
               "id: 'minecraft:diamond_ore'}];\n"
               "return look.queries.ore.matches.length;")
        got = st.parse_declared_queries(src)
        self.assertEqual([q["name"] for q in got], ["ore"])

    def test_a_comment_mentioning_look_queries_binds(self):
        """(b) A comment is not code. Live: Axiom's line 3 was a comment."""
        src = ("// I want look.queries.ore and look.queries.cows here\n"
               "queries = [{name: 'ore', kind: 'blocks', id: 'minecraft:stone'}];\n"
               "return 1;")
        got = st.parse_declared_queries(src)
        self.assertEqual([q["name"] for q in got], ["ore"])

    def test_a_comment_with_an_apostrophe_binds(self):
        """Regression: house style writes "the bot's ..." in comments.

        The apostrophe used to open a string inside the comment, leaving a
        lone quote that ran to EOF and swallowed the declaration -- the script
        bound with ZERO queries and no error. An ODD count failed, an even
        count survived by accident, which is why every apostrophe-free fixture
        passed. Comments are now masked before strings are stripped.
        """
        for n in (1, 2, 3, 4):
            with self.subTest(apostrophes=n):
                src = ("// " + " ".join(f"a{i}'s" for i in range(n)) + "\n"
                       "queries = [{name: 'ore', kind: 'blocks', "
                       "id: 'minecraft:stone'}];\n"
                       "return 1;")
                got = st.parse_declared_queries(src)
                self.assertEqual([q["name"] for q in got], ["ore"])

    def test_a_string_containing_a_comment_marker_and_an_apostrophe_binds(self):
        """The other direction: masking comments first must not break strings.

        A string holding both `//` and an apostrophe is still a string -- the
        comment mask has to respect string bounds, or this test would fail the
        same way the apostrophe case did before the order swap.

        Asserted on the MASK, not through parse_declared_queries: every
        string-typed query field is pattern-constrained (name must be an
        identifier, id must be a valid item id, radius an int), so no VALID
        declaration can carry arbitrary prose. Routing this through the schema
        tests the schema, not the masking.
        """
        src = ("queries = [\"see // it's fine\"]\n"
               "return 1;")
        masked = st._strip_strings(st._mask_comments(src))
        # The string body is blanked, and the `//` inside it did not start a
        # comment that ate the rest of the line.
        self.assertNotIn("fine", masked)
        self.assertIn("queries", masked)
        self.assertIn("return 1;", masked)

    def test_compound_property_assignment_is_refused(self):
        """`+=`, `||=`, `??=` diverge from the validated literal, so refuse.

        The two-character operators are the ones that need the whole operator
        run read: testing only the character after `queries` sees `|` or `?`,
        not the `=` two positions later, and ACCEPTs them.
        """
        base = ("queries = [{name: 'ore', kind: 'blocks', "
                "id: 'minecraft:stone'}];\n")
        for op in ("+=", "||=", "??="):
            with self.subTest(op=op):
                with self.assertRaises(st.DeclaredQueriesError):
                    st.parse_declared_queries(
                        base + f"api.queries {op} [];\nreturn 1;")

    def test_a_property_comparison_is_not_an_assignment(self):
        """`==` and `===` are compares; refusing them would break real code."""
        base = ("queries = [{name: 'ore', kind: 'blocks', "
                "id: 'minecraft:stone'}];\n")
        for cmp in ("if (look.queries == null) {}", "if (look.queries === null) {}"):
            with self.subTest(cmp=cmp):
                got = st.parse_declared_queries(base + cmp + "\nreturn 1;")
                self.assertEqual([q["name"] for q in got], ["ore"])

    def test_a_string_mentioning_look_queries_binds(self):
        """A string literal is not code either."""
        src = ("queries = [{name: 'ore', kind: 'blocks', id: 'minecraft:stone'}];\n"
               "api.say('reading look.queries.ore now');\n"
               "return look.queries.ore.matches.length;")
        got = st.parse_declared_queries(src)
        self.assertEqual([q["name"] for q in got], ["ore"])

    def test_a_property_assignment_is_still_refused(self):
        """(d) A property WRITE is dynamic and stays refused."""
        for src in ("api.queries = [];",
                    "look.queries = [{name: 'a', kind: 'blocks', id: 'minecraft:stone'}];"):
            with self.assertRaises(st.DeclaredQueriesError) as ctx:
                st.parse_declared_queries(src)
            self.assertIn("bare assignment", str(ctx.exception))

    def test_a_property_read_is_not_a_property_assignment(self):
        """The distinction the defect collapsed: read legal, write refused."""
        read_only = "return look.queries.ore.matches.length;"
        self.assertEqual(st.parse_declared_queries(read_only), [])
        with self.assertRaises(st.DeclaredQueriesError):
            st.parse_declared_queries("api.queries = [];")

    def test_duplicate_and_trailing_junk_are_still_refused(self):
        """(e)(f) The two refusals that already worked must keep working."""
        with self.assertRaises(st.DeclaredQueriesError) as ctx:
            st.parse_declared_queries(
                "queries = [{name: 'a', kind: 'blocks', id: 'minecraft:chest'}];\n"
                "queries = [{name: 'b', kind: 'blocks', id: 'minecraft:dirt'}];")
        self.assertIn("more than once", str(ctx.exception))
        with self.assertRaises(st.DeclaredQueriesError):
            st.parse_declared_queries(
                "queries = [{name: 'c', kind: 'blocks', id: 'minecraft:chest'}] + evil();")


if __name__ == "__main__":
    unittest.main()
