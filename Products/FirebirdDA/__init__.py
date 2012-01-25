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
from App.ImageFile import ImageFile
import os

classes=('DA.Connection',)
database_type='Firebird'

class FirebirdError(Exception):
    pass

class QueryError(FirebirdError):
    pass

misc_={}

for icon in ('conn', 'table', 'view', 'stable', 'what',
             'field', 'text','bin','int','float',
             'date','time','datetime', 'generator', 'sequence',
             'procedure', 'trigger', 'trigger_inactive', 
             'key_primary', 'key_foreign', 'key', 'index', 'check'):
    misc_[icon+'.gif']=ImageFile('icons/%s.gif' % icon, globals())

DA=None
def getDA():
    global DA
    if DA is None:
        import DA
    return DA

getDA()

__module_aliases__=(
    ('Products.AqueductFirebird.DA', DA),
    )

def manage_addFirebirdConnectionForm(self, REQUEST, *args, **kw):
    " "
    DA=getDA()
    return DA.addConnectionForm(
        self, self, REQUEST,
        database_type=database_type)

def manage_addFirebirdConnection(
    self, id, title, connection, check=None, REQUEST=None):
    " "
    return getDA().manage_addFirebirdConnection(
        self, id, title, connection, check, REQUEST)

def initialize(context):

    context.registerClass(
        DA.Connection,
        permission='Add Firebird Database Connections',
        constructors=(manage_addFirebirdConnectionForm,
                      manage_addFirebirdConnection),
        legacy=(manage_addFirebirdConnectionForm,
                manage_addFirebirdConnection),
    )

