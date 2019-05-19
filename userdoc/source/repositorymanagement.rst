Repository Management
=====================

Molior creates for each project version two aptly repositories. One for release builds which is the 'stable' repo and another one for the 'unstable' (=ci) builds.

.. code:: python

    /../repos/myproject/1.0.0/dists/stable
    /../repos/myproject/1.0.0/dists/unstable

This gives us also two apt sources urls for each project version:

.. code:: python

    deb http://aptly.server/stretch/9.4/repos/myproject/1.0.0 stable main
    deb http://aptly.server/stretch/9.4/repos/myproject/1.0.0 unstable main


Notice: Currently only the component ``main`` is supported.
