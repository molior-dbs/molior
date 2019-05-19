FAQ
===

**How can I fix a mistake I made during project, projectversion or source repo creation/addition?**

Currently it is not possible to edit projects, versions or source repositories. Please contact an administrator
to fix it manually for you.

**Why do I have to snapshot/lock a project version?**

Project versions can be locked to ensure that no further changes can be done to the project version in the future.
This feature is intended to be used for production releases of the whole project version.

**Molior does not start building my packages, how to fix?**

Here's a quick check list if molior does not start building your packages after creating a release:

    - Does the molior user have read access to your repository?
    - Does your latest git tag have the correct format? (e.g. v1.0.0, v1.2.3-alpha1, v2.0.0-rc5)
    - Does your repository contain a valid ``debian/molior.yml`` file which matches the configured project version on the ui?
    - Has your git tag been properly pushed to the remote?
    - Is your changelog file formatted correctly? (execute ‘dpkg-parsechangelog’ in your repository to check.)
    - Have you configured the web hook to trigger molior correctly?

If none of those hints help please contact an administrator.
