# Copyright (c) 2021, SKA Observatory
# Copyright (c) 2025, UK SKA Regional Centre (UKSRC)
#
# All rights reserved.
#
# This code is licensed under the BSD 3-Clause License (with modifications).
#
# include Makefile for python related targets and variables

.PHONY: metrics-collect-target
$(filter-out metrics-collect-target, $(MAKECMDGOALS)): metrics-collect-target

# do not declare targets if help had been invoked
ifneq (long-help,$(firstword $(MAKECMDGOALS)))
ifneq (help,$(firstword $(MAKECMDGOALS)))

ifeq ($(strip $(PROJECT)),)
  NAME=$(shell basename $(CURDIR))
else
  NAME=$(PROJECT)
endif

PYTHON_SUPPORT := $(shell dirname $(abspath $(lastword $(MAKEFILE_LIST))))/.make-python-support

SHELL=/usr/bin/env bash

PYTHON_SRC ?= src/## Python src directory - defaults to src

PYTHON_RUNNER ?=## use to specify command runner, e.g. "poetry run" or "python -m"

PYTHON_VARS_BEFORE_PYTEST ?= PYTHONPATH=$(CURDIR)/$(PYTHON_SRC):/app/$(PYTHON_SRC):$(PYTHONPATH)## used to include needed argument variables to pass to pytest if necessary

PYTHON_VARS_AFTER_PYTEST ?=## used to include optional pytest flags

PYTHON_TEST_FILE ?= tests/## Option pytest test file

PYTHON_LINE_LENGTH ?= 79## Default value piped to all linting tools

PYTHON_TEST_FOLDER_NBMAKE ?= .## Option folder for notebook tests

NOTEBOOK_IGNORE_FILES ?=## Option to exclude test files, usage: not <file1> and not <file2>

PYTHON_FILE_EXTENSION_IGNORE ?= not .py## Used to ignore .py files from being tested in notebook-test target

ifeq ($(NOTEBOOK_IGNORE_FILES),)
	PYTHON_SWITCHES_FOR_NBMAKE ?= --disable-warnings -rs -k "$(PYTHON_FILE_EXTENSION_IGNORE)"
else
	PYTHON_SWITCHES_FOR_NBMAKE ?= --disable-warnings -rs -k "$(PYTHON_FILE_EXTENSION_IGNORE) and $(NOTEBOOK_IGNORE_FILES)"
endif

# Disable the following pylint checks in ruff for notebooks:
# 	missing-module-docstring
# 	invalid-name
NOTEBOOK_SWITCHES_FOR_RUFF ?= --ignore=D100,N802
PYTHON_SWITCHES_FOR_RUFF ?=

PYTHON_LINT_TARGET ?= $(PYTHON_SRC) tests/## Paths containing python to be formatted and linted

NOTEBOOK_LINT_TARGET ?= notebooks/*.ipynb## Top-level active notebooks to be formatted and linted


.PHONY: python-format python-pre-format python-do-format python-post-format \
	python-lint python-pre-lint python-do-lint python-post-lint \
	python-test python-pre-test python-do-test python-post-test


python-pre-format:

python-post-format:

python-do-format:
	## 1. Organize imports (Replaces isort)
	$(PYTHON_RUNNER) ruff check --fix-only $(PYTHON_LINT_TARGET)
	## 2. Format code (Replaces black)
	$(PYTHON_RUNNER) ruff format --line-length=$(PYTHON_LINE_LENGTH) $(PYTHON_LINT_TARGET)

## TARGET: python-format
## SYNOPSIS: make python-format
## HOOKS: python-pre-format, python-post-format
## VARS:
##       PYTHON_RUNNER=<python executor> - defaults to empty, but could pass something like python -m
##       PYTHON_LINT_TARGET=<file or directory path to Python code> - default 'src/ tests/'
##		 PYTHON_LINE_LENGTH=<line length> - defaults to 79, set it once and all linters will use this value
##
##  Reformat project Python code in the given directories/files using ruff.

python-format: python-pre-format python-do-format python-post-format  ## format the Python code

python-pre-lint:

python-post-lint:

python-do-lint:
	@mkdir -p build/reports;
	## 1. Run Linter with correct format and pipefail to catch errors
	$(PYTHON_RUNNER) ruff check $(PYTHON_LINT_TARGET) $(PYTHON_SWITCHES_FOR_RUFF) \
		--line-length=$(PYTHON_LINE_LENGTH) \
		--output-format=$$( [ "$$GITHUB_ACTIONS" = "true" ] && echo "github" || echo "grouped" )
	## 2. Generate JUnit Report for CI
	$(PYTHON_RUNNER) ruff check $(PYTHON_LINT_TARGET) $(PYTHON_SWITCHES_FOR_RUFF) \
		--line-length=$(PYTHON_LINE_LENGTH) \
		--output-format=junit \
		--output-file=build/reports/linting-python.xml
	## 3. Check Formatting
	$(PYTHON_RUNNER) ruff format --check $(PYTHON_LINT_TARGET) \
		--line-length=$(PYTHON_LINE_LENGTH)
	## 4. Type checking
	$(PYTHON_RUNNER) python -m mypy $(PYTHON_LINT_TARGET) --ignore-missing-imports


## TARGET: python-lint
## SYNOPSIS: make python-lint
## HOOKS: python-pre-lint, python-post-lint
## VARS:
##       PYTHON_RUNNER=<python executor> - defaults to empty, but could pass something like python -m
##       PYTHON_LINT_TARGET=<file or directory path to Python code> - default 'src/ tests/'
##		 PYTHON_LINE_LENGTH=<line length> - defaults to 79, set it once and all linters will use this value
##       PYTHON_SWITCHES_FOR_RUFF=<additional switches to pass to ruff>
##
##  Lint check project Python code in the given directories/files using ruff.

python-lint: python-pre-lint python-do-lint python-post-lint  ## lint the Python code

python-pre-test:

python-post-test:

python-do-test:
	@$(PYTHON_RUNNER) pytest --version -c /dev/null
	@mkdir -p build
	$(PYTHON_VARS_BEFORE_PYTEST) $(PYTHON_RUNNER) pytest \
		$(PYTHON_VARS_AFTER_PYTEST) \
		-m "not integration" \
	 	--cov=$(PYTHON_SRC) \
		--cov-report=term-missing \
		--cov-report html:build/reports/code-coverage \
		--cov-report xml:build/reports/code-coverage.xml \
		--junitxml=build/reports/unit-tests.xml \
		$(PYTHON_TEST_FILE)

## TARGET: python-test
## SYNOPSIS: make python-test
## HOOKS: python-pre-test, python-post-test
## VARS:
##       PYTHON_RUNNER=<python executor> - defaults to empty, but could pass something like python -m
##       PYTHON_TEST_FILE=<paths and/or files for testing> - defaults to tests/unit/
##       PYTHON_VARS_BEFORE_PYTEST=<environment variables defined before pytest in run> - default empty
##       PYTHON_VARS_AFTER_PYTEST=<additional switches passed to pytest> - default empty
##
##  Run pytest against the tests defined in ./tests.  By default, this will pickup any pytest
##  specific configuration set in pytest.ini, setup.cfg etc. located in ./tests

python-test: python-pre-test python-do-test python-post-test  ## test the Python package

python-do-test-integration:
	@$(PYTHON_RUNNER) pytest --version -c /dev/null
	$(PYTHON_RUNNER) pytest \
		-m integration \
		tests

python-test-integration: python-do-test-integration

## TARGET: python-test-integration
## SYNOPSIS: make python-test-integration
## HOOKS: 
## VARS:
##
##  Run pytest against the integration tests defined in ./tests with 
##  "integration" markers.


notebook-pre-format:

notebook-post-format:

notebook-do-format:
	## 1. Organize imports (Replaces isort)
	$(PYTHON_RUNNER) ruff check --fix-only $(NOTEBOOK_LINT_TARGET)
	## 2. Format code (Replaces black)
	$(PYTHON_RUNNER) ruff format --line-length=$(PYTHON_LINE_LENGTH) $(NOTEBOOK_LINT_TARGET)


## TARGET: notebook-format
## SYNOPSIS: make notebook-format
## HOOKS: notebook-pre-format, notebook-post-format
## VARS:
##       PYTHON_RUNNER=<python executor> - defaults to empty, but could pass something like python -m
##       NOTEBOOK_LINT_TARGET=<file or directory path to Python code> - defaults to . (all notebooks in the repo)
##		 PYTHON_LINE_LENGTH=<line length> - defaults to 79, set it once and all linters will use this value
##
##  Reformat Jupyter notebooks in the given directories/files using ruff.

notebook-format: notebook-pre-format notebook-do-format notebook-do-format


notebook-pre-lint:

notebook-post-lint:
	@. $(PYTHON_SUPPORT) ; \
		checkNotebookDir

notebook-do-lint:
	@mkdir -p build/reports;
	## 1. Run Linter with correct format and pipefail to catch errors
	$(PYTHON_RUNNER) ruff check $(NOTEBOOK_LINT_TARGET) $(NOTEBOOK_SWITCHES_FOR_RUFF) \
		--line-length=$(PYTHON_LINE_LENGTH) \
		--output-format=$$( [ "$$GITHUB_ACTIONS" = "true" ] && echo "github" || echo "grouped" )
	## 2. Generate JUnit Report for CI
	$(PYTHON_RUNNER) ruff check $(NOTEBOOK_LINT_TARGET) $(NOTEBOOK_SWITCHES_FOR_RUFF) \
		--line-length=$(PYTHON_LINE_LENGTH) \
		--output-format=junit \
		--output-file=build/reports/linting-notebooks.xml
	## 3. Check Formatting
	$(PYTHON_RUNNER) ruff format --check $(NOTEBOOK_LINT_TARGET) \
		--line-length=$(PYTHON_LINE_LENGTH)
	## 4. Type checking
	$(PYTHON_RUNNER) python -m nbqa mypy $(NOTEBOOK_LINT_TARGET) --ignore-missing-imports

## TARGET: notebook-lint
## SYNOPSIS: make notebook-lint
## HOOKS: notebook-pre-lint, notebook-post-lint
## VARS:
##       PYTHON_RUNNER=<python executor> - defaults to empty, but could pass something like python -m
##       NOTEBOOK_LINT_TARGET=<file or directory path to notebooks> - defaults to . (all notebooks in the repo)
##		 PYTHON_LINE_LENGTH=<line length> - defaults to 79, set it once and all linters will use this value
##       NOTEBOOK_SWITCHES_FOR_RUFF=<additional switches to pass to ruff>
##
##  Lint check Jupyter notebooks in the given directories/files using ruff.

notebook-lint: notebook-pre-lint notebook-do-lint notebook-post-lint ## Lint Jupyter notebooks


notebook-pre-test:

notebook-post-test:
	@. $(PYTHON_SUPPORT) ; \
		checkNotebookDir

notebook-do-test:
	@$(PYTHON_RUNNER) pytest --version -c /dev/null
	@mkdir -p build
	$(PYTHON_VARS_BEFORE_PYTEST) $(PYTHON_RUNNER) pytest --nbmake $(PYTHON_SWITCHES_FOR_NBMAKE) $(PYTHON_TEST_FOLDER_NBMAKE)

## TARGET: notebook-test
## SYNOPSIS: make notebook-test
## HOOKS: notebook-pre-test, notebook-post-test
## VARS:
##       PYTHON_RUNNER=<python executor> - defaults to empty, but could pass something like python -m
##       PYTHON_TEST_FOLDER_NBMAKE - defaults to . (all notebooks in the repo)
##       PYTHON_VARS_BEFORE_PYTEST=<environment variables defined before pytest in run> - default empty
##       NOTEBOOK_IGNORE_FILES - Notebook files to ignore. Defaults to "not notebook.ipynb".
##       PYTHON_SWITCHES_FOR_NBMAKE - Includes test folder and files to ignore
##
##  Run pytest --nbmake  against the notebooks defined in PYTHON_TEST_FOLDER_NBMAKE.  By default, this will pickup any jupyter notebooks

notebook-test: notebook-pre-test notebook-do-test notebook-post-test  ## test the Jupyter Notebook package


# end of switch to suppress targets for help
endif
endif