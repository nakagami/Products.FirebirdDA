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
database_type='Firebird'

from html import escape as html_escape

from AccessControl import getSecurityManager
from AccessControl.class_init import InitializeClass
from AccessControl.Permissions import test_database_connections
from AccessControl.SecurityInfo import ClassSecurityInfo
from . import __version__
from .db import DB, _DRIVER, QUERY_ERRORS
from .isql_meta import translate_isql_meta, source_object_name
import Shared.DC.ZRDB.Connection
from App.special_dtml import HTMLFile


def _html_safe(value):
    """HTML-escape a value and render newlines as <br/> for Test-tab
    display.  The Test tab's connectionTestForm.dtml renders
    ``error_value`` WITHOUT html_quote, so error text that crosses this
    display boundary must already be HTML-safe.  db.py deliberately keeps
    its exceptions plain text, so the escaping lives here, at the boundary,
    and never touches the shared query() path (Z SQL Methods, SiteErrorLog,
    event log).
    """
    return html_escape(str(value), quote=True).replace('\n', '<br/>')


class TestQueryError(Exception):
    """Carries a pre-escaped, HTML-safe message for the ZMI Test tab.

    Raised by Connection.manage_test after a driver error so the message
    rendered by ``error_value`` (no html_quote) is safe.  Not derived from
    the driver exception classes, so DocumentTemplate's safe_callable()
    cannot mis-fire on it -- the same hazard the custom db.OperationalError
    avoids.
    """


addConnectionForm=HTMLFile('dtml/connectionAdd',globals())


def manage_addFirebirdConnectionForm(self, REQUEST):
    """Add a connection form"""
    return addConnectionForm(
        self, self, REQUEST,
        database_type=database_type,
    )


def manage_addFirebirdConnection(
    self, id, title, connection, check=None, REQUEST=None):
    """Add a DB connection to a folder"""

    # Note - type checking is taken care of by _setObject
    # and the Connection object constructor.
    self._setObject(id, Connection(
        id, title, connection, check))
    if REQUEST is not None:
        return self.manage_main(self,REQUEST)

class Connection(Shared.DC.ZRDB.Connection.Connection):
    """Zope ZRDB Connection for Interbase/Firebird databases."""
    database_type=database_type
    driver_name=_DRIVER
    da_version = __version__
    _isAnSQLConnection = True
    meta_type = f'{database_type} Database Connection'
    zmi_icon = 'fas fa-database'

    security = ClassSecurityInfo()

    manage_properties=HTMLFile('dtml/connectionEdit', globals())

    def connected(self):
        if hasattr(self, '_v_database_connection'):
            return self._v_database_connection.opened
        return ''

    def factory(self):
        # Used by the inherited connect(), which also closes a previous
        # connection first, wraps connect-time driver errors in BadRequest
        # (raw firebird.base.types.Error would crash DTML rendering, see
        # db.OperationalError) and maintains _v_connected for the status
        # texts of title_or_id/title_and_id.
        return DB

    @security.protected(test_database_connections)
    def manage_test(self, query, REQUEST=None):
        """Translate ISQL meta commands, then run the standard Test query.

        ISQL shortcuts (``show tables`` / ``show procedure NAME`` / ...)
        are a Test-tab convenience, so the translation lives here in the
        DA layer -- already gated by the Test tab's own
        ``test_database_connections`` permission -- rather than in the
        driver's shared query() path, which also serves Z SQL Methods.

        A driver error is caught and re-raised HTML-safe: db.py raises
        plain-text exceptions (keeping the shared path clean), but this
        Test tab's ``connectionTestForm.dtml`` renders ``error_value``
        without html_quote. The offending SQL is appended only for
        Manager callers.
        """
        # A query containing '<' (e.g. ``WHERE x < 5``) arrives from the
        # form as a TaintedString, which is not a str subtype and breaks
        # the meta-command string handling below. Normalise to the raw
        # str; _test_query_error escapes it again for display.
        query = str(query)
        translated = translate_isql_meta(query)
        if translated is not None:
            query = translated
        try:
            return super().manage_test(query, REQUEST)
        except QUERY_ERRORS as exc:
            raise self._test_query_error(exc) from exc

    def _test_query_error(self, exc):
        """Turn a plain-text driver exception into an HTML-safe
        ``TestQueryError`` for the Test tab: the escaped message, then
        SQLSTATE/SQLCODE if present, and -- only for Manager callers
        (local roles included) -- the offending SQL.
        """
        parts = [_html_safe(str(exc) or type(exc).__name__)]

        sqlstate = getattr(exc, 'sqlstate', None)
        if sqlstate:
            if isinstance(sqlstate, bytes):
                sqlstate = sqlstate.decode('ascii', 'replace')
            parts.append(f'SQLSTATE: {_html_safe(sqlstate)}')

        # firebird-driver exposes sqlcode; firebirdsql exposes sql_code.
        # Truthiness, not "is not None": firebirdsql defaults sql_code to
        # 0 (= success) on every exception, which is never meaningful in
        # an error display.
        sqlcode = getattr(exc, 'sqlcode', None)
        if not sqlcode:
            sqlcode = getattr(exc, 'sql_code', None)
        if sqlcode:
            parts.append(f'SQLCODE: {_html_safe(sqlcode)}')

        sql = getattr(exc, 'sql', None)
        if sql and self._caller_is_manager():
            snippet = str(sql).strip()
            max_len = 2000
            if len(snippet) > max_len:
                snippet = snippet[:max_len] + '\n  ... (truncated)'
            parts.append(f'SQL: {_html_safe(snippet)}')

        return TestQueryError('<br/>'.join(parts))

    def _caller_is_manager(self):
        """True if the current user holds the Manager role in this
        connection's context. Passing ``self`` makes has_role consider
        LOCAL roles too; without a context object only global roles count
        (the P2-5 bug), so a site-local Manager would never see the SQL.
        """
        try:
            user = getSecurityManager().getUser()
            return bool(user.has_role(('Manager',), self))
        except Exception:
            # Outside a request (unit test, startup): no SQL in errors.
            return False

    @security.protected(test_database_connections)
    def manage_testForm(self, REQUEST=None, **kw):
        """Standard Test form, with one tweak for the source-listing
        ``show <kind> NAME`` commands (procedure/view/trigger/function).

        Those return the object's body in a single result cell whose DOM
        text already holds the newlines, but the ZMI table renders cells
        with ``white-space: normal`` -- which collapses the code on screen
        and, worse, makes a copy come out collapsed too. For such a query
        we append a small stylesheet switching the result cell to
        ``white-space: pre-wrap``, so the source shows and copies properly
        formatted. Everything else is the stock form.
        """
        html = super().manage_testForm(REQUEST, **kw)
        if REQUEST is not None and source_object_name(REQUEST.get('query') or ''):
            html = f'{html}\n' + (
                '<style>main table.table td '
                '{white-space: pre-wrap; font-family: monospace; tab-size: 4;}'
                '</style>')
        return html


InitializeClass(Connection)
