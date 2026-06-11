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
"""ISQL meta command translation.

isql supports a handful of meta commands (``show tables``,
``show table NAME``, ``show procedures``, ``show procedure NAME``,
``show version``, ...) that plain Firebird SQL does not understand. In
the ZMI Test tab of the FirebirdDA Connection we translate them into
real system-table queries so they work the same way as in isql. Object
lists (tables, views, procedures, functions, triggers, generators,
domains, exceptions) and the ``show version``/``show database`` info
commands are exact matches in ``ISQL_META_COMMANDS``. The parameterised
variants are handled by ``translate_isql_meta()``: ``show table NAME``
(column list) and ``show procedure/view/trigger/function NAME`` (the
object's source, defined in ``SOURCE_OBJECTS`` and rendered as a <pre>
block by the DA layer).
"""
import re


ISQL_META_COMMANDS = {
    'show tables': (
        "SELECT TRIM(RDB$RELATION_NAME) AS TABLE_NAME "
        "FROM RDB$RELATIONS "
        "WHERE RDB$SYSTEM_FLAG = 0 AND RDB$VIEW_BLR IS NULL "
        "ORDER BY RDB$RELATION_NAME"
    ),
    'show views': (
        "SELECT TRIM(RDB$RELATION_NAME) AS VIEW_NAME "
        "FROM RDB$RELATIONS "
        "WHERE RDB$SYSTEM_FLAG = 0 AND RDB$VIEW_BLR IS NOT NULL "
        "ORDER BY RDB$RELATION_NAME"
    ),
    'show procedures': (
        "SELECT TRIM(RDB$PROCEDURE_NAME) AS PROCEDURE_NAME "
        "FROM RDB$PROCEDURES "
        "WHERE RDB$SYSTEM_FLAG = 0 "
        "ORDER BY RDB$PROCEDURE_NAME"
    ),
    'show functions': (
        "SELECT TRIM(RDB$FUNCTION_NAME) AS FUNCTION_NAME "
        "FROM RDB$FUNCTIONS "
        "WHERE RDB$SYSTEM_FLAG = 0 "
        "ORDER BY RDB$FUNCTION_NAME"
    ),
    'show triggers': (
        "SELECT TRIM(RDB$TRIGGER_NAME) AS TRIGGER_NAME "
        "FROM RDB$TRIGGERS "
        "WHERE RDB$SYSTEM_FLAG = 0 "
        "ORDER BY RDB$TRIGGER_NAME"
    ),
    'show generators': (
        "SELECT TRIM(RDB$GENERATOR_NAME) AS GENERATOR_NAME "
        "FROM RDB$GENERATORS "
        "WHERE RDB$SYSTEM_FLAG = 0 "
        "ORDER BY RDB$GENERATOR_NAME"
    ),
    'show domains': (
        "SELECT TRIM(RDB$FIELD_NAME) AS DOMAIN_NAME "
        "FROM RDB$FIELDS "
        "WHERE RDB$SYSTEM_FLAG = 0 "
        "AND RDB$FIELD_NAME NOT STARTING WITH 'RDB$' "
        "ORDER BY RDB$FIELD_NAME"
    ),
    'show exceptions': (
        "SELECT TRIM(RDB$EXCEPTION_NAME) AS EXCEPTION_NAME "
        "FROM RDB$EXCEPTIONS "
        "WHERE RDB$SYSTEM_FLAG = 0 "
        "ORDER BY RDB$EXCEPTION_NAME"
    ),
    'show version': (
        "SELECT rdb$get_context('SYSTEM', 'ENGINE_VERSION') AS VERSION "
        "FROM RDB$DATABASE"
    ),
    'show database': (
        "SELECT "
        "rdb$get_context('SYSTEM', 'DB_NAME') AS DATABASE_NAME, "
        "rdb$get_context('SYSTEM', 'ENGINE_VERSION') AS ENGINE_VERSION, "
        "rdb$get_context('SYSTEM', 'CURRENT_USER') AS CURRENT_USER "
        "FROM RDB$DATABASE"
    ),
}


# Firebird RDB$FIELDS.RDB$FIELD_TYPE -> readable SQL type name.
# Covers the common column types; unknown types are emitted as a
# numeric code.
FB_FIELD_TYPE_CASE = """
  CASE f.RDB$FIELD_TYPE
    WHEN 7 THEN
      CASE f.RDB$FIELD_SUB_TYPE
        WHEN 1 THEN 'NUMERIC(' || f.RDB$FIELD_PRECISION || ',' ||
                    (-f.RDB$FIELD_SCALE) || ')'
        WHEN 2 THEN 'DECIMAL(' || f.RDB$FIELD_PRECISION || ',' ||
                    (-f.RDB$FIELD_SCALE) || ')'
        ELSE 'SMALLINT'
      END
    WHEN 8 THEN
      CASE f.RDB$FIELD_SUB_TYPE
        WHEN 1 THEN 'NUMERIC(' || f.RDB$FIELD_PRECISION || ',' ||
                    (-f.RDB$FIELD_SCALE) || ')'
        WHEN 2 THEN 'DECIMAL(' || f.RDB$FIELD_PRECISION || ',' ||
                    (-f.RDB$FIELD_SCALE) || ')'
        ELSE 'INTEGER'
      END
    WHEN 10 THEN 'FLOAT'
    WHEN 12 THEN 'DATE'
    WHEN 13 THEN 'TIME'
    WHEN 14 THEN 'CHAR(' || f.RDB$CHARACTER_LENGTH || ')'
    WHEN 16 THEN
      CASE f.RDB$FIELD_SUB_TYPE
        WHEN 1 THEN 'NUMERIC(' || f.RDB$FIELD_PRECISION || ',' ||
                    (-f.RDB$FIELD_SCALE) || ')'
        WHEN 2 THEN 'DECIMAL(' || f.RDB$FIELD_PRECISION || ',' ||
                    (-f.RDB$FIELD_SCALE) || ')'
        ELSE 'BIGINT'
      END
    WHEN 27 THEN 'DOUBLE PRECISION'
    WHEN 35 THEN 'TIMESTAMP'
    WHEN 37 THEN 'VARCHAR(' || f.RDB$CHARACTER_LENGTH || ')'
    WHEN 261 THEN
      'BLOB SUB_TYPE ' ||
      CASE f.RDB$FIELD_SUB_TYPE
        WHEN 0 THEN 'BINARY'
        WHEN 1 THEN 'TEXT'
        ELSE CAST(f.RDB$FIELD_SUB_TYPE AS VARCHAR(10))
      END
    ELSE 'TYPE_' || CAST(f.RDB$FIELD_TYPE AS VARCHAR(10))
  END
"""

# Query for "show table NAME": column list with type, length, nullability,
# default. {name} is filled in by the translator with the validated table
# name (always pre-validated, so no SQL-injection risk).
SHOW_TABLE_SQL = (
    "SELECT "
    "TRIM(rf.RDB$FIELD_NAME) AS FIELD_NAME, "
    + FB_FIELD_TYPE_CASE.strip() + " AS FIELD_TYPE, "
    "CASE WHEN COALESCE(rf.RDB$NULL_FLAG, f.RDB$NULL_FLAG) = 1 "
    "THEN 'NOT NULL' ELSE '' END AS NULLABLE, "
    "COALESCE(rf.RDB$DEFAULT_SOURCE, f.RDB$DEFAULT_SOURCE) AS DEFAULT_VALUE "
    "FROM RDB$RELATION_FIELDS rf "
    "JOIN RDB$FIELDS f ON rf.RDB$FIELD_SOURCE = f.RDB$FIELD_NAME "
    "WHERE rf.RDB$RELATION_NAME = '{name}' "
    "ORDER BY rf.RDB$FIELD_POSITION"
)

# Identifier fragment shared by the "show <kind> NAME" commands: a quoted
# "Name" (case kept) or an unquoted name (upper-cased by the translator).
_NAME_RE = r'(?:"(?P<quoted>[^"]+)"|(?P<unquoted>[A-Za-z][A-Za-z0-9_$]*))'

SHOW_TABLE_RE = re.compile(
    r'^show\s+table\s+' + _NAME_RE + r'\s*;?\s*$', re.IGNORECASE)

# "show procedure/view/trigger/function NAME": the object's source body,
# returned as a single SOURCE cell and rendered <pre> by the DA layer
# (Connection.manage_testForm). Maps the keyword to (system table, name
# column, source column). RDB$FUNCTION_SOURCE requires Firebird 3+.
SOURCE_OBJECTS = {
    'procedure': ('RDB$PROCEDURES', 'RDB$PROCEDURE_NAME', 'RDB$PROCEDURE_SOURCE'),
    'view':      ('RDB$RELATIONS',  'RDB$RELATION_NAME',  'RDB$VIEW_SOURCE'),
    'trigger':   ('RDB$TRIGGERS',   'RDB$TRIGGER_NAME',   'RDB$TRIGGER_SOURCE'),
    'function':  ('RDB$FUNCTIONS',  'RDB$FUNCTION_NAME',  'RDB$FUNCTION_SOURCE'),
}

SHOW_SOURCE_RE = re.compile(
    r'^show\s+(?P<kind>' + '|'.join(SOURCE_OBJECTS) + r')\s+'
    + _NAME_RE + r'\s*;?\s*$', re.IGNORECASE)


def _validated_object_name(match):
    """Return the validated identifier from a "show <kind> NAME" match.

    Unquoted identifiers are upper-cased (Firebird stores them that way
    in the system tables); quoted identifiers keep their case. Returns
    None if the name contains an apostrophe -- a string terminator and
    our SQL-injection safety net. Quoted identifiers may legitimately
    contain spaces etc., so only the apostrophe is blocked.
    """
    quoted = match.group('quoted')
    name = quoted if quoted is not None else match.group('unquoted').upper()
    if "'" in name:
        return None
    return name


def translate_isql_meta(query_string):
    """Translate an ISQL meta command to a Firebird SQL query.

    If query_string matches a known ISQL meta command
    (case-insensitive, whitespace normalised, optional trailing ';'),
    return the corresponding Firebird SQL query.  Otherwise return
    None.
    """
    stripped = query_string.strip()
    # 1) Exact matches (show tables / show procedures / show version / ...)
    key = ' '.join(stripped.rstrip(';').strip().lower().split())
    sql = ISQL_META_COMMANDS.get(key)
    if sql is not None:
        return sql
    # 2) show table NAME (column list).
    m = SHOW_TABLE_RE.match(stripped)
    if m:
        name = _validated_object_name(m)
        return SHOW_TABLE_SQL.format(name=name) if name is not None else None
    # 3) show procedure/view/trigger/function NAME (object source).
    m = SHOW_SOURCE_RE.match(stripped)
    if m:
        name = _validated_object_name(m)
        if name is None:
            return None
        table, name_col, source_col = SOURCE_OBJECTS[m.group('kind').lower()]
        return ("SELECT {col} AS SOURCE FROM {tbl} "
                "WHERE {namecol} = '{name}'").format(
                    col=source_col, tbl=table, namecol=name_col, name=name)
    return None


def source_object_name(query_string):
    """Return the validated name if query_string is a "show <kind> NAME"
    command that returns an object's source (procedure/view/trigger/
    function), else None.

    The DA layer (Connection.manage_testForm) uses this to recognise such
    commands and render the source with whitespace preserved; the SQL
    translation itself happens in translate_isql_meta() above.
    """
    m = SHOW_SOURCE_RE.match(query_string.strip())
    if m is None:
        return None
    return _validated_object_name(m)
