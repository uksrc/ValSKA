# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here.
import sys
from pathlib import Path

# sys.path.insert(0, str(Path('..', 'src').resolve()))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]) + "/src")

# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "ValSKA"
copyright = "2025, P.Sims, Q.Gueuning, E.Polehampton, T.Chen, V.Stolyarov"
author = "P.Sims, Q.Gueuning, E.Polehampton, T.Chen, V.Stolyarov"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.duration",
    "sphinx.ext.doctest",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "myst_parser",
]

autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "private-members": True,
}

# This uses both the class docstring and the
# __init__ docstring for class documentation
autoclass_content = "both"

autodoc_mock_imports = [
    "bayeseor",
    "IPython",
]

templates_path = ["_templates"]
exclude_patterns = []

myst_heading_anchors = 5  # to avoid uneeded warnings, cf.
# https://github.com/executablebooks/MyST-Parser/issues/885

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "sphinx_rtd_theme"
# This would be the location for custom CSS or static assets
html_static_path = []
