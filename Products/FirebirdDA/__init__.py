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
# Single source of truth for the package version: setup.py parses this
# line, DA.py imports it for the ZMI display. Must stay ABOVE the DA
# import -- DA.py does ``from . import __version__`` while this module
# is still initialising.
__version__ = '0.8.0'

from . import DA

def initialize(context):

    context.registerClass(
        DA.Connection,
        permission='Add Firebird Database Connections',
        constructors=(DA.manage_addFirebirdConnectionForm,
                      DA.manage_addFirebirdConnection)
    )
