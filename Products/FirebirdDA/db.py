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
import html
import os
import re
import signal
import time

import Shared.DC.ZRDB.THUNK
from DateTime import DateTime

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
    import threading

    from firebird.driver import DatabaseError as Error
    from firebird.driver import InterfaceError
    from firebird.driver import connect as _raw_connect
    from firebird.driver import tpb as _make_tpb
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

        pass

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

elif _DRIVER == "firebirdsql":
    import firebirdsql
    from firebirdsql import OperationalError

    _connect = firebirdsql.connect
    Error = firebirdsql.Error

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
)


def _is_firebird_driver_connection_lost(exc):
    """True if exc indicates a transient connection-loss situation
    where a reconnect + single retry makes sense."""
    # BrokenPipeError is a subclass of ConnectionError.
    if isinstance(exc, (ConnectionError, InterfaceError)):
        return True
    codes = getattr(exc, "gds_codes", None) or ()
    if any(c in RECONNECT_GDS_CODES for c in codes):
        return True
    msg = str(exc).lower()
    return any(m in msg for m in _RECONNECT_MARKERS)


def _exception_message(exc):
    """Return a defensive string message for exceptions with optional args."""
    args = getattr(exc, "args", None)
    msg = str(args[0] if args else exc)
    if not msg:
        msg = exc.__class__.__name__
    return msg


def _caller_is_manager():
    """True if the current Zope user has the Manager role.

    Gates a single Manager-only convenience in this DA: including the
    offending SQL snippet in error messages.  Non-Manager callers get
    sanitised errors without the SQL.

    Uses has_role(('Manager',)) instead of checkPermission because
    checkPermission needs an Acquisition-wrapped context object,
    which the DB instance does not have.
    """
    try:
        from AccessControl import getSecurityManager

        return getSecurityManager().getUser().has_role(("Manager",))
    except Exception:
        # Outside a Zope request (unit test, startup) be conservative:
        # no SQL in errors.
        return False


def _html_safe(value):
    """Normalise to str, HTML-escape, then render newlines as <br/>.

    Defends against Zope TaintedString input (SQL containing < or >)
    and keeps unescaped error/SQL text out of the HTML output.
    """
    return html.escape(str(value), quote=True).replace("\n", "<br/>")


def _format_firebirdsql_error(exc):
    """Format a firebirdsql exception as an HTML-safe error message."""
    msg = _html_safe(_exception_message(exc))
    op = OperationalError(msg)
    op.args = (msg,)
    return op


def _format_firebird_driver_error(exc, query_string, include_sql=False):
    """Format a firebird-driver exception as a multi-line message."""
    parts = ["Firebird query failed."]

    orig = str(exc).strip()
    if orig:
        parts.append(f"Error: {_html_safe(orig)}")

    sqlstate = getattr(exc, "sqlstate", None)
    if sqlstate:
        if isinstance(sqlstate, bytes):
            sqlstate = sqlstate.decode("ascii", "replace")
        parts.append(f"SQLSTATE: {_html_safe(sqlstate)}")

    sqlcode = getattr(exc, "sqlcode", None)
    if sqlcode is not None:
        parts.append(f"SQLCODE: {_html_safe(sqlcode)}")

    if query_string and include_sql:
        snippet = str(query_string).strip()
        max_len = 2000
        if len(snippet) > max_len:
            snippet = snippet[:max_len] + "\n  ... (truncated)"
        parts.append(f"SQL: {_html_safe(snippet)}")

    return "<br/>".join(parts)


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
    """
    m = re.match(r"^([^:/]+)(?::(\d+))?[:/](.+)$", dsn)
    if not m:
        raise ValueError(f"Unrecognized DSN format: {dsn!r}")
    host, port, path = m.groups()
    if port:
        return f"{host}/{port}:{path}"
    # /alias (single component) -> alias; /path/to/db stays as-is
    if path.startswith("/") and "/" not in path[1:]:
        path = path[1:]
    return f"{host}:{path}"


class DB(Shared.DC.ZRDB.THUNK.THUNKED_TM):
    database_error = Error
    opened = None

    conn = None

    def open(self):
        if self.conn is not None:
            self.close()
        self.conn = _connect(**self.conn_args)
        if _DRIVER == "firebirdsql":
            self.conn.set_autocommit(True)
        else:
            self.conn.main_transaction.default_tpb = _make_tpb(
                _Isolation.READ_COMMITTED
            )
        self.opened = DateTime()

    def close(self):
        conn = self.conn
        self.conn = None
        self.opened = None
        if conn is None:
            return
        with contextlib.suppress(Exception):
            conn.close()

    def __init__(self, connection):
        conn_args = dict(s.split("=", 1) for s in connection.split())
        if _DRIVER == "firebird-driver" and "dsn" in conn_args:
            conn_args["database"] = _convert_dsn(conn_args.pop("dsn"))
        self.conn_args = conn_args
        self.open()

    def _execute_query(self, query_string, max_rows):
        """Execute query_string on self.conn and return (items, rows)."""
        c = self.conn.cursor()
        try:
            queries = [q for q in (s.strip() for s in query_string.split("\0")) if q]
            if not queries:
                raise OperationalError("empty query")
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
                        result += r

            if _DRIVER == "firebird-driver":
                # Commit so the next query gets a fresh READ_COMMITTED
                # snapshot. Not needed for firebirdsql (autocommit is on).
                self.conn.commit()
        except Exception:
            if _DRIVER == "firebird-driver":
                # Rollback so the failed query does not leave an open
                # transaction behind. Accumulated open transactions prevent
                # the OAT from advancing, eventually triggering a server-
                # side "connection shutdown" (GDS 335544856).
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
        if _DRIVER == "firebirdsql":
            return self._query_firebirdsql(query_string, max_rows)
        return self._query_firebird_driver(query_string, max_rows)

    def _query_firebirdsql(self, query_string, max_rows):
        """Run query via firebirdsql with retries for transient errors."""
        last_exc = None
        for i in range(_FIREBIRDSQL_RETRIES):
            try:
                return self._execute_query(query_string, max_rows)

            except OperationalError as e:
                last_exc = e
                msg = _exception_message(e)
                if msg in (
                    "Can not recv() packets",
                    "_op_allocate_statement() Invalid db handle",
                ):
                    time.sleep(1)
                    self.close()
                    self.open()
                elif "too many open handles to database" in msg:
                    self.close()
                    self.open()
                else:
                    raise _format_firebirdsql_error(e) from e
            except Error as e:
                raise _format_firebirdsql_error(e) from e
            except BrokenPipeError as e:
                last_exc = e
                self.close()
                self.open()
        exc = _format_firebirdsql_error(last_exc)
        exc.args = (
            f"Firebird query failed after {_FIREBIRDSQL_RETRIES} retries: "
            + exc.args[0],
        )
        raise exc from last_exc

    def _query_firebird_driver(self, query_string, max_rows):
        """Run query via firebird-driver with retry and error enrichment."""
        last_exc = None
        for attempt in range(_FIREBIRD_DRIVER_RETRIES):
            try:
                if self.opened is None:
                    self.open()
                return self._execute_query(query_string, max_rows)

            except (Error, ConnectionError) as e:
                if not _is_firebird_driver_connection_lost(e):
                    # SQL / logic error: enrich and re-raise.
                    msg = _format_firebird_driver_error(
                        e, query_string, include_sql=_caller_is_manager()
                    )
                    raise OperationalError(msg) from e
                last_exc = e
                self.close()
                if attempt < _FIREBIRD_DRIVER_RETRIES - 1:
                    time.sleep(_FIREBIRD_DRIVER_RETRY_DELAY)

        msg = (
            "Connection to Firebird lost; reconnect attempts "
            "exhausted.\n\n"
            + _format_firebird_driver_error(
                last_exc, query_string, include_sql=_caller_is_manager()
            )
        )
        raise OperationalError(msg) from last_exc
