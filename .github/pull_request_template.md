## What this changes, and why

<!-- What a client of the server would notice, and the reasoning behind the change. The diff shows the how. -->

## Which commitment it keeps

<!-- Only if it touches a path CODEOWNERS lists separately: authorization, the output models,
columns.json, the checks that hold this repository to the runtime, the dependencies or the
release workflow. Otherwise delete this section. -->

## Checklist

- [ ] A test for the behaviour, named for what it protects; for a bug fix, it fails without the fix
- [ ] `pytest -q`, `ruff check .`, `ruff format --check .` and `codespell` pass, and CI's columns job if `columns.json` changed
- [ ] A line under the unreleased heading in `CHANGELOG.md`, and the README if it describes what changed
- [ ] Every commit is signed off (`git commit -s`) and signed

## Did a coding agent help? (optional)

<!-- Agents are welcome, and telling us is welcome, not required. If one helped, a line on
what it did and what you checked yourself tells a reviewer where to look. Either way, you
are responsible for every line and have read every one. -->
