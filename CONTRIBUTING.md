# Contributing to rsyscall-ng

Bug reports, questions and pull requests are welcome. This document covers the mechanics. The
repository layout, the requirements and the development flow are in [README.md](README.md).

For security problems, do not open an issue: see [SECURITY.md](SECURITY.md).

## Developer Certificate of Origin (required)

The provenance of the code matters in this project, so every commit must be signed off under the
[Developer Certificate of Origin 1.1](https://developercertificate.org/):

```bash
git commit -s
```

That adds a `Signed-off-by: Your Name <your@email>` trailer, certifying that you wrote the change
or otherwise have the right to submit it under the project's license (MIT). Use your real name and
a working email. Pull requests with unsigned commits will be asked to add the sign-off:

```bash
git commit --amend --no-edit -s     # fix the last commit
```

## Signing commits with GPG or SSH (encouraged)

Cryptographically signing your commits is welcome on top of the DCO:

```bash
git commit -s -S
```

It is encouraged, not required: the DCO sign-off plus review is the bar for merging. If you
already have a signing key configured with GitHub, please use it.

## Pull requests

- Set up both backends once, as in the README's quick start. The upstream C library is built
  locally only as a test oracle; the Rust one is what the package ships:

  ```bash
  make oracle && make venv                  # C oracle, .venv
  make native && make venv BACKEND=rust     # Rust native side, .venv-rust
  ```

- Run the checks before pushing:

  ```bash
  make native-test      # the Rust crate's own tests
  make spec-check       # docs/spec: generated tables and vectors, citations
  make test             # the test-suite against the C oracle (BACKEND=rust for the Rust side)
  ```

- If your change can alter test results, record both baselines and compare them. The CI requires
  the C oracle and the Rust native side to give the same per-test results on the same machine:

  ```bash
  make baseline && make baseline BACKEND=rust && make baseline-diff
  ```

- `tests/baseline-*.txt` are generated: never edit them by hand. When a change alters the
  results, commit the regenerated files and explain the change in `tests/baseline-notes.md`.
- `docs/spec` cites line numbers of files under `python/`, and `make spec-check` verifies that the
  cited lines exist. If your change moves cited lines, update the citations.
- English for code, comments, commit messages and docs. Spanish is fine everywhere else
  (issues and discussions can be bilingual).
