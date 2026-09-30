SHELL := bash
BACKEND ?= c
export BACKEND
.PHONY: help oracle native native-test venv preflight hello baseline baseline-diff test probe probe-diff spec-check wheel wheel-manylinux wheel-test clean-venv clean-reference clean-native clean-dist

help:
	@echo "targets (BACKEND=c|rust selects the native implementation; default c):"
	@echo "  oracle           clone upstream at the pinned commit into reference/ and build its C library (backend c)"
	@echo "  native           build the clean-room Rust native side and install it into native/prefix (backend rust)"
	@echo "  native-test      run the Rust crate's own tests (cargo test -p rsyscall-core)"
	@echo "  venv             create the backend's venv and install python/ (editable) against its prefix"
	@echo "  preflight        check that the venv loads librsyscall from the backend's prefix"
	@echo "  hello            smoke test: clone a process, write to its stdout, exec echo"
	@echo "  baseline         run the suite, one interpreter per test, and write tests/baseline-<backend>.txt"
	@echo "  baseline-diff    compare tests/baseline-c.txt with tests/baseline-rust.txt (header line ignored)"
	@echo "  test             run pytest; pass arguments with PYTEST_ARGS='...'"
	@echo "  probe            run the black-box probes against the backend's helper executables"
	@echo "  probe-diff       run the probes against both backends and diff the normalised output"
	@echo "  spec-check       verify docs/spec: generated layouts and vectors are current, citations valid"
	@echo "  wheel            build the wheel (bundles the Rust native side) into dist/"
	@echo "  wheel-manylinux  check the wheel with auditwheel and retag it as manylinux_2_17 (uvx: auditwheel + patchelf)"
	@echo "  wheel-test       install the newest wheel into a throwaway venv and exercise it away from the source tree"
	@echo "  clean-venv       remove both venvs and in-tree build artifacts"
	@echo "  clean-reference  remove reference/ (oracle clone and build)"
	@echo "  clean-native     remove native/prefix and native/target"
	@echo "  clean-dist       remove dist/, build/ and the bundled artefacts copied into python/rsyscall/_native/"

oracle:
	scripts/oracle-build.sh

native:
	scripts/native-install.sh

native-test:
	cargo test --manifest-path native/Cargo.toml -p rsyscall-core

venv:
	scripts/venv-setup.sh

preflight:
	scripts/preflight.sh

hello: preflight
	source scripts/env.sh && "$$PY" scripts/hello.py

baseline: preflight
	source scripts/env.sh && BASELINE_OUT="$$ROOT/tests/baseline-$(BACKEND).txt" "$$PY" scripts/baseline.py $(PYTEST_ARGS)

baseline-diff:
	@diff <(sed 2d tests/baseline-c.txt) <(sed 2d tests/baseline-rust.txt) && echo "baselines identical (header line ignored)"

test: preflight
	source scripts/env.sh && "$$PY" -m pytest $(PYTEST_ARGS)

probe:
	source scripts/env.sh && for m in stdin stub stublong bootstrap; do python3 scripts/probes/probe_oracle.py "$$PREFIX/libexec/rsyscall" $$m; done

probe-diff:
	scripts/probe-compare.sh

spec-check:
	python3 scripts/abi-layouts.py --check docs/spec/abi-layouts.generated.md
	source scripts/env.sh && "$$PY" scripts/spec-vectors.py --check docs/spec/vectors/v0.json
	python3 scripts/spec-lint.py

clean-venv:
	rm -rf .venv .venv-rust python/rsyscall/_raw*.so python/rsyscall/_raw*.c python/build python/*.egg-info

clean-reference:
	rm -rf reference

wheel:
	rm -rf dist build && uv build --wheel --out-dir dist .

wheel-manylinux:
	uvx --with patchelf --from auditwheel auditwheel repair --plat manylinux_2_17_x86_64 -w dist dist/rsyscall_ng-*-linux_x86_64.whl && rm dist/rsyscall_ng-*-linux_x86_64.whl

wheel-test:
	scripts/wheel-test.sh

clean-native:
	rm -rf native/prefix native/target

clean-dist:
	rm -rf dist build python/rsyscall/_native/librsyscall.so python/rsyscall/_native/rsyscall-* *.egg-info python/*.egg-info
