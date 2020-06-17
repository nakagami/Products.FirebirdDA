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

import sys
import six
from six.moves._thread import allocate_lock

from .db import DB
from .DABase import Connection as BaseConnection
import Shared.DC.ZRDB.Connection
from App.special_dtml import HTMLFile
from zExceptions import BadRequest

_Connection=Shared.DC.ZRDB.Connection.Connection

_connections={}
_connections_lock=allocate_lock()

addConnectionForm=HTMLFile('dtml/connectionAdd',globals())
def manage_addFirebirdConnection(
    self, id, title, connection, check=None, REQUEST=None):
    """Add a DB connection to a folder"""

    # Note - type checking is taken care of by _setObject
    # and the Connection object constructor.
    self._setObject(id, Connection(
        id, title, connection, check))
    if REQUEST is not None: return self.manage_main(self,REQUEST)

class Connection(BaseConnection):
    " "
    database_type=database_type
    id='%s_database_connection' % database_type
    meta_type=title='%s Database Connection' % database_type
    icon='misc_/%sDA/conn.gif' % database_type

    manage_properties=HTMLFile('dtml/connectionEdit', globals())

    def connected(self):
        if hasattr(self, '_v_database_connection'):
            return self._v_database_connection.opened
        return ''

    def title_and_id(self):
        s=_Connection.inheritedAttribute('title_and_id')(self)
        if (hasattr(self, '_v_database_connection') and
            self._v_database_connection.opened):
            s="%s, which is connected" % s
        else:
            s="%s, which is <font color=red> not connected</font>" % s
        return s

    def title_or_id(self):
        s=_Connection.inheritedAttribute('title_and_id')(self)
        if (hasattr(self, '_v_database_connection') and
            self._v_database_connection.opened):
            s="%s (connected)" % s
        else:
            s="%s (<font color=red> not connected</font>)" % s
        return s

    def connect(self,s):
        _connections_lock.acquire()
        try:
            c=_connections
            self._v_database_connection=c[s]=DB(s)
            return self
        finally:
            _connections_lock.release()
