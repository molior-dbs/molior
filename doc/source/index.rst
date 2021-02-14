.. molior documentation master file, created by
   sphinx-quickstart on Thu Mar 31 14:33:07 2016.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

.. image:: ../img/moliorlogo_large.png

Welcome to molior's documentation!
==================================

Molior is an automagic debian builder, which pulls git repos if there’s a new release (git tag like v0.0.2), builds them and publishes/serves the built debian packages through aptly.

Contents:

.. toctree::
    :maxdepth: 2

    components.rst
    database.rst
    publishing.rst
    statemachines.rst
    buildnodes.rst
    logging.rst
    molior/modules.rst


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
