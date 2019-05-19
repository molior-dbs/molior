Mirrors
=======

To provide a fully reproducible build environment and independence from internet resources molior allows mirroring of external debian repositories. The two different types of mirrors are described below.

Base Mirrors
------------
A base mirror provides a full installable operating system such as debian or ubuntu.

Framework Mirrors
-----------------
Framework mirrors are usually smaller in size than base mirrors and only contain libraries, frameworks and/or tools.
These mirrors are used if a specific version of a package is not available in any of the base mirrors for example.

Examples: Mono, Docker, dotnet.core

Important: Framework mirrors can only be created on top of an existing base mirror.
