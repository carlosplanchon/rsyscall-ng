SHELL := bash
.PHONY: help oracle venv hello baseline test clean-venv clean-reference

help:
	@echo "targets:"
	@echo "  oracle           clone upstream at the pinned commit into reference/ and build its C library"
	@echo "  venv             create .venv and install python/ (editable) against the oracle"
	@echo "  hello            smoke test: clone a process, write to its stdout, exec echo"
	@echo "  baseline         run the suite and write tests/baseline-c.txt"
	@echo "  test             run pytest; pass arguments with PYTEST_ARGS='...'"
	@echo "  clean-venv       remove .venv and in-tree build artifacts"
	@echo "  clean-reference  remove reference/ (oracle clone and build)"

oracle:
	scripts/oracle-build.sh

venv:
	scripts/venv-setup.sh

hello:
	source scripts/env.sh && "$$PY" scripts/hello.py

baseline:
	source scripts/env.sh && "$$PY" scripts/baseline.py $(PYTEST_ARGS)

test:
	source scripts/env.sh && "$$PY" -m pytest $(PYTEST_ARGS)

clean-venv:
	rm -rf .venv python/rsyscall/_raw*.so python/rsyscall/_raw*.c python/build python/*.egg-info

clean-reference:
	rm -rf reference
