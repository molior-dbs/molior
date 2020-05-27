Database
========

Molior uses postgresql as a database. The connection string can be configured in the molior.yml file.
Per default unix authentication is used.

Connect to the Database
~~~~~~~~~~~~~~~~~~~~~~~

You can connect to the database with the following command:

.. code:: sh

    sudo -u postgres psql molior

Model
~~~~~

.. image:: images/database.png

Generate Database Schema
~~~~~~~~~~~~~~~~~~~~~~~~

To generate the database schema install the `postgresql-autodoc` tool:

.. code:: sh

    sudo apt-get install postgresql-autodoc
    sudo -u postgres postgresql_autodoc -d molior  # generates a molior.dia file

The dia file can now be viewed with the `dia` programm

.. code:: sh

    sudo apt install dia

Migrations
~~~~~~~~~~
To perform database upgrades/migrations a simple shell script with the incremented upgrade-number can be placed in
the pkgdata/molior-server/usr/share/molior/database/ folder.

Example:

pkgdata/molior-server/usr/share/molior/database/upgrade-17

.. code:: python

    #!/bin/sh

    psql molior <<EOF

    ALTER TABLE hook ADD COLUMN enabled BOOLEAN DEFAULT true;

    EOF
