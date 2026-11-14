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

All other ``key=value`` pairs are passed to ``connect()`` unchanged.
With ``firebirdsql`` a ``timeout=5`` entry is recommended: it bounds
socket connect and read waits, so a hanging (as opposed to refusing)
Firebird host cannot block a Zope worker thread for the full OS TCP
timeout.  ``firebird-driver`` does not accept a ``timeout`` key.

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

Multi-statement batches (Z SQL Methods using ``<dtml-var
sql_delimiter>``) also differ on partial failure: ``firebirdsql`` runs
with autocommit, so statements before a failing one remain committed;
``firebird-driver`` executes the whole batch in a single transaction
and rolls it back on error, undoing the earlier statements.

Connection-Loss Retries
-----------------------

When a connection is lost mid-query, FirebirdDA reconnects and retries
the query only if every statement in the batch starts with ``SELECT``.
Anything else fails immediately, because the server may already have
committed the write before the connection dropped -- replaying it could
execute the write twice.

Note the limit of this lexical check: a ``SELECT`` with server-side
effects -- ``SELECT GEN_ID(SEQ, 1) FROM RDB$DATABASE`` or a selectable
stored procedure that writes -- passes the gate and may be executed a
second time after a reconnect.

ConnectionIdleTimeout
---------------------

Leave ``ConnectionIdleTimeout`` unset in ``firebird.conf`` and
``databases.conf``.  The engine default of 0 disables the idle timer.

FirebirdDA keeps one connection open for the life of the Zope worker.
Between requests that attachment is idle on purpose.  A short timeout
closes it.  The next request then receives ``isc_att_shutdown`` with
the secondary error ``isc_att_shut_idle``.  A pure ``SELECT`` is
retried once.  An ``INSERT``, ``UPDATE``, ``DELETE`` or ``WITH`` is
not retried, so that request fails.  The following request opens a
new connection.

A timeout of several hours still reclaims an attachment whose TCP
close the server never noticed, and it can fail the first write after
a long quiet period.  Leave the setting unset to avoid that.

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

