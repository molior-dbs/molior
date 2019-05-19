Development Environment
=======================

Make sure you have checked out the following repositories in your work dir:

    - **molior**
    - **molior-web**
    - **aptlydeb**

Setting up molior vagrant box
-----------------------------

To test molior you can use the provided vagrant scripts, which set up a
virtual machine and install the local version of all molior packages.

::

    cd vagrant
    vagrant up
    # follow the instructions


Rebuild molior
--------------

The repositories listed above are all mounted into the vagrant box so locally modified packages can easily be built and installed inside the box:

::
    # builds & installs all packages
    build

Or build individual packages:

::
    # build molior-server
    build molior # or molior-web, aptlydeb
