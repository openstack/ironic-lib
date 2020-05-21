# -*- coding: utf-8 -*-
#

# -- General configuration ----------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom ones.
extensions = [
              'sphinx.ext.viewcode',
              'openstackdocstheme',
              'sphinxcontrib.apidoc'
              ]

wsme_protocols = ['restjson']

# autodoc generation is a bit aggressive and a nuisance when doing heavy
# text edit cycles.
# execute "export SPHINX_DEBUG=1" in your terminal to disable

# Add any paths that contain templates here, relative to this directory.
templates_path = ['_templates']

# The suffix of source filenames.
source_suffix = '.rst'

# The master toctree document.
master_doc = 'index'

# General information about the project.
copyright = u'OpenStack Foundation'

# A list of ignored prefixes for module index sorting.
modindex_common_prefix = ['ironic_lib']

# If true, '()' will be appended to :func: etc. cross-reference text.
add_function_parentheses = True

# If true, the current module name will be prepended to all description
# unit titles (such as .. function::).
add_module_names = True

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = 'native'

# -- sphinxcontrib.apidoc configuration --------------------------------------

apidoc_module_dir = '../../ironic_lib'
apidoc_output_dir = 'reference/api'
apidoc_excluded_paths = [
    'tests',
]

# -- Options for HTML output --------------------------------------------------

# The theme to use for HTML and HTML Help pages.  Major themes that come with
# Sphinx are currently 'default' and 'sphinxdoc'.
#html_theme_path = ["."]
#html_static_path = ['_static']

html_theme = 'openstackdocs'

# openstackdocstheme options
openstackdocs_repo_name = 'openstack/ironic-lib'
openstackdocs_pdf_link = True
openstackdocs_use_storyboard = True

# Output file base name for HTML help builder.
htmlhelp_basename = 'ironic-libdoc'

latex_use_xindy = False

# Grouping the document tree into LaTeX files. List of tuples
# (source start file, target name, title, author, documentclass
# [howto/manual]).
latex_documents = [
    (
        'index',
        'doc-ironic-lib.tex',
        u'Ironic Lib Documentation',
        u'OpenStack Foundation',
        'manual'
    ),
]
