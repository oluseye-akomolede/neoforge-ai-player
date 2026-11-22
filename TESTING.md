# Running the Java tests

A fresh clone is enough:

```bash
./gradlew test                                    # whole Java suite
./gradlew test --tests '*WorldTimeTest*'          # one class
```

`gradle/wrapper/gradle-wrapper.jar` is tracked on purpose. Without it `./gradlew`
does not run at all for anyone without a pre-populated `~/.gradle` cache, which is
every fresh clone and every CI-style run. Do not add it back to `.gitignore`.

## `libs/` is not needed for the tests

`build.gradle` declares its dependencies from Maven coordinates
(`net.neoforged:neoforge`, the JUnit BOM) and references no `libs/` directory.
Jars under `libs/` are for the mod's optional runtime integrations and are not
consumed by the test task. Verified by running `--tests '*WorldTimeTest*'` in a
scratch `git clone` with no `libs/` directory present at all: 8 tests, 0 failures.

## `--offline` only works on a warm checkout

A cold clone cannot build with `--offline`: the NeoForge userdev plugin fetches
Minecraft metadata into `.gradle/caches/minecraft/versions/<mc_version>/` on first
use and fails with

```
Could not find the file: .../.gradle/caches/minecraft/versions/1.21.1/metadata.json and we are offline.
```

That failure is about the Minecraft toolchain, not about your test. Drop
`--offline` for the first run in a new checkout; it is fine afterwards.

## Reading a failure

Do not judge a test run by "BUILD FAILED" alone. A `--tests` filter that matches
**no class** also fails, with

```
> No tests found for given includes: [*SomeTest*](--tests filter)
```

so a typo in the class name, or a branch that predates the test, looks the same
colour as a genuine regression. Read that line before concluding anything, and
check the class exists in the tree you are actually on:

```bash
git ls-files "*SomeTest*"
```

Confirming a run really executed the tests is the same discipline: a task line of
`Task :test FROM-CACHE` means nothing ran. Use `--rerun-tasks`, or read
`build/test-results/test/TEST-*.xml` and check its `tests="N" failures="0"`.
