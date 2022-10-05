.. highlight:: shell

============
Contributing
============

Contributions are welcome, and they are greatly appreciated! Every little bit
helps, and credit will always be given.

You can contribute in many ways:

Types of Contributions
----------------------

Report Bugs
~~~~~~~~~~~

Report bugs at https://github.com/vintasoftware/django-virtual-models/issues

Before reporting a bug, please double-check the requirements of this project:
https://github.com/vintasoftware/django-virtual-models/blob/main/README.md#requirements

If you think you really found a bug, please create a GitHub issue and use the "Bug report" template.

Fix Bugs
~~~~~~~~

Look through the GitHub issues for bugs. Anything tagged with "bug" and "help wanted" is open
to whoever wants to implement it. Please comment on the issue saying you're working in a solution.

Implement Features
~~~~~~~~~~~~~~~~~~

Look through the GitHub issues for features. Anything tagged with "enhancement" and "help wanted"
is open to whoever wants to implement it.
Please comment on the issue saying you're working in a solution.

Write Documentation
~~~~~~~~~~~~~~~~~~~

django-virtual-models could always use more documentation, whether as part of
the official django-virtual-models docs, in docstrings,
or even on the web in blog posts, articles, and such.

Submit Feedback
~~~~~~~~~~~~~~~

If you have a suggestion, concern, or want to propose a feature,
please create a GitHub issue and use the "New feature" template.

Get Started!
------------

Ready to contribute? Please read our Code of Conduct:
https://github.com/vintasoftware/django-virtual-models/blob/main/CODE_OF_CONDUCT.md

Now, here's how to set up `django-virtual-models` for local development.

1. Fork the `django-virtual-models` repo on GitHub.
2. Clone your fork locally::

    $ git clone git@github.com:your_name_here/django-virtual-models.git

3. Install your local copy into a virtualenv. Assuming you have virtualenvwrapper installed,
this is how you set up your fork for local development::

    $ mkvirtualenv django-virtual-models
    $ cd django-virtual-models/

4. Install the project and the dev requirements::

    $ pip install -e .[doc,dev,test]

5. Install pre-commit checks::

    $ pre-commit install

6. Create a branch for local development::

    $ git checkout -b name-of-your-bugfix-or-feature

   Now you can make your changes locally.

7. When you're done making changes, check that your changes pass tests,
including testing other Python and Django versions with tox::

    $ pytest
    $ pytest example
    $ tox

8. Commit your changes and push your branch to GitHub::

    $ git add .
    $ git commit -m "Your detailed description of your changes."
    $ git push origin name-of-your-bugfix-or-feature

9. Submit a Pull Request through the GitHub website.

Pull Request Guidelines
-----------------------

Before you submit a Pull Request, check that it meets these guidelines:

1. The Pull Request should include tests.
2. If the Pull Request adds functionality, the docs should be updated.
3. The CI should pass.
