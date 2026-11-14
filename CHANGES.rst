Changelog
=========

0.8.0 (unreleased)
------------------

Python 3.11+ modernisation
~~~~~~~~~~~~~~~~~~~~~~~~~~
- Require Python 3.11 or newer; target Zope 5.
- Code style: f-strings, ``contextlib.suppress``, proper exception
  chaining, remove unused imports and dead code.
- Unify docstring/comment style across the codebase.
- Extract ISQL meta command translation into a dedicated ``isql_meta``
  module.

Driver support
~~~~~~~~~~~~~~
- Add support for ``firebird-driver`` as alternative to ``firebirdsql``.
- Automatic DSN format conversion between drivers.
- Fail fast on an unsupported ``FIREBIRDDA_DRIVER`` value.
- Keep the leading slash of an absolute path when converting a
  ``host:port/path`` DSN for ``firebird-driver`` -- it previously turned
  into a relative path, so the server looked for the database in the
  wrong place.
- Pass a DSN without a host part (a bare local path or alias) through
  unchanged instead of raising, so ``firebird-driver`` attaches to it
  locally.
- Materialise BLOB values larger than 64 KiB before the per-query commit
  under ``firebird-driver``, which otherwise handed back closed
  ``BlobReader`` streams.

Reliability
~~~~~~~~~~~
- Simplify connection retry logic and improve error resilience.
- Raise ``OperationalError`` when retries are exhausted instead of
  silently failing.
- Guarantee cursor cleanup by splitting ``query()`` per driver.
- Retry a lost connection only for pure ``SELECT`` batches, under **both**
  drivers. A batch that may write (INSERT/UPDATE/DELETE/MERGE/EXECUTE,
  DDL, or a ``WITH`` CTE) is no longer replayed after a drop, because the
  commit may already have reached the server -- replaying could execute
  the write twice. **Behaviour change for the firebirdsql path**, which
  since 0.7.1 replayed whole batches on transient errors (autocommit per
  statement makes a duplicate even likelier there): an unattended write
  job that used to survive a Firebird restart via retry now fails visibly
  instead of risking a silent duplicate. SELECTs keep the full retry
  resilience. The dead connection is closed before the error is raised,
  so the next request reconnects instead of hitting it again.
- Also catch ``InterfaceError`` in the ``firebird-driver`` retry path --
  it is not a ``DatabaseError`` subclass, so it previously bypassed both
  retry and error wrapping.
- Reopen a firebirdsql connection on the next query after an explicit
  ``close()`` (e.g. the ZMI "Close Connection" button) instead of
  failing every following request. The reconnect now happens inside the
  retry loop's ``try``, so a failed reopen is caught and retried rather
  than escaping raw and skipping the remaining retries.
- Trust a ``firebird-driver`` status vector when one is present rather
  than also matching on the message text, so an intentional database
  shutdown is no longer misclassified as a transient connection loss.
- Catch every ``OSError`` in the firebirdsql retry loop, not only
  ``ConnectionError``/``TimeoutError`` -- a DNS failure (``gaierror``)
  or an unreachable host/network (``EHOSTUNREACH``/``ENETUNREACH``)
  during a reconnect no longer escapes raw, skipping the remaining
  retries and the error wrapping.
- Use the inherited ``connect()`` via a ``factory()`` hook instead of a
  minimal override: the previous connection is closed before a new one
  is opened (no leaked server attachments on Properties "Save
  changes"), connect-time driver errors are wrapped in ``BadRequest``
  (a raw ``firebird-driver`` exception would crash DTML error
  rendering), and ``_v_connected`` is maintained again, so the
  inherited ``title_and_id()`` -- used by the Z SQL Method connection
  dropdown -- no longer reports a connected database as "not
  connected".
- Log errors from closing a connection instead of discarding them
  silently -- a failing detach can leave the server-side attachment
  open, which matters when chasing "too many open handles".
- Under ``firebird-driver``, ``close()`` never calls native
  ``YAttachment::detach``, neither via ``conn.close()`` nor from a
  later ``Connection.__del__``.  ``libfbclient`` raises SIGILL inside
  detach on a dead attachment and kills the Zope process; a ping
  immediately before detach is not a safe gate.  Every close nulls
  ``_att`` first and then does best-effort local cleanup only.
  A normal remote close still ends the server attachment: dropping
  the handle runs ``release()``, which sends ``op_detach`` and closes
  the socket.  Closing a healthy attachment this way does not consult
  ``ConnectionIdleTimeout``.  A configured timeout can still close an
  attachment that Zope keeps idle between requests.  Leaving the
  setting unset, the engine default of 0, does not.  An attachment
  can still linger only when the TCP session was already dead and the
  server does not notice the close.  ``firebirdsql`` still closes
  normally.
- Document that ``ConnectionIdleTimeout`` should stay unset.  The
  adapter keeps its connection for the life of the Zope worker.  A
  short timeout closes that attachment during a quiet period, and the
  next non-``SELECT`` request fails instead of being retried.
- Serialize ``open`` / ``close`` / ``query`` on a per-``DB`` ``RLock``
  so Waitress worker threads cannot overlap lifecycle operations on
  the same shared connection.
- On query failure under ``firebird-driver``, skip ``rollback()`` when
  the error is already a connection loss (the outer retry path
  abandons the handle; an extra native call on a dead attachment is
  useless).
- Treat GDS ``335544324`` (invalid database handle) and matching
  message markers as connection loss for reconnect / abandon.
- Reopen when the driver handle is already closed but still referenced
  (``conn.is_closed()``), so a stale ``self.conn`` does not fail queries
  with opaque ``TypeError``/``AttributeError`` instead of reconnecting.

Error reporting
~~~~~~~~~~~~~~~
- Show driver errors with SQLSTATE and SQLCODE, and -- for Manager
  callers -- the offending SQL, formatted for the Test tab.
- Escape error text at the display boundary, not in the driver layer:
  ``db.py`` raises plain-text exceptions carrying structured
  ``sql``/``sqlstate``/``sqlcode`` attributes, and the Connection's
  ``manage_test`` escapes them for the Test tab (whose
  ``connectionTestForm.dtml`` renders ``error_value`` without
  html_quote). The shared ``query()`` path -- Z SQL Methods, SiteErrorLog,
  the event log -- no longer shows HTML entities such as ``&#x27;`` or
  ``<br/>``.
- Preserve the original firebirdsql exception type (``IntegrityError``,
  ``ProgrammingError``, ...) on the shared path instead of collapsing
  every error to ``OperationalError``; only transient/connection errors
  are wrapped, so filesystem code and External Methods can still catch
  the specific type.
- Normalise Test-tab input to ``str`` so a query containing ``<``
  (e.g. ``WHERE x < 5``) no longer crashes as a ``TaintedString`` before
  reaching the database.
- Report the underlying error after exhausted firebirdsql retries. A
  broken pipe used to surface as just ``32`` (the errno) because the
  message was assembled after the exception was frozen.
- Catch ``firebird-driver``'s ``InterfaceError`` at the DA boundary
  (``QUERY_ERRORS``): it is a sibling of ``DatabaseError``, not a
  subclass, so it previously reached the Test tab unwrapped.
- Drop the meaningless ``SQLCODE: 0`` line from Test-tab errors --
  firebirdsql defaults ``sql_code`` to 0 (success) on every exception,
  including pure connection-loss errors.

ZMI enhancements
~~~~~~~~~~~~~~~~
- Add ISQL ``show`` meta commands in the Test tab: object lists
  (tables, views, procedures, functions, triggers, generators, domains,
  exceptions), ``show table NAME`` (columns),
  ``show procedure/view/trigger/function NAME`` (object source, rendered
  with whitespace preserved so it copies cleanly), plus ``show version``
  and ``show database``.
- Show connection status in the object listing.
- Include SQL snippet in error messages for Manager callers.
- Fix ``show database`` failing on the reserved word ``CURRENT_USER``
  used as a column alias (now aliased as ``USER_NAME``).
- Treat a ``NULL`` ``RDB$SYSTEM_FLAG`` as a user object in the ``show``
  object lists (``COALESCE``), matching isql -- databases migrated from
  InterBase/old Firebird versions could otherwise list user objects
  incompletely.
- Show the running FirebirdDA version in the connection's Properties
  tab, next to the driver. The version lives in
  ``Products.FirebirdDA.__version__`` (single source of truth;
  ``setup.py`` reads it from there), so the ZMI always shows the code
  that is actually imported -- unlike pip metadata, which for an
  editable install can lag behind.
- Modernise the Add and Properties forms to the Zope 4/5 Bootstrap ZMI
  layout (own ``<main class="container-fluid">``, form groups instead of
  the old table layout). This also removes the "Design Hints: This
  layout is still not updated to ZMI conventions of Zope 4" notice that
  the ZMI appends to legacy forms.

Security
~~~~~~~~
- Remove unused connection cache that held plaintext credentials.
- Restrict the SQL snippet in Test-tab errors to Manager callers, and
  check the Manager role in the connection's own context so a LOCAL
  (site-level) Manager role counts -- not only global ones, as a
  context-less ``has_role`` check would.
- Gate ISQL meta commands via the Test tab's ``Test Database
  Connections`` permission instead of a Manager-role check, translating
  in the Connection's ``manage_test`` (DA layer) rather than the shared
  ``query()`` path -- so Z SQL Methods are never affected.

0.7.1 (2024-01-04)
------------------
- Reopen connection on "too many handles" errors and fix
  ``OperationalError`` output. [044144c]
- Add connection retries in ``query()`` method. [8cd2b8b]

0.7.0 (2020-06-20)
------------------
- Port to Zope 4 and Python 3. [1e2033f]
- Refactoring of forms, classifiers and imports. [9c7af69, 0984739, c2f8eda,
  1e080d7]

0.6.x (2014)
------------
- Disable connection pool (do not reuse connections across requests).
  [3fefc46]
- Enable ``set_autocommit(True)``. [a2e57f5]
- Declare ``Products`` namespace package. [3ebe2f8]
- Add trove classifiers. [0c61502]

0.5.0 (2012-01)
---------------
- Initial release by Hajime Nakagami, forked from ``ZKinterbasdbDA 0.5.0``
  and switched to the ``firebirdsql`` driver. [77e9b51, d7f6336]
