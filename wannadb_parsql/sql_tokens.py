from enum import Enum
from typing import List

import sqlparse.tokens as T

STRING_TYPE = "string"
NUMERIC_TYPE = "numeric"
UNKNOWN_TYPE = "unknown"
FUNC_TYPE_MAP = {
    "AVG": NUMERIC_TYPE,
    "COUNT": NUMERIC_TYPE,
    "MIN": NUMERIC_TYPE,
    "MAX": NUMERIC_TYPE,
    "SUM": NUMERIC_TYPE,
}
TTYPE_MAP = {
    T.String.Single: STRING_TYPE,
    T.Number.Integer: NUMERIC_TYPE,
}


def translate_datatype(ttype):
    if not ttype:
        return UNKNOWN_TYPE
    if ttype in TTYPE_MAP:
        return TTYPE_MAP[ttype]
    return UNKNOWN_TYPE


def get_func_type(function_name: str):
    if not function_name:
        return UNKNOWN_TYPE
    function_name = function_name.upper()
    if function_name in FUNC_TYPE_MAP:
        return FUNC_TYPE_MAP[function_name]
    return UNKNOWN_TYPE


class SQLToken:
    def __init__(self, name: str):
        self._name = name

    def __str__(self):
        return self._name

    def __repr__(self):
        return f'<NotAColumn \'{self._name}\'>'

    @staticmethod
    def is_column():
        return False

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, new_name):
        self._name = new_name


class ColumnToken(SQLToken):
    def __init__(self, value: str, datatype: str):
        super(ColumnToken, self).__init__(value)
        self.datatype = datatype

    def __str__(self):
        return self._name

    def __repr__(self):
        return f"<Column '{self._name}' '{self.datatype}'>"

    @staticmethod
    def is_column():
        return True


class SQLGroupType(Enum):
    SELECT = 'SELECT-Group'
    FROM = 'FROM-Group'
    WHERE = 'WHERE-Group'
    GROUP_BY = 'GROUP_BY-Group'
    HAVING = 'HAVING-Group'
    ORDER_BY = 'ORDER_BY-Group'
    LIMIT = 'LIMIT-Group'
    SEMICOLON = 'SEMICOLON-Group'


class SQLTokenGroup:
    def __init__(self, tokens, group_type: SQLGroupType):
        self.tokens = tokens
        self.group_type = group_type

    def __str__(self):
        return ' '.join([str(token) for token in self.tokens])

    def __repr__(self):
        return f'<{self.group_type.value}, {self.tokens}>'


class SQLStatement:
    def __init__(self, name='Query'):
        self.groups: List[SQLTokenGroup] = []
        self.name = name

    def __str__(self):
        return ' '.join([str(group) for group in self.groups])

    def __repr__(self):
        return f'<{self.name}, {self.groups}>'

    def __iter__(self):
        return iter(self.groups)

    def append(self, group: SQLTokenGroup):
        self.groups.append(group)

    def empty(self):
        return len(self.groups) == 0
