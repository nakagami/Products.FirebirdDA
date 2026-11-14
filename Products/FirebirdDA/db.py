##############################################################################
#
# Copyright (c) 2001 Zope Corporation and Contributors. All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.0 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE
#
##############################################################################
import contextlib
import datetime
import decimal
import os
import re
import signal
import threading
import time
from logging import getLogger

import Shared.DC.ZRDB.THUNK
from DateTime import DateTime

LOG = getLogger("FirebirdDA")

_DRIVER = os.environ.get("FIREBIRDDA_DRIVER", "").strip()

if not _DRIVER:
    try:
        import firebirdsql

        _DRIVER = "firebirdsql"
    except ImportError:
        _DRIVER = "firebird-driver"

if _DRIVER not in ("firebirdsql", "firebird-driver"):
    raise RuntimeError(
        f"Unsupported FIREBIRDDA_DRIVER {_DRIVER!r}; expected "
        "'firebirdsql' or 'firebird-driver'"
    )

if _DRIVER == "firebird-driver":
    import ctypes
    import ctypes.util

    from firebird.driver import DatabaseError as Error
    from firebird.driver import InterfaceError
    from firebird.driver import connect as _raw_connect
    from firebird.driver import tpb as _make_tpb
    from firebird.driver.core import BlobReader
    from firebird.driver.types import Isolation as _Isolation

    # libfbclient installs a C-level SIGTERM handler via sigaction()
    # on the first connect(), which swallows SIGTERM entirely.
    # Python's signal.getsignal() doesn't see it (it only tracks
    # Python-level handlers).  We save the OS-level handler before
    # connect() and restore it afterwards.
    _libc = ctypes.CDLL(ctypes.util.find_library("c") or None, use_errno=True)
    _sigaction = getattr(_libc, "sigaction", None)
    _sigaction_lock = threading.Lock()
    _SIGACTION_BUFFER_SIZE = 4096

    class _SigactionBuffer(ctypes.Union):
        _fields_ = [
            ("_alignment", ctypes.c_longdouble),
            ("_storage", ctypes.c_ubyte * _SIGACTION_BUFFER_SIZE),
        ]

    if _sigaction is not None:
        _sigaction.argtypes = (ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
        _sigaction.restype = ctypes.c_int

    def _call_sigaction(signum, act, oldact):
        if _sigaction is None:
            return False
        ctypes.set_errno(0)
        return _sigaction(signum, act, oldact) == 0

    def _connect(**kwargs):
        if _sigaction is None:
            return _raw_connect(**kwargs)

        saved = _SigactionBuffer()
        with _sigaction_lock:
            have_saved_handler = _call_sigaction(
                signal.SIGTERM, None, ctypes.byref(saved)
            )
            try:
                return _raw_connect(**kwargs)
            finally:
                if have_saved_handler:
                    _call_sigaction(signal.SIGTERM, ctypes.byref(saved), None)

    # GDS codes that indicate a lost or unusable connection where
    # a reconnect + retry is appropriate.
    RECONNECT_GDS_CODES: frozenset[int] = frozenset(
        {
            335544324,  # invalid database handle (no active connection)
            335544648,  # connection lost to database (pipe)
            335544721,  # network error
            335544722,  # Unable to complete network request
            335544726,  # Error reading data from the connection
            335544727,  # Error writing data to the connection
            335544741,  # connection lost to database
            335544761,  # too many open handles to database
            335544856,  # connection shutdown
        }
    )

    class OperationalError(Exception):
        """FirebirdDA operational error for the firebird-driver backend.

        Carries a PLAIN-TEXT message plus structured attributes
        (``sql``, ``sqlstate``, ``sqlcode``) so the DA layer can escape
        the message and, for Manager callers, append the SQL when it
        renders the ZMI Test tab.  db.py itself never HTML-escapes, so
        the shared query() path (Z SQL Methods, SiteErrorLog, event log)
        keeps clean plain text.

        Does NOT inherit from firebird.base.types.Error, because that class
        defines __getattr__ such that any unset attribute returns None —
        including __call__.  This crashes Zope's DocumentTemplate:
        safe_callable() checks hasattr(e, '__call__') (which returns True)
        and then calls e() on the exception instance.  Since e.__call__ is
        None, rendering <dtml-var error_value> in the ZMI Test tab crashes
        with "TypeError: 'NoneType' object is not callable" — without the
        actual Firebird error message ever reaching the user.

        The original firebird-driver exception is chained via __cause__.
        """

        sql = None
        sqlstate = None
        sqlcode = None

    # cursor.description type_code → ZRDB type character.
    # firebird-driver returns Python types (int, float, ...).
    def _zrdb_type(type_code, scale):
        if type_code is int:
            return "i"
        if type_code in (float, decimal.Decimal):
            return "n"
        if type_code in (datetime.date, datetime.datetime, datetime.time):
            return "d"
        return "s"

    def _materialize_row(row):
        """Read open BLOB streams in a fetched row into memory.

        firebird-driver returns BLOBs larger than ``stream_blob_threshold``
        (default 64 KiB) as ``BlobReader`` streams bound to the current
        transaction.  The commit that follows every query closes the
        cursor and with it those readers, so unless we read them now Zope
        would receive dead handles (rendered as ``<BlobReader ...>`` in
        DTML, an AttributeError on ``.read()``).  Smaller BLOBs already
        arrive materialised, so only ``BlobReader`` values are touched.
        """
        materialized = None
        for i, value in enumerate(row):
            if isinstance(value, BlobReader):
                if materialized is None:
                    materialized = list(row)
                materialized[i] = value.read()
        return tuple(materialized) if materialized is not None else row

elif _DRIVER == "firebirdsql":
    import firebirdsql
    from firebirdsql import OperationalError

    _connect = firebirdsql.connect
    Error = firebirdsql.Error
    # Subclass of firebirdsql.Error; bound here so QUERY_ERRORS below can
    # name it for both drivers.
    InterfaceError = firebirdsql.InterfaceError

    # cursor.description type_code → ZRDB type character.
    # firebirdsql returns ISC numeric type codes.
    _INTEGER_OR_DECIMAL_CODES = frozenset(
        {
            firebirdsql.SQL_TYPE_SHORT,  # 500
            firebirdsql.SQL_TYPE_LONG,  # 496
            firebirdsql.SQL_TYPE_INT64,  # 580
            firebirdsql.SQL_TYPE_INT128,  # 32752
        }
    )
    _FLOAT_CODES = frozenset(
        {
            firebirdsql.SQL_TYPE_FLOAT,  # 482
            firebirdsql.SQL_TYPE_DOUBLE,  # 480
            firebirdsql.SQL_TYPE_D_FLOAT,  # 530
            firebirdsql.SQL_TYPE_DEC64,  # 32760
            firebirdsql.SQL_TYPE_DEC128,  # 32762
            firebirdsql.SQL_TYPE_DEC_FIXED,  # 32758
        }
    )
    _DATE_CODES = frozenset(
        {
            firebirdsql.SQL_TYPE_DATE,  # 570
            firebirdsql.SQL_TYPE_TIME,  # 560
            firebirdsql.SQL_TYPE_TIMESTAMP,  # 510
            firebirdsql.SQL_TYPE_TIMESTAMP_TZ,  # 32754
            firebirdsql.SQL_TYPE_TIME_TZ,  # 32756
        }
    )

    def _zrdb_type(type_code, scale):
        if type_code in _INTEGER_OR_DECIMAL_CODES:
            return "i" if scale == 0 else "n"
        if type_code in _FLOAT_CODES:
            return "n"
        if type_code in _DATE_CODES:
            return "d"
        return "s"


# Exception types query() may raise, for callers (the DA layer) that want
# to catch driver errors narrowly -- without swallowing ZODB ConflictError
# or Retry, which must propagate. Error covers firebirdsql's original
# types passed through by P3-3 (IntegrityError, ProgrammingError, ...).
# firebird-driver's InterfaceError is a SIBLING of DatabaseError (both
# derive from firebird.base.types.Error), so it must be listed explicitly
# -- it reaches the DA layer raw from connect-time failures.
QUERY_ERRORS = (OperationalError, Error, InterfaceError)

_FIREBIRDSQL_RETRIES = 5
_FIREBIRD_DRIVER_RETRIES = 2
_FIREBIRD_DRIVER_RETRY_DELAY = 0.5

# Substring fallback markers (lower-cased) used to recognise
# connection-loss situations on exceptions that do not carry
# gds_codes (e.g. Python-level socket errors raised before the
# server could return a status vector).
_RECONNECT_MARKERS = (
    "broken pipe",
    "connection lost",
    "connection closed",
    "network error",
    "too many open handles",
    "shutdown",
    "invalid database handle",
    "no active connection",
    "error reading data",
    "error writing data",
)


def _is_firebird_driver_connection_lost(exc):
    """True if exc indicates a transient connection-loss situation
    where a reconnect + single retry makes sense."""
    # BrokenPipeError is a subclass of ConnectionError.
    if isinstance(exc, (ConnectionError, InterfaceError)):
        return True
    codes = getattr(exc, "gds_codes", None) or ()
    if codes:
        # A structured status vector is authoritative: trust it and do
        # NOT fall back to substring matching.  Otherwise a deliberately
        # shut-down database (gds 335544528/335544506, intentionally not
        # in RECONNECT_GDS_CODES) would be misread as transient just
        # because its message happens to contain "shutdown".
        return any(c in RECONNECT_GDS_CODES for c in codes)
    msg = str(exc).lower()
    return any(m in msg for m in _RECONNECT_MARKERS)


def _is_read_only_batch(query_string):
    """True if every statement in the batch is a plain ``SELECT``.

    Gates connection-loss retries: replaying a batch is only safe when it
    cannot have written anything, because the connection may have dropped
    *after* the server already committed (a stale ``rollback()`` on the
    dead handle cannot undo that).  We are deliberately conservative --
    the statement must start with ``SELECT`` after stripping; anything
    else (INSERT/UPDATE/DELETE/MERGE/EXECUTE, DDL, even a ``WITH`` CTE) is
    treated as potentially writing and is never retried.  Statements are
    split on the same NUL separator ``_execute_query`` uses.
    """
    statements = [s.strip() for s in query_string.split("\0")]
    statements = [s for s in statements if s]
    if not statements:
        return False
    return all(s.upper().startswith("SELECT") for s in statements)


def _exception_message(exc):
    """Return a defensive string message for exceptions with optional args."""
    args = getattr(exc, "args", None)
    msg = str(args[0] if args else exc)
    if not msg:
        msg = exc.__class__.__name__
    return msg


# Reasons shared by both driver paths, kept as PLAIN TEXT here; the DA
# layer (Connection.manage_test) escapes them for the Test tab.
_CONNECTION_LOST_NO_RETRY = (
    "Connection to Firebird lost; not retried because the batch is not a "
    "pure SELECT and replaying it could execute a write twice."
)
_CONNECTION_LOST_EXHAUSTED = (
    "Connection to Firebird lost; reconnect attempts exhausted."
)


def _base_error_text(exc):
    """Plain-text message for an exception.

    For OSError use str(): args[0] is the errno (e.g. 32 for a broken
    pipe), not a message.
    """
    if isinstance(exc, OSError):
        return str(exc)
    return _exception_message(exc)


def _carry_attrs(target, source, query_string):
    """Attach the offending SQL to target and copy whatever structured
    error attributes source carries.

    The attribute names differ per driver (firebird-driver: sqlstate /
    sqlcode; firebirdsql: sql_code) and gds_codes may be on either, so we
    copy every known name that is actually set.  The DA layer reads them
    back defensively when it formats the Test-tab error.
    """
    target.sql = query_string
    for name in ("sqlstate", "sqlcode", "sql_code", "gds_codes"):
        value = getattr(source, name, None)
        if value is not None:
            setattr(target, name, value)


def _operational_error(exc, query_string, prefix=None):
    """Build an OperationalError with a PLAIN-TEXT message plus the source
    exception's structured attributes and the offending SQL.

    ``OperationalError`` is the driver-appropriate class (the custom one
    for firebird-driver, firebirdsql's own otherwise).  For firebird-driver
    the wrap is also mandatory: the raw firebird.base.types.Error crashes
    DTML rendering (see the OperationalError docstring).
    """
    text = _base_error_text(exc)
    if prefix:
        text = f"{prefix}\n\n{text}"
    op = OperationalError(text)
    _carry_attrs(op, exc, query_string)
    return op


def _attach_sql(exc, query_string):
    """Attach the offending SQL to exc and return it for re-raising, so it
    keeps its original driver type (P3-3) while the DA layer can still
    show the SQL for Manager callers."""
    with contextlib.suppress(AttributeError, TypeError):
        exc.sql = query_string
    return exc


def fetchallmap(c):
    """Fetch all rows from cursor c as a list of {column_name: value} dicts.

    Not called anywhere in this product and not exposed to Zope.
    Kept for backward compatibility with third-party code that may
    import it directly.
    """
    desc = c.description
    r = []
    for row in c.fetchall():
        d = {}
        for col, value in zip(desc, row):
            key = str(col[0])
            try:
                d[key] = value.strip()
            except AttributeError:
                d[key] = value
        r.append(d)
    return r


def _convert_dsn(dsn):
    """Convert firebirdsql DSN format to firebird-driver format.

    firebirdsql:      host:port/path  host:/path
    firebird-driver:  host/port:path  host:path

    The path is interpreted exactly as firebirdsql's urlparse-based
    ``parse_dsn`` does, so both drivers attach to the same database:

    - The separator after the host/port is a single ``:`` (as in
      ``host:/path``); a ``/`` (as in ``host:3050/path``) belongs to the
      path and keeps its leading slash -- otherwise an absolute remote
      path silently becomes relative.
    - A single-component ``/alias`` collapses to ``alias``; deeper
      absolute paths keep their leading slash.

    A DSN without a recognisable ``host[:port]`` prefix (a bare local
    path like ``/var/db/app.fdb`` or an alias) is passed through
    unchanged; firebird-driver accepts such strings natively as a local
    attach, so converting -- or worse, raising -- would only break them.
    """
    # Consume a ':' separator, but only look ahead past a '/' one so the
    # leading slash stays with the path.
    m = re.match(r"^([^:/]+)(?::(\d+))?(?::|(?=/))(.+)$", dsn)
    if not m:
        return dsn
    host, port, path = m.groups()
    # Mirror firebirdsql: /alias (single component) -> alias.
    if path.startswith("/") and "/" not in path[1:]:
        path = path[1:]
    if port:
        return f"{host}/{port}:{path}"
    return f"{host}:{path}"


class DB(Shared.DC.ZRDB.THUNK.THUNKED_TM):
    database_error = Error
    opened = None

    conn = None

    def open(self):
        with self._lock:
            if self.conn is not None:
                # Nested close under the same RLock (re-entrant).
                self.close()
            self.conn = _connect(**self.conn_args)
            if _DRIVER == "firebirdsql":
                self.conn.set_autocommit(True)
            else:
                self.conn.main_transaction.default_tpb = _make_tpb(
                    _Isolation.READ_COMMITTED
                )
            self.opened = DateTime()

    def _ensure_open(self):
        """Reopen if we have no connection or a stale closed driver handle.

        ``firebird-driver`` can leave ``self.conn`` set while
        ``conn.is_closed()`` is already true (e.g. something else closed
        the handle, or a prior abandon nulled ``_att`` without clearing
        our reference).  Using that object then raises opaque
        ``TypeError``/``AttributeError`` instead of a connection-loss
        error, so the retry path never runs.  Detect and reopen first.

        Caller must hold ``self._lock`` (query/open paths do).
        """
        if self.conn is not None:
            is_closed = getattr(self.conn, "is_closed", None)
            if callable(is_closed) and is_closed():
                self.conn = None
                self.opened = None
        if self.opened is None:
            self.open()

    def close(self, *, abandon=False):
        """Release the Firebird connection held by this ``DB`` instance.

        Always clears ``self.conn`` / ``self.opened`` first so a second
        ``close()`` is a no-op and concurrent retry logic cannot see a
        half-closed handle.

        Under ``firebird-driver`` this method **never** calls native
        ``YAttachment::detach`` (via ``conn.close()`` or GC ``__del__``).
        ``libfbclient`` has been observed to raise **SIGILL** inside
        detach on dead or inconsistent attachments and kill the whole
        Zope process.  Even a successful ``ping()`` is not a reliable
        gate (TOCTOU / threads).  We always null ``_att`` first
        so ``Connection.__del__`` cannot detach, then best-effort
        Python-side cleanup.  A normal remote close still ends the
        server attachment: dropping the handle runs ``release()``,
        which sends ``op_detach`` and closes the socket.  Closing a
        healthy attachment this way does not consult
        ``ConnectionIdleTimeout``.  A configured timeout can still
        close an attachment that stays idle between requests; leave
        the setting unset so that does not happen.  An attachment
        can still linger only when the TCP session was already dead
        and the server does not notice the close.  Skipping
        ``detach()`` is preferable to a process crash.

        *abandon* only changes the log reason/level (connection-loss vs
        normal close).  ``firebirdsql`` is pure Python and keeps a
        normal ``conn.close()``.
        """
        with self._lock:
            conn = self.conn
            self.conn = None
            self.opened = None
            if conn is None:
                return
            if _DRIVER == "firebird-driver":
                reason = "connection-loss" if abandon else "normal-close"
                self._abandon_firebird_driver_connection(conn, reason=reason)
                return
            # firebirdsql: pure Python, normal close is always safe.
            try:
                is_closed = getattr(conn, "is_closed", None)
                if callable(is_closed) and is_closed():
                    return
                conn.close()
            except Exception:
                LOG.warning(
                    "Error closing the Firebird connection.", exc_info=True
                )

    def _abandon_firebird_driver_connection(self, conn, *, reason="unknown"):
        """Drop a firebird-driver connection without native detach.

        *reason* is only for logging: ``connection-loss`` (retry/loss
        paths) vs ``normal-close`` (ZMI, reopen, explicit close).
        """
        # connection-loss stays WARNING (ops signal). normal-close is
        # DEBUG so ZMI reopen / open()→close() does not flood the event log.
        log = LOG.warning if reason == "connection-loss" else LOG.debug
        log(
            "Closing firebird-driver connection without detach "
            "(avoids libfbclient YAttachment::detach SIGILL risk). "
            "reason=%s thread=%s conn_id=%s",
            reason,
            threading.current_thread().ident,
            id(conn),
        )
        # Null _att FIRST so Connection.__del__ cannot detach even
        # if best-effort cleanup below is interrupted.  firebird-driver
        # 2.0.x: only Connection.close()/__del__ call _att.detach();
        # _close()/_close_internals() do not detach (they roll back /
        # close transactions and statements).
        self._neutralize_firebird_driver_attachment(conn)
        # Best-effort local cleanup.  With _att already None, helpers
        # that still touch the wire fail; that is expected and suppressed.
        with contextlib.suppress(Exception):
            conn._close()
        with contextlib.suppress(Exception):
            conn._close_internals()

    @staticmethod
    def _neutralize_firebird_driver_attachment(conn):
        """Null ``_att`` so firebird-driver will not detach in ``__del__``."""
        with contextlib.suppress(Exception):
            if getattr(conn, "_att", None) is not None:
                conn._att = None

    def __init__(self, connection):
        conn_args = dict(s.split("=", 1) for s in connection.split())
        if _DRIVER == "firebird-driver" and "dsn" in conn_args:
            conn_args["database"] = _convert_dsn(conn_args.pop("dsn"))
        self.conn_args = conn_args
        # Serialize open/close/query: Waitress multi-thread + shared DB
        # connection is a documented risk; RLock also closes TOCTOU
        # windows around native client calls.
        self._lock = threading.RLock()
        self.open()

    def _execute_query(self, query_string, max_rows):
        """Execute query_string on self.conn and return (items, rows).

        Caller must hold ``self._lock``.
        """
        c = self.conn.cursor()
        try:
            queries = [q for q in (s.strip() for s in query_string.split("\0")) if q]
            if not queries:
                # An empty/whitespace query yields an empty result, as it
                # has since the Zope 4 port (queries used to be a py3
                # filter object, so ``if not queries`` was never true).
                return (), ()
            desc = None
            result = []
            for qs in queries:
                c.execute(qs)

                d = c.description
                if d is None:
                    continue
                if desc is None:
                    desc = d
                elif d != desc:
                    raise OperationalError(
                        "Multiple incompatible selects in multiple sql-statement query"
                    )
                if len(result) < max_rows:
                    r = c.fetchmany(max_rows - len(result))
                    if r:
                        if _DRIVER == "firebird-driver":
                            # Read open BLOB streams now, while the cursor
                            # is still on this statement -- the commit
                            # below closes it and with it the readers.
                            r = [_materialize_row(row) for row in r]
                        result += r

            if _DRIVER == "firebird-driver":
                # Commit so the next query gets a fresh READ_COMMITTED
                # snapshot. Not needed for firebirdsql (autocommit is on).
                self.conn.commit()
        except Exception as exc:
            if _DRIVER == "firebird-driver":
                # Rollback so the failed query does not leave an open
                # transaction behind. Accumulated open transactions prevent
                # the OAT from advancing, eventually triggering a server-
                # side "connection shutdown" (GDS 335544856).  Skip the
                # rollback when the wire is already gone — an extra native
                # call on a dead attachment is useless, and the outer
                # query loop will abandon the handle.
                if not _is_firebird_driver_connection_lost(exc):
                    with contextlib.suppress(Exception):
                        self.conn.rollback()
            raise
        finally:
            with contextlib.suppress(Exception):
                c.close()

        if desc is None:
            return (), ()

        items = []
        for name, type_code, width, ds, p, scale, null_ok in desc:
            items.append(
                {
                    "name": name,
                    "type": _zrdb_type(type_code, scale),
                    "width": width,
                    "null": null_ok,
                }
            )

        return items, result

    def query(self, query_string, max_rows=9999999):
        """Public entry point — dispatch to the active driver backend."""
        with self._lock:
            if _DRIVER == "firebirdsql":
                return self._query_firebirdsql(query_string, max_rows)
            return self._query_firebird_driver(query_string, max_rows)

    def _reconnect_for_retry(self, query_string, exc, delay=0):
        """Gate a firebirdsql connection-loss retry to pure SELECT batches,
        then close so the loop's guard reopens on the next pass.

        Raises for a non-SELECT batch (after closing, so the next request
        reconnects via the guard): firebirdsql autocommits per statement,
        so replaying it after a mid-batch drop could commit a write twice
        (a single INSERT can be through server-side even if only the reply
        was lost). Only self.close() here -- the reopen happens inside the
        loop's try, where a failed reconnect is caught and retried instead
        of escaping raw.
        """
        if not _is_read_only_batch(query_string):
            # Close before raising -- otherwise a pure-write worker would
            # keep hitting the dead connection on every request.
            self.close()
            raise _operational_error(
                exc, query_string, prefix=_CONNECTION_LOST_NO_RETRY
            ) from exc
        if delay:
            time.sleep(delay)
        self.close()

    def _close_after_connection_loss(self):
        """Drop a connection after a detected wire/attachment loss.

        Under ``firebird-driver`` this *abandons* the handle (no native
        detach) because detach on a dead attachment can SIGILL.  Under
        ``firebirdsql`` a normal close is fine.
        """
        self.close(abandon=(_DRIVER == "firebird-driver"))

    def _query_firebirdsql(self, query_string, max_rows):
        """Run query via firebirdsql with retries for transient errors.

        Connection-loss retries are gated to pure SELECT batches, like the
        firebird-driver path. Non-transient errors keep their original
        firebirdsql type (P3-3); db.py raises plain text and the DA layer
        escapes it for the Test tab.
        """
        last_exc = None
        for i in range(_FIREBIRDSQL_RETRIES):
            try:
                # Reopen after close() (ZMI button, reconnect) or a stale
                # closed handle; without this, later queries hit None.cursor().
                self._ensure_open()
                return self._execute_query(query_string, max_rows)

            except OperationalError as e:
                msg = _exception_message(e)
                if msg in (
                    "Can not recv() packets",
                    "_op_allocate_statement() Invalid db handle",
                ):
                    last_exc = e
                    self._reconnect_for_retry(query_string, e, delay=1)
                elif "too many open handles to database" in msg:
                    last_exc = e
                    self._reconnect_for_retry(query_string, e)
                else:
                    # SQL / logic error: keep the original type (P3-3).
                    raise _attach_sql(e, query_string)
            except Error as e:
                raise _attach_sql(e, query_string)
            except OSError as e:
                # Covers BrokenPipeError from a dying socket AND the raw
                # OS errors the reopen guard's connect() raises while the
                # server is still down or unreachable -- not just
                # ConnectionError/TimeoutError, but also socket.gaierror
                # (DNS) and EHOSTUNREACH/ENETUNREACH, which are plain
                # OSError. So a failed reconnect is retried instead of
                # escaping raw and skipping the remaining attempts.
                last_exc = e
                self._reconnect_for_retry(query_string, e)
        raise _operational_error(
            last_exc,
            query_string,
            prefix=f"Firebird query failed after {_FIREBIRDSQL_RETRIES} retries.",
        ) from last_exc

    def _query_firebird_driver(self, query_string, max_rows):
        """Run query via firebird-driver with reconnect retries.

        SQL/logic errors are wrapped in the custom OperationalError (plain
        text + structured .sql/.sqlstate/.sqlcode) because the raw
        firebird.base.types.Error crashes DTML rendering. Connection-loss
        retries are gated to pure SELECT batches. The DA layer escapes the
        message and, for Manager callers, appends the SQL for the Test tab.
        """
        last_exc = None
        for attempt in range(_FIREBIRD_DRIVER_RETRIES):
            try:
                self._ensure_open()
                return self._execute_query(query_string, max_rows)

            except (Error, ConnectionError, InterfaceError) as e:
                if not _is_firebird_driver_connection_lost(e):
                    # SQL / logic error: wrap as plain text, keep attrs.
                    raise _operational_error(e, query_string) from e
                if not _is_read_only_batch(query_string):
                    # Connection lost on a batch that may write. The commit
                    # can already have reached the server before the drop,
                    # so replaying the batch risks a duplicate write --
                    # surface the loss immediately instead. Abandon first so
                    # the next request reconnects via the guard above, and
                    # so we never detach a dead libfbclient attachment.
                    self._close_after_connection_loss()
                    raise _operational_error(
                        e, query_string, prefix=_CONNECTION_LOST_NO_RETRY
                    ) from e
                last_exc = e
                self._close_after_connection_loss()
                if attempt < _FIREBIRD_DRIVER_RETRIES - 1:
                    time.sleep(_FIREBIRD_DRIVER_RETRY_DELAY)

        raise _operational_error(
            last_exc, query_string, prefix=_CONNECTION_LOST_EXHAUSTED
        ) from last_exc
