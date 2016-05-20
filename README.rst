----------
ironic_lib
----------

Overview
--------

A common library to be used **exclusively** by projects under the `Ironic
governance <http://governance.openstack.org/reference/projects/ironic.html>`_.

Running Tests
-------------

To run tests in virtualenvs (preferred)::

  sudo pip install tox
  tox

To run tests in the current environment::

  sudo pip install -r requirements.txt
  nosetests

