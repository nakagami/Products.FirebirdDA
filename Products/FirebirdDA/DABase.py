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
import sys
from string import join
import Shared.DC.ZRDB.Connection
from App.special_dtml import HTMLFile
from ExtensionClass import Base
import Acquisition

def field_to_string(d):
    type_name = d['TYPE_NAME']
    if type_name == 'SHORT':
        s = 'SMALLINT'
    elif type_name == 'LONG':
        s = 'INTEGER'
    elif type_name == 'TEXT':
        s = 'CHAR(' + str(d['CHARACTER_LENGTH']) + ')'
    elif type_name == 'VARYING':
        s = 'VARCHAR(' + str(d['CHARACTER_LENGTH']) + ')'
    elif type_name == 'INT64':
        if d['FIELD_SUB_TYPE'] == 1:
            s = 'NUMERIC'
        else:
            s = 'DECIMAL'
        s += '(' + str(d['FIELD_PRECISION']) + ',' + str(d['FIELD_SCALE'] * -1) + ')'
    elif type_name == 'BLOB':
        s = 'BLOB SUB_TYPE ' + str(d['FIELD_SUB_TYPE'])
    else:
        s = type_name

    if d.get('NULL_FLAG'):
        s += ' NOT NULL '

    if d.get('DEFAULT_SOURCE'):
        s += d['DEFAULT_SOURCE']

    return s

class Connection(Shared.DC.ZRDB.Connection.Connection):
    _isAnSQLConnection=1

    manage_options=Shared.DC.ZRDB.Connection.Connection.manage_options+(
        {'label': 'Browse', 'action':'manage_browse'},
        )

    manage_tables=HTMLFile('dtml/tables',globals())
    manage_browse=HTMLFile('dtml/browse',globals())

    def tpValues(self):
        r=[]
        if not hasattr(self, '_v_database_connection'):
            return r
        c=self._v_database_connection

        for d in c.tables(rdb=0):
            r.append(TableBrowser(d, c))
        for d in c.procedures():
            r.append(ProcedureBrowser(d))
        for d in c.generators():
            r.append(GeneratorBrowser(d))

        return r

    def __getitem__(self, name):
        if name=='tableNamed':
            if not hasattr(self, '_v_tables'): self.tpValues()
            return self._v_tables.__of__(self)
        raise KeyError, name

class Browser(Base):
    info=None
    icon=''
    Description=''
    def __init__(self, d, c=None):
        self.__dict__.update(d)
        self._c = c

    def tpValues(self):
        return []

    def tpId(self): return ''
    def Name(self): return self.tpId()
    def Type(self): return ''
    def Params(self): return ''
    def Source(self): return ''

class TableBrowser(Browser, Acquisition.Implicit):
    info=HTMLFile('dtml/table_info',globals())

    def tpValues(self):
        r=[]

        for d in self._c.columns(self.TABLE_NAME):
            r.append(ColumnBrowser(d))

        consts = self._c.constraints(self.TABLE_NAME)
        for d in consts:
            r.append(ConstraintBrowser(consts[d]))

        check_consts = self._c.check_constraints(self.TABLE_NAME)
        for d in check_consts:
            r.append(CheckConstraintBrowser(check_consts[d]))

        for d in self._c.triggers(self.TABLE_NAME):
            r.append(TriggerBrowser(d))

        r.append(SourceBrowser(self.VIEW_SOURCE))

        return r

    def tpId(self): return self.TABLE_NAME
    def icon(self):
        if self.VIEW_SOURCE: return 'view'+'.gif'
        elif self.SYSTEM_FLAG: return 'stable'+'.gif'
        else: return 'table'+'.gif'
    def Type(self):
        if self.VIEW_SOURCE: return 'VIEW'
        elif self.SYSTEM_FLAG: return 'SYSTEM_TABLE'
        else: return 'TABLE'

class ProcedureBrowser(Browser, Acquisition.Implicit):
    icon='procedure'+'.gif'

    def tpValues(self):
        param = ''
        inp = [e['NAME'] + ' ' + field_to_string(e) for e in self.IN_PARAMS]
        outp = [e['NAME'] + ' ' + field_to_string(e) for e in self.OUT_PARAMS]
        if inp:
            param += '(' + join(inp, ',') + ')'
        if outp:
            param += ' RETURNS(' + join(outp, ',') + ')'

        return [SourceBrowser(self.PROCEDURE_SOURCE, param)]

    def tpId(self): return self.PROCEDURE_NAME
    def Type(self): return 'PROCEDURE'

class GeneratorBrowser(Browser, Acquisition.Implicit):
    def tpValues(self):
        return []
    def tpId(self): return self.GENERATOR_NAME
    def Type(self):
        if self.SYSTEM_FLAG == 0:
            return 'SEQUENCE'
        else:
            return 'GENERATOR'
    def icon(self):
        if self.SYSTEM_FLAG == 0:
            return 'sequence'+'.gif'
        else:
            return 'generator'+'.gif'
    def Description(self):
        return '#' + str(self.GENERATOR_COUNT)

class ColumnBrowser(Browser):
    field_icons={ 'SHORT': 'int', 'LONG': 'int', 'QUAD': 'int',
        'FLOAT': 'float', 'DATE': 'date', 'TIME': 'time', 'TEXT': 'text',
        'INT64': 'int', 'DOUBLE': 'float', 'TIMESTAMP': 'datetime',
        'VARYING': 'text', 'CSTRING': 'text', 'BLOB_ID': 'int', 'BLOB': 'bin',}
    def tpId(self): return self.NAME
    def Type(self): return self.TYPE_NAME
    def icon(self): return self.field_icons.get(self.TYPE_NAME, 'field')+'.gif'
    def Description(self):
        return field_to_string(self.__dict__)

class ConstraintBrowser(Browser):
    const_icons={'PRIMARY KEY':'key_primary', 
                'INDEX':'index', 
                'UNIQUE':'key', 
                'FOREIGN KEY':'key_foreign'}
    def tpValues(self):
        return []
    def tpId(self): return self.INDEX_NAME
    def icon(self): return self.const_icons[self.CONST_TYPE]+'.gif'
    def Name(self): return self.CONST_TYPE
    def Type(self):
        if self.CONST_NAME:
            return self.CONST_NAME
        else:
            return self.INDEX_NAME
    def Description(self): 
        s = '(' + join(self.FIELD_NAME, ',') + ')'

        if self.CONST_TYPE == 'FOREIGN KEY':
            (index_name, tab, cols) = self.FOREIGN_KEY
            s += ' REFERENCES ' + tab + '(' + join(cols, ',') + ')'
        if self.UPDATE_RULE and self.UPDATE_RULE=='CASCADE':
            s += ' ON UPDATE ' + self.UPDATE_RULE
        if self.DELETE_RULE and self.DELETE_RULE=='CASCADE':
            s += ' ON DELETE ' + self.DELETE_RULE
        return s

class CheckConstraintBrowser(Browser):
    icon='check'+'.gif'
    def tpValues(self):
        return [SourceBrowser(self.CHECK_SOURCE)]

    def tpId(self): 
        return self.CHECK_NAME
    def Name(self): return 'CHECK'
    def Type(self): return self.CHECK_NAME

class TriggerBrowser(Browser):
    icon='trigger'+'.gif'
    def _trigger_prefix(self):
        return (self.TRIGGER_TYPE + 1) & 1
    def _trigger_action_suffix(self, slot):
        suffix_types = ['', 'INSERT', 'UPDATE', 'DELETE']
        i = ((self.TRIGGER_TYPE + 1) >> (slot * 2 -1)) & 3
        return suffix_types[i]

    def tpValues(self):
        source = self._trigger_action_suffix(1)

        s = self._trigger_action_suffix(2)
        if s:
            if source: source += 'OR '
            source += s

        s = self._trigger_action_suffix(3)
        if s:
            if source: source += 'OR '
            source += s


        if self._trigger_prefix() == 0:
            source = 'BEFORE ' + source
        else:
            source = 'AFTER ' + source
        if self.TRIGGER_SOURCE:
            source += ' ' + self.TRIGGER_SOURCE
        else:
            source += ' [------ No soruce ------]' # System table

        return [SourceBrowser(source)]

    def tpId(self): 
        return self.TRIGGER_NAME
    def Type(self): return 'TRIGGER'
    def Description(self):
        return '[' + str(self.TRIGGER_SEQUENCE) + ']'

class SourceBrowser(Base, Acquisition.Implicit):
    icon=''
    Description=''

    def __init__(self, source, params=None):
        self._source=source
        self._params=params

    def tpValues(self):
        return []

    def tpId(self): return ''
    def Name(self): return ''
    def Type(self): return ''
    def Source(self): return self._source
    def Params(self): return self._params

