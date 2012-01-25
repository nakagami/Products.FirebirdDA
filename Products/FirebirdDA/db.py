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
import os, thread, string
import firebirdsql
import Shared.DC.ZRDB.THUNK
from DateTime import DateTime

from Products.FirebirdDA import QueryError

with_system_flag=0

def fetchallmap(c):
    desc = c.description
    r = []
    for row in c.fetchall():
        d = {}
        for i in range(len(desc)):
            key = str(desc[i][0])
            try: d[key] = string.strip(row[i])
            except: d[key] = row[i]
        r.append(d)
    return r

class DB(Shared.DC.ZRDB.THUNK.THUNKED_TM):
    database_error=firebirdsql.Error
    opened=None

    def tables(self, *args, **kw):
        self._begin()
        c = self.conn.cursor()

        if with_system_flag:
            c.execute('''select rdb$relation_name TABLE_NAME, 
                rdb$owner_name TABLE_OWNER, rdb$view_source VIEW_SOURCE,
                rdb$system_flag SYSTEM_FLAG
                from rdb$relations 
                order by rdb$flags, rdb$relation_name''')
        else:
            c.execute('''select rdb$relation_name TABLE_NAME, 
                rdb$owner_name TABLE_OWNER, rdb$view_source VIEW_SOURCE,
                rdb$system_flag SYSTEM_FLAG
                from rdb$relations where rdb$flags=1 
                order by rdb$relation_name''')
        rows = fetchallmap(c)
        self._finish()
        return rows

    def columns(self, table_name):
        self._begin()
        c = self.conn.cursor()

        r=c.execute('''select A.rdb$field_name NAME, 
    A.rdb$null_flag NULL_FLAG, A.rdb$default_source DEFAULT_SOURCE,
    C.rdb$type_name TYPE_NAME,
    B.rdb$field_sub_type FIELD_SUB_TYPE, B.rdb$field_precision FIELD_PRECISION,
    B.rdb$field_scale FIELD_SCALE, B.rdb$character_length "CHARACTER_LENGTH"
    from rdb$relation_fields A, rdb$fields B, rdb$types C
    where C.rdb$field_name='RDB$FIELD_TYPE' 
        and A.rdb$field_source = B.rdb$field_name 
        and B.rdb$field_type=C.rdb$type and  A.rdb$relation_name='%s'
    order by A.rdb$field_position, A.rdb$field_name''' % table_name)

        rows=fetchallmap(c)

        self._finish()
        return rows

    def constraints(self, table_name):
        self._begin()
        c = self.conn.cursor()

        r=c.execute('''select 
    a.rdb$index_name INDEX_NAME, a.rdb$index_id INDEX_ID, 
    a.rdb$foreign_key FOREIGN_KEY, 
    b.rdb$field_name FIELD_NAME, c.rdb$constraint_type CONST_TYPE, 
    c.rdb$constraint_name CONST_NAME,
    d.rdb$update_rule UPDATE_RULE, d.rdb$delete_rule DELETE_RULE
    from rdb$indices A, rdb$index_segments B, 
    rdb$relation_constraints C left join rdb$ref_constraints D 
                on c.rdb$constraint_name=d.rdb$constraint_name
    where A.rdb$index_name=B.rdb$index_name 
        AND A.rdb$index_name=C.rdb$index_name
        AND a.rdb$relation_name='%s'
    order by a.rdb$index_id, b.rdb$field_position ''' % table_name)
        rows = fetchallmap(c)

        d = {}
        for row in rows:
            if not d.has_key(row['INDEX_ID']):
                if row['CONST_TYPE']:
                    const_type = row['CONST_TYPE']
                else:
                    const_type = 'INDEX'
                d[row['INDEX_ID']] = {
                    'INDEX_NAME': row['INDEX_NAME'], 
                    'CONST_TYPE': const_type, 
                    'CONST_NAME': row['CONST_NAME'],
                    'UPDATE_RULE': row['UPDATE_RULE'],
                    'DELETE_RULE': row['DELETE_RULE'],
                    'FIELD_NAME': [] }
                if row['FOREIGN_KEY']:
                    d[row['INDEX_ID']]['FOREIGN_KEY'] = self._references(c, row['FOREIGN_KEY'])

            d[row['INDEX_ID']]['FIELD_NAME'].append(row['FIELD_NAME'])

        self._finish()

        return d

    def _references(self, c, index_name):
        r=c.execute('''select 
            a.rdb$relation_name RELATION_NAME, B.rdb$field_name FIELD_NAME 
              from rdb$indices A, rdb$index_segments B
              where A.rdb$index_name='%s' 
              and A.rdb$index_name=b.rdb$index_name''' % index_name)

        rows = c.fetchall()
        d = []
        for r in rows:
            d.append(string.strip(r[1]))

        return (index_name, string.strip(rows[0][0]), d)  #index,table,[fields]

    def triggers(self, table_name):
        self._begin()
        c = self.conn.cursor()

        if with_system_flag:
            r=c.execute(''' select 
                rdb$trigger_name TRIGGER_NAME, 
                rdb$trigger_sequence TRIGGER_SEQUENCE, 
                rdb$trigger_type TRIGGER_TYPE, 
                rdb$trigger_source TRIGGER_SOURCE, 
                rdb$trigger_inactive TRIGGER_INACTIVE
                    from rdb$triggers
                    where rdb$relation_name='%s'
                    order by rdb$trigger_sequence''' % table_name)
        else:
            r=c.execute(''' select 
                rdb$trigger_name TRIGGER_NAME, 
                rdb$trigger_sequence TRIGGER_SEQUENCE, 
                rdb$trigger_type TRIGGER_TYPE, 
                rdb$trigger_source TRIGGER_SOURCE, 
                rdb$trigger_inactive TRIGGER_INACTIVE
                    from rdb$triggers
                    where (rdb$system_flag is null or rdb$system_flag = 0) 
                        and rdb$relation_name='%s'
                    order by rdb$trigger_sequence''' % table_name)

        rows = fetchallmap(c)
        self._finish()
        return rows

    def check_constraints(self, table_name):
        self._begin()
        c = self.conn.cursor()

        r=c.execute('''select 
            A.rdb$constraint_name CHECK_NAME, 
            C.rdb$trigger_source CHECK_SOURCE 
            from rdb$relation_constraints A, rdb$check_constraints B, 
                rdb$triggers C
            where A.rdb$constraint_name = B.rdb$constraint_name 
                and B.rdb$trigger_name = C.rdb$trigger_name 
                and rdb$constraint_type='CHECK' 
                and A.rdb$relation_name = '%s' ''' % table_name)

        rows = c.fetchall()

        d = {}
        for row in rows:
            d[row[0]] = {'CHECK_NAME': string.strip(row[0]),
                        'CHECK_SOURCE': string.strip(row[1])}

        self._finish()

        return d

    def generators(self):
        self._begin()
        c = self.conn.cursor()

        if with_system_flag:
            c.execute('''select rdb$generator_name, rdb$system_flag
                  from rdb$generators 
                  order by rdb$system_flag, rdb$generator_name''')
        else:
            c.execute('''select rdb$generator_name, rdb$system_flag
                  from rdb$generators 
                  where rdb$system_flag is null or rdb$system_flag = 0 
                  order by rdb$system_flag, rdb$generator_name''')
        gens=c.fetchall()
        r=[]
        for gen in gens:
            c.execute(''' select gen_id(%s,0) from rdb$database ''' % gen[0])
            count = c.fetchone()[0]
            r.append({'GENERATOR_NAME': string.strip(gen[0]),
                    'SYSTEM_FLAG': gen[1],
                    'GENERATOR_COUNT': count})

        self._finish()
        return r

    def procedures(self):
        self._begin()
        c = self.conn.cursor()

        c.execute('''select rdb$procedure_name, rdb$procedure_source 
                from rdb$procedures order by rdb$procedure_name''')
        procs=c.fetchall()
        r=[]
        for proc in procs:
            c.execute(''' select A.rdb$parameter_name NAME, 
    C.rdb$type_name TYPE_NAME,
    B.rdb$field_sub_type FIELD_SUB_TYPE, B.rdb$field_precision FIELD_PRECISION,
    B.rdb$field_scale FIELD_SCALE, B.rdb$character_length "CHARACTER_LENGTH"
    from rdb$procedure_parameters A, rdb$fields B, rdb$types C
      where C.rdb$field_name='RDB$FIELD_TYPE' 
         and A.rdb$field_source = B.rdb$field_name 
         and A.rdb$parameter_type = 0
         and B.rdb$field_type=C.rdb$type and  A.rdb$procedure_name='%s'
       order by A.rdb$parameter_number''' % proc[0])
            in_params = fetchallmap(c)

            c.execute(''' select A.rdb$parameter_name NAME, 
    C.rdb$type_name TYPE_NAME,
    B.rdb$field_sub_type FIELD_SUB_TYPE, B.rdb$field_precision FIELD_PRECISION,
    B.rdb$field_scale FIELD_SCALE, B.rdb$character_length "CHARACTER_LENGTH"
    from rdb$procedure_parameters A, rdb$fields B, rdb$types C
      where C.rdb$field_name='RDB$FIELD_TYPE' 
         and A.rdb$field_source = B.rdb$field_name 
         and A.rdb$parameter_type = 1
         and B.rdb$field_type=C.rdb$type and  A.rdb$procedure_name='%s'
       order by A.rdb$parameter_number''' % proc[0])
            out_params = fetchallmap(c)

            r.append({'PROCEDURE_NAME': proc[0],
                    'PROCEDURE_SOURCE': proc[1],
                    'IN_PARAMS': in_params,
                    'OUT_PARAMS':out_params})

        self._finish()
        return r

    def open(self):
        self.conn = firebirdsql.connect(**self.conn_args)
        self.opened=DateTime()

    def close(self):
        self.conn.close()
        self.opened = None

    def __init__(self,connection):
        conn_args = {}
        for s in string.split(connection):
            k,v = s.split('=', 1)
            conn_args[k] = v
        self.conn_args = conn_args
        self.lock = thread.allocate_lock()
        self.db_conn = []
        self.open()

    def query(self,query_string, max_rows=9999999):
        self._begin()
        c = self.conn.cursor()

        queries=filter(None, map(string.strip,string.split(query_string, '\0')))
        if not queries: raise QueryError, 'empty query'
        desc=None
        result=[]
        for qs in queries:
            c.execute(qs)
            d=c.description
            if d is None: continue
            if desc is None: desc=d
            elif d != desc:
                self._abort()
                raise QueryError, (
                    'Multiple incompatible selects in '
                    'multiple sql-statement query'
                    )

            if len(result) < max_rows:
                result=result+c.fetchmany(max_rows-len(result))

        self._finish()

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

    def _begin(self):
        self.conn.begin()

    def _finish(self):
        self.conn.commit()

    def _abort(self):
        self.conn.rollback()
