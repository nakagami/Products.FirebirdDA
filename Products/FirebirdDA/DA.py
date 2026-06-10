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

from AccessControl.class_init import InitializeClass
from AccessControl.Permissions import test_database_connections
from AccessControl.SecurityInfo import ClassSecurityInfo
from .db import DB, _DRIVER
from .isql_meta import translate_isql_meta, source_object_name
import Shared.DC.ZRDB.Connection
from App.special_dtml import HTMLFile


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
    _isAnSQLConnection = True
    meta_type = f'{database_type} Database Connection'
    zmi_icon = 'fas fa-database'

    security = ClassSecurityInfo()

    manage_properties=HTMLFile('dtml/connectionEdit', globals())

    def connected(self):
        if hasattr(self, '_v_database_connection'):
            return self._v_database_connection.opened
        return ''

    def title_or_id(self):
        s = self.title or self.id
        status = 'connected' if self.connected() else 'not connected'
        return f'{s} ({status})'

    def connect(self, s):
        self._v_database_connection = DB(s)
        return self

    @security.protected(test_database_connections)
    def manage_test(self, query, REQUEST=None):
        """Translate ISQL meta commands, then run the standard Test query.

        ISQL shortcuts (``show tables`` / ``show procedure NAME`` / ...)
        are a Test-tab convenience, so the translation lives here in the
        DA layer -- already gated by the Test tab's own
        ``test_database_connections`` permission -- rather than in the
        driver's shared query() path, which also serves Z SQL Methods.
        """
        translated = translate_isql_meta(query)
        if translated is not None:
            query = translated
        return super().manage_test(query, REQUEST)

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
            html = (
                '%s\n<style>main table.table td '
                '{white-space: pre-wrap; font-family: monospace; tab-size: 4;}'
                '</style>'
                % html)
        return html


InitializeClass(Connection)
