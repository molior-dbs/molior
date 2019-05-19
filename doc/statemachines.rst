State Machines
==============

Build State Machine
~~~~~~~~~~~~~~~~~~~

A build can run through the following states:

- **new** *the build task was created*
- **needs_build** *the build is ready to be started (src package is ready)*
- **scheduled** *the build has been added to the build queue*
- **building** *the build has started*
- **build_failed** *the build has failed*
- **needs_publish** *the build has finished successfully and is now ready to be published*
- **publishing** *molior is publishing the build output*
- **publish_failed** *publishing of the build output has failed*
- **successful** *the build has been published successfully*


.. image:: images/buildstatemachine.png


Source Repository State Machine
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Sourcerepositories can have one of the following states:

- **new** *the repository has been newly added*
- **cloning** *molior is cloning the repository*
- **ready** *the repository is ready to be used*
- **busy** *the repository is currently busy/locked*
- **error** *cloning or pulling of the repository has failed*

.. image:: images/sourcerepostatemachine.png
