FirebirdDA
==============

FirebirdDA https://github.com/nakagami/Products.FirebirdDA is Zope database
adapter for Interbase/Firebird.

Requirements
------------

- Python >= 3.11
- Zope 5

Installation
-----------------

buildout.cfg::

   eggs =
       ...
       Products.FirebirdDA

Driver Configuration
--------------------

FirebirdDA supports two Firebird Python drivers:

- ``firebirdsql`` (default, auto-detected)
- ``firebird-driver``

Set the ``FIREBIRDDA_DRIVER`` environment variable to select a driver
explicitly.  In a Zope deployment this is typically done in ``zope.conf``::

   <environment>
     FIREBIRDDA_DRIVER firebird-driver
   </environment>

If the variable is not set, FirebirdDA auto-detects: it tries to import
``firebirdsql`` first and falls back to ``firebird-driver``.

To use ``firebird-driver``, install it as an extra::

   pip install Products.FirebirdDA[firebird-driver]

Connection String
-----------------

The connection string uses space-separated ``key=value`` pairs::

   dsn=host:/path/to/database.fdb user=sysdba password=masterkey

The ``dsn``, ``user`` and ``password`` keys are passed directly to the
driver's ``connect()`` function.  When using ``firebird-driver``, the
DSN is automatically converted from ``firebirdsql`` format
(``host:/path``) to ``firebird-driver`` format (``host:path``).

Driver Differences
------------------

The two drivers differ in how they return fixed-length ``CHAR(n)``
values:

- ``firebirdsql`` strips trailing spaces from ``CHAR`` columns
  automatically (``xsqlvar.py``: ``SQL_TYPE_TEXT`` → ``rstrip()``).
- ``firebird-driver`` returns ``CHAR`` values padded to the declared
  column width, as delivered by the Firebird wire protocol.

When switching from ``firebirdsql`` to ``firebird-driver``, code that
compares or displays ``CHAR`` values may need explicit ``rstrip()``
calls, or the column can be migrated from ``CHAR(n)`` to
``VARCHAR(n)``.

Test Tab
--------

The ZMI Test tab supports ISQL-style meta commands (requires the
Test Database Connections permission):

- ``show tables`` — list all user tables
- ``show table NAME`` — show columns of a table
- ``show views`` — list all user views
- ``show view NAME`` — show the view source
- ``show procedures`` — list all stored procedures
- ``show procedure NAME`` — show the procedure source
- ``show functions`` — list all user functions
- ``show function NAME`` — show the function source (Firebird 3+)
- ``show triggers`` — list all user triggers
- ``show trigger NAME`` — show the trigger source
- ``show generators`` — list all generators (sequences)
- ``show domains`` — list all user domains
- ``show exceptions`` — list all user exceptions
- ``show version`` — show Firebird engine version
- ``show database`` — show database name, engine version and current user

