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
import os
import firebirdsql
import Shared.DC.ZRDB.THUNK
from DateTime import DateTime

from firebirdsql import OperationalError

with_system_flag=0

def fetchallmap(c):
    desc = c.description
    r = []
    for row in c.fetchall():
        d = {}
        for i in range(len(desc)):
            key = str(desc[i][0])
            try: d[key] = row[i].strip()
            except: d[key] = row[i]
        r.append(d)
    return r

class DB(Shared.DC.ZRDB.THUNK.THUNKED_TM):
    database_error=firebirdsql.Error
    opened=None

    def open(self):
        self.conn = firebirdsql.connect(**self.conn_args)
        self.conn.set_autocommit(True)
        self.opened=DateTime()

    def close(self):
        self.conn.close()
        self.opened = None

    def __init__(self,connection):
        conn_args = {}
        for s in connection.split():
            k,v = s.split('=', 1)
            conn_args[k] = v
        self.conn_args = conn_args
        self.db_conn = []
        self.open()

    def query(self,query_string, max_rows=9999999):
        c = self.conn.cursor()

        queries=filter(None, [q.strip() for q in query_string.split('\0')])
        if not queries:
            raise OperationalError('empty query')
        desc=None
        result=[]
        for qs in queries:
            c.execute(qs)
            d=c.description
            if d is None: continue
            if desc is None: desc=d
            elif d != desc:
                raise OperationalError(
                    'Multiple incompatible selects in '
                    'multiple sql-statement query'
                    )

            if len(result) < max_rows:
                r = c.fetchmany(max_rows-len(result))
                if r:
                    result += r


        if desc is None:
            return (), ()

        items=[]
        for name, type, width, ds, p, scale, null_ok in desc:
            if type=='NUMBER':
                if scale==0: type='i'
                else: type='n'
            elif type=='DATE':
                type='d'
            else: type='s'
            items.append({
                'name': name,
                'type': type,
                'width': width,
                'null': null_ok,
                })

        return items, result

