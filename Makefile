QUISP_MAKEFILE = "./quisp/Makefile"
NPROC ?= $(shell nproc)
EXPECTED_OMNETPP_VERSION ?= $(shell cat $(CURDIR)/.omnetpp-version 2>/dev/null)
QUTIP_VENV ?= $(CURDIR)/.venv-qutip
QUTIP_PYTHON ?= $(QUTIP_VENV)/bin/python
DASHBOARD_HOST ?= 127.0.0.1
DASHBOARD_PORT ?= 8765
DASHBOARD_LOG_DIR ?= $(CURDIR)/scripts/dashboard/runs
DASHBOARD_AUDIT_LOG ?= $(CURDIR)/scripts/dashboard/dashboard_audit.log
DASHBOARD_WORKSPACE_ROOT ?= $(CURDIR)
DASHBOARD_QUISP_BINARY ?= $(CURDIR)/quisp/quisp

.PHONY: all tidy format ci makefile-exe makefile-lib check-omnetpp checkmakefile googletest clean test coverage coverage-report help quispr run-unit-test run-sim-test qutip-env qutip-check dashboard-backend

all: makefile-exe
	$(MAKE) -C quisp -j$(NPROC)

run-module-test: lib-debug
	cd module_tests && ./runtest

run-unit-test: makefile-lib googletest
	QUTIP_PYTHON_EXECUTABLE=$(QUTIP_PYTHON) $(MAKE) -C quisp run-unit-test -j$(NPROC)

run-sim-test: exe
	pip install -r requirements.txt
	pytest ./simulation_tests -n auto

qutip-env:
	python3 -m venv $(QUTIP_VENV)
	$(QUTIP_PYTHON) -m pip install --upgrade pip
	$(QUTIP_PYTHON) -m pip install -r requirements-qutip.txt

qutip-check:
	$(QUTIP_PYTHON) -c "import qutip, qutip_qip, qutip.qip; print(qutip.__version__)"

test: run-unit-test run-module-test run-sim-test

exe: makefile-exe
	$(MAKE) -C quisp -j$(NPROC)

dashboard-backend: exe
	QUTIP_PYTHON_EXECUTABLE=$(QUTIP_PYTHON) \
	DASHBOARD_HOST=$(DASHBOARD_HOST) \
	DASHBOARD_PORT=$(DASHBOARD_PORT) \
	DASHBOARD_LOG_DIR=$(DASHBOARD_LOG_DIR) \
	DASHBOARD_AUDIT_LOG=$(DASHBOARD_AUDIT_LOG) \
	DASHBOARD_WORKSPACE_ROOT=$(DASHBOARD_WORKSPACE_ROOT) \
	DASHBOARD_QUISP_BINARY=$(DASHBOARD_QUISP_BINARY) \
	./scripts/dashboard/run_backend.sh

lib: makefile-lib
	$(MAKE) -C quisp -j$(NPROC)

lib-debug: makefile-lib
	$(MAKE) -C quisp -j$(NPROC) MODE=debug

msgheaders: check-omnetpp checkmakefile
	$(MAKE) -C quisp msgheaders

format-ci:
	$(MAKE) -C quisp format-ci

format: quisp/Makefile
	$(MAKE) -C quisp format

tidy: quisp/Makefile
	$(MAKE) -C quisp tidy

check-omnetpp:
	@if [ -z "$(EXPECTED_OMNETPP_VERSION)" ]; then \
		echo 'Expected OMNeT++ version is not set. Check .omnetpp-version or EXPECTED_OMNETPP_VERSION.'; \
		exit 1; \
	fi
	@if ! command -v opp_makemake >/dev/null 2>&1; then \
		echo 'opp_makemake was not found. Source the QuISP/OMNeT++ environment first, or use the devcontainer/CI image.'; \
		exit 1; \
	fi
	@if ! command -v opp_configfilepath >/dev/null 2>&1; then \
		echo 'opp_configfilepath was not found. Source the QuISP/OMNeT++ environment first, or use the devcontainer/CI image.'; \
		exit 1; \
	fi
	@echo "Using OMNeT++ config: $$(opp_configfilepath)"
	@version_file="$$(dirname "$$(opp_configfilepath)")/Version"; \
	if [ ! -f "$$version_file" ]; then \
		echo "OMNeT++ version file not found: $$version_file"; \
		exit 1; \
	fi; \
	actual_version="$$(cat "$$version_file")"; \
	echo "Using OMNeT++ version: $$actual_version"; \
	if [ "$$actual_version" != "$(EXPECTED_OMNETPP_VERSION)" ]; then \
		echo "Expected OMNeT++ version: $(EXPECTED_OMNETPP_VERSION)"; \
		echo 'Install the expected OMNeT++ version locally, or use the devcontainer/CI image.'; \
		exit 1; \
	fi

makefile-exe: check-omnetpp eigen spdlog json
	cd quisp && opp_makemake -f --deep -O out -i ./makefrag

makefile-lib: check-omnetpp eigen spdlog json
	cd quisp && opp_makemake -f --deep -O out -i ./makefrag -M debug  --make-so

googletest/CMakeLists.txt:
	git submodule update --init googletest

googletest/build: googletest/CMakeLists.txt
	mkdir -p googletest/build && cd googletest/build && cmake .. -G "Unix Makefiles"

googletest/build/lib: googletest/build
	make -C googletest/build

googletest: googletest/build/lib

spdlog/CMakeLists.txt:
	git submodule update --init spdlog

spdlog: spdlog/CMakeLists.txt

json/CMakeLists.txt:
	git submodule update --init json

json: json/CMakeLists.txt

eigen/CMakeLists.txt:
	git submodule update --init eigen

eigen: eigen/CMakeLists.txt
clean:
	@if [ -f "$(QUISP_MAKEFILE)" ]; then \
		$(MAKE) -C quisp clean; \
	fi
	$(RM) quisp/Makefile quisp/quisp quisp/quisp_dbg quisp/run_unit_test quisp/libquisp*
	$(RM) -r quisp/out
	$(RM) -rf quisp/coverage* quisp/default.profraw quisp/lcov.info

distclean:
	git submodule deinit --all -f
	make clean

coverage: makefile-lib
	$(MAKE) -C quisp lcov.info

coverage-report: makefile-lib
	$(MAKE) -C quisp/ coverage/index.html


checkmakefile:
	@if [ ! -f "$(QUISP_MAKEFILE)" ]; then \
	echo; \
	echo '===================================================================================================='; \
	echo 'quisp/Makefile does not exist. Please use "make makefile-exe" or "make makefile-lib" to generate it!'; \
	echo '===================================================================================================='; \
	echo; \
	exit 1; \
	else \
	echo 'quisp/Makefile exists.'; \
	fi

help:
	@echo; \
	echo '===================================================================================================='; \
	echo 'Usage: make [target]'; \
	echo '===================================================================================================='; \
	echo; \
	echo 'Available targets:'; \
	echo '  exe                 build the executable quisp/quisp'; \
	echo '  lib                 build the library quisp/libquisp{_dbg}.{dylib,so}'; \
	echo '  qutip-env           create .venv-qutip and install qutip dependencies'; \
	echo '  qutip-check         verify that .venv-qutip can import qutip and qutip_qip'; \
	echo '  dashboard-backend   start dashboard backend with repo-local qutip python'; \
	echo '  check-omnetpp       verify that OMNeT++ build tools and version match .omnetpp-version'; \
	echo '  clean               remove objcet files, executables and libraries'; \
	echo '  distclean           remove everything includes submoduled components'; \
	echo '  test       			build and run all tests'; \
	echo '  run-unit-test       build unit tests and run it'; \
	echo '  run-sim-test       	build simulation tests and run it'; \
	echo '  run-module-test     build module tests(opp_test) and run it'; \
	echo '  coverage            generate coverage as quisp/lcov.info'; \
	echo '  coverage-report     generate html coverage report at quisp/coverage/index.html'; \
	echo '  format              run clang-format on the source files'; \
	echo '  tidy                run clang-tidy on the source files to do static analysis'; \
