# ValSKA

**An open-source, reproducible, flexible, and extensible validation toolkit for SKA and precursor science workflows, including 21-cm power-spectrum studies and primary-beam perturbation analyses.**
[![CI Pipeline](https://github.com/uksrc/ValSKA/actions/workflows/valska-actions.yml/badge.svg)](https://github.com/uksrc/ValSKA/actions/workflows/valska-actions.yml)

[![Docs Status](https://readthedocs.org/projects/valska/badge/?version=latest)](https://valska.readthedocs.io/en/latest/)

---

## Overview

ValSKA provides science-validation tooling for SKA and precursor instrument workflows, including Bayesian case studies built around the Hydrogen Epoch of Reionization Array (HERA) and the **BayesEoR** modelling framework.

The focus of this repository is **validation tooling**: enabling controlled, inspectable, and reproducible studies of how modelling assumptions propagate through end-to-end science pipelines. The current flagship workflow studies how uncertainty in the primary-beam full width at half maximum (FWHM) affects 21-cm power-spectrum inference.

This repository is developed as part of the UK Square Kilometre Array Regional Centre (UKSRC) science-validation effort.

For Python imports, use `valska` as the canonical package name. The legacy
`valska_hera_beam` import path is still supported temporarily as a deprecated
compatibility shim while downstream code migrates.

---

## Features

- **Bayesian 21-cm inference**
  Uses BayesEoR to perform joint Bayesian modelling of spectrally smooth foreground emission and a stochastic 21-cm signal from the Epoch of Reionization.

- **Instrumental sensitivity validation**
  Quantifies the robustness of inferred 21-cm power spectra to controlled perturbations in the assumed primary-beam FWHM.

- **Reproducible HPC workflows**
  Explicit separation of run preparation, CPU precompute, and GPU inference stages enables resumable, auditable, and HPC-appropriate execution.

---

## Contents

ValSKA currently includes:

- Validation results from **BaNTER** (Bayesian Null-Test Evidence Ratio) analyses
- BayesEoR chain files from mock HERA foreground-only and foreground-plus-signal datasets
- Full provenance records for all validation runs
- Command-line tooling for preparing, submitting, and managing ensembles of BayesEoR runs

---

## Installation

General guidance:

- Clone the repository
- All dependencies can be installed with `conda` using the included `valska_env_base.yaml` and `valska_env_gpu.yaml` files
- In `valska_env_gpu.yaml`, select `cuda` or `cudatoolkit` depending on your system (e.g. Azimuth vs Galahad).
```
conda env create -f valska_env_base.yaml
conda activate valska
conda env update -f valska_env_gpu.yaml
```
 
**Note:**
This repository provides *validation tooling and job orchestration*.
It does **not** automatically create conda environments, clone BayesEoR, or manage HPC accounts.

---

## BayesEoR validation workflow (high-level)

This repository supports **reproducible, sweep-based validation studies** in which BayesEoR analyses are repeated across multiple controlled FWHM perturbations as one of the current ValSKA workflows.

At a high level, the workflow is:

- Define a validation sweep over beam FWHM
- Prepare self-contained BayesEoR run directories
- Submit CPU and GPU stages with explicit dependencies
- Inspect, resume, or extend runs as needed

The recommended user interface for this workflow is the `valska-bayeseor-sweep` command, which builds on lower-level `prepare` and `submit` tooling.

For post-processing, `valska-bayeseor-report` can be run on any existing sweep directory to generate summary tables and evidence comparison plots retroactively.

**Detailed usage examples, expected outputs, and recovery patterns are documented separately.**

---

## Documentation

Documentation is hosted on [ReadTheDocs](https://valska.readthedocs.io/en/latest/).

Detailed command-line examples and workflow patterns are provided in:

- [BayesEoR CLI examples](https://valska.readthedocs.io/en/latest/workflows/bayeseor_cli_examples.html)
- [BayesEoR reporting workflows](https://valska.readthedocs.io/en/latest/workflows/bayeseor_reporting.html)
- [BayesEoR operations CLI](https://valska.readthedocs.io/en/latest/workflows/bayeseor_operations.html)

That document is the primary reference for:
- Preparing validation sweeps
- Submitting CPU and GPU stages
- Partial submission and recovery
- Resubmission after walltime
- Inspecting manifests and job records

## Testing

### Unit Tests

For comprehensive unit testing instructions, see the [Testing Guide](https://valska.readthedocs.io/en/latest/testing.html).

(beam-metrics)=
### Beam Metrics

The `beam_metrics` module contains methods to check simulated UV data (`uvh5` format) to verify that the actual beam size in the data matches the simulation configuration parameters. Note: it works for a simulation of a single source that passes through zenith at the telescope latitude. It fits a Gaussian or Airy beam to the Stokes I amplitude and checks its variation with frequency. The beam metrics checks can be run as follows:

```
import valska.beam_metrics as beam_metrics

bm = beam_metrics.BeamMetrics("<uvh5_filename>", "<pyuvsim_config.yaml>", template_dir="<template_dir>")
bm.check_beam(show=True)
```

To save the diagnostic figure for batch validation, pass a file path and
disable interactive display:

```
bm.check_beam(save_path="beam_metrics.png", show=False)
```

- `uvh5_filename` is the path and filename to the simulated dataset
- `pyuvsim_config.yaml` is the main pyuvsim configuration file (which specifies paths to telescope configuration and catalogue)
- `template_dir` is an optional template directory containing the specified telescope configuration and catalogue files

## Contributing

ValSKA is an open source project and contributions to this package in any form are very welcome (e.g. new features, feature requests, bug reports, documentation fixes). Please make such contributions in the form of an issue and/or pull request.

When creating a pull request, please use the provided pull request template which includes a checklist to ensure:
- Self-review of code
- Local tests pass (`make python-test` and `make notebook-test`)
- Relevant documentation is updated

In order to enforce CI checks on pull requests, branch protection rules are in place on the `main` branch to:

- Require status checks to pass before merging
- Require pull request reviews before merging

We use pre-commit hooks to ensure code quality and consistency - please see the [Guide to Contributing](https://valska.readthedocs.io/en/latest/contributing.html) for further information about setting up and using pre-commit.


For any additional questions or comments, please contact one of the UKSRC science validation tooling team:
 - Peter Sims (PO) - ps550 [at] cam.ac.uk
 - Tianyue Chen (SM) - tianyue.chen [at] manchester.ac.uk
 - Quentin Gueuning - qdg20 [at] cam.ac.uk
 - Ed Polehampton - edward.polehampton [at] stfc.ac.uk
 - Vlad Stolyarov - vs237 [at] cam.ac.uk
