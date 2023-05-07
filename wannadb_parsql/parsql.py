from typing import Dict

import sqlparse
import sqlparse.tokens as T

from .sql_tokens import SQLToken, SQLStatement, SQLGroupType, SQLTokenGroup, ColumnToken, get_func_type, \
    translate_datatype, UNKNOWN_TYPE

DOCUMENTS_TABLE = 'documents'

SELECT = 'SELECT'
DISTINCT = 'DISTINCT'
ALL = 'ALL'

FROM = 'FROM'

# RIGHT JOIN not supported by SQLite
JOIN = 'JOIN'
LEFT_JOIN = 'LEFT JOIN'
INNER_JOIN = 'INNER JOIN'
CROSS_JOIN = 'CROSS JOIN'
ANY_JOIN = [JOIN, LEFT_JOIN, INNER_JOIN, CROSS_JOIN]
ON = 'ON'

WHERE = 'WHERE'

GROUP_BY = 'GROUP BY'
HAVING = 'HAVING'

ORDER_BY = 'ORDER BY'
ASC = 'ASC'
DESC = 'DESC'

LIMIT = 'LIMIT'
OFFSET = 'OFFSET'

IN = 'IN'
NOT = 'NOT'
OR = 'OR'
AND = 'AND'

ASTERISK = '*'
PAREN_OPEN = '('
PAREN_CLOSE = ')'
COMMA = ','
SEMICOLON = ';'


class InvalidSQLError(Exception):
    """
    Raised when the SQL statement is ill-formed.
    """

    def __init__(self, statement: str, got: str):
        self.statement = statement
        self.got = got

    def __str__(self):
        return f"SQL statement ill-formed: Token '{self.got}' in '{self.statement}' is not allowed"


class SQLSyntaxError(Exception):
    """
    Raised when an expected token is not found while parsing.
    Includes information about the SQL statement, the expected token, the actual token
    and the location, i.e. previous token, within the statement.
    """

    def __init__(self, statement: str, expected: str, got: str, near: str):
        self.statement = statement
        self.expected = expected
        self.got = got
        self.near = near

    def __str__(self):
        return f"Unexpected token in '{self.statement}'; expected '{self.expected}' " \
               f"but got '{self.got}' near '{self.near}'"


class SQLSemanticError(Exception):
    """
    Raised when a semantic error is not found while parsing, e.g. ambiguous datatype of a column.
    Includes information about the SQL statement, the expected context, the actual context
    and the location, i.e. previous token, within the statement.
    """

    def __init__(self, statement: str, expected: str, got: str, near: str):
        self.statement = statement
        self.expected = expected
        self.got = got
        self.near = near

    def __str__(self):
        return f"Semantic error in '{self.statement}'; expected '{self.expected}' " \
               f"but got '{self.got}' near '{self.near}'"


class Parser:
    def __init__(self):
        self.parsed_statement: str = ""
        self.token_generator = None
        self.current_token = None
        self.last_token = None
        self.current_idx = 0
        self.columns: Dict[str, ColumnToken] = dict()
        self.parsed_tokens = []
        self.parsed_groups = None

    def parse(self, statement: str):
        """
        Extracts the columns from the statement passed to this parser in the constructor.

        :param statement: SQL SELECT statement
        :raises ValueError: if more than 1 SQL statement was given in the statement string or if the string is empty
        :raises SQLSyntaxError: if the SQL statement is syntactically incorrect
        :raises SQLSemanticError: if the SQL statement is semantically incorrect (ambiguous datatypes)
        :returns: List of extracted columns (SQLTokens), SQLStatement
        """

        self.parsed_statement = statement
        self._validate_statement(statement)

        parsed_statements = sqlparse.parse(statement)
        if len(parsed_statements) != 1:
            raise ValueError(f"Expected exactly 1 SQL statement, got {len(parsed_statements)}")
        self.token_generator = parsed_statements[0].flatten()
        self.current_idx = 0
        self.current_token = next(self.token_generator, None)
        self.columns: Dict[str, ColumnToken] = dict()
        self.parsed_groups = SQLStatement()
        self._consume_statement()

        if self.current_token is not None:
            self._raise_syntax_error("end of statement")
        assert (len(self.parsed_tokens) == 0)
        result_columns = list(self.columns.values())

        return result_columns, self.parsed_groups

    @staticmethod
    def _validate_statement(statement: str):
        if len(statement) == 0:
            raise ValueError("SQL statement must not be empty")
        if statement.find("\"") != -1:
            raise InvalidSQLError(statement, "\"")

    def _error_near_token(self):
        if self.last_token is None:
            near = "start"
        else:
            near = self.last_token.value
        return near

    def _raise_syntax_error(self, expected: str):
        raise SQLSyntaxError(self.parsed_statement, expected, self.current_token.value, self._error_near_token())

    def _raise_semantic_error(self, expected: str, got: str):
        raise SQLSemanticError(self.parsed_statement, expected, got, self._error_near_token())

    def _stash_token(self, token):
        if not token.is_group or len(token.tokens) == 1:
            stashed_token = SQLToken(token.value)
            self.parsed_tokens.append(stashed_token)

    def _stash_group(self, group_type: SQLGroupType):
        self.parsed_groups.append(SQLTokenGroup(self.parsed_tokens, group_type))
        self.parsed_tokens = []

    def _next_token(self, stash=True):
        if stash:
            self._stash_token(self.current_token)
        idx = self.current_idx
        while True:
            next_token = next(self.token_generator, None)
            idx += 1
            if next_token is None or not next_token.match(T.Whitespace, None):
                self.last_token = self.current_token
                self.current_idx, self.current_token = idx, next_token
                break
            elif not next_token.match(T.Whitespace, None):
                self._stash_token(next_token)

    def _is_current_token_equal_to(self, *expected: str) -> bool:
        if self.current_token is None:
            return False
        for exp in expected:
            if exp is not None and exp.casefold() == self.current_token.value.casefold():
                return True
        return False

    def _consume_statement(self):
        self._consume_token(SELECT)
        if self._optional_consume_any_of(DISTINCT):
            if self._optional_consume_any_of(PAREN_OPEN):
                self._consume_columns()
                self._consume_token(PAREN_CLOSE)
                if self._optional_consume_any_of(COMMA):
                    self._consume_columns()
            else:
                self._consume_columns()
        else:
            self._optional_consume_any_of(ALL)
            self._consume_columns()

        self._stash_group(SQLGroupType.SELECT)
        if self._optional_consume_any_of(FROM):
            self._consume_from()
            self._stash_group(SQLGroupType.FROM)

        if self._optional_consume_any_of(WHERE):
            self._consume_where()
            self._stash_group(SQLGroupType.WHERE)

        if self._optional_consume_any_of(GROUP_BY):
            self._consume_group_by()
            self._stash_group(SQLGroupType.GROUP_BY)
            if self._optional_consume_any_of(HAVING):
                self._consume_having()
                self._stash_group(SQLGroupType.HAVING)

        if self._optional_consume_any_of(ORDER_BY):
            self._consume_order_by()
            self._stash_group(SQLGroupType.ORDER_BY)

        if self._optional_consume_any_of(LIMIT):
            self._consume_limit()
            self._stash_group(SQLGroupType.LIMIT)

        if self._optional_consume_any_of(SEMICOLON):
            self._stash_group(SQLGroupType.SEMICOLON)

    def _consume_token(self, token: str):
        if not self._is_current_token_equal_to(token):
            self._raise_syntax_error(token)

        self._next_token()

    def _optional_consume_any_of(self, *tokens: str) -> bool:
        for token in tokens:
            if self.current_token is None:
                break
            if self._is_current_token_equal_to(token):
                self._next_token()
                return True

        return False

    def _consume_columns(self):
        while self.current_token is not None:
            self._consume_function_or_column()
            if not self._optional_consume_any_of(COMMA):
                break

    def _consume_function_or_column(self, datatype=UNKNOWN_TYPE) -> (str, str):
        # Possible extension here: allow table name, e.g. "documents.aircraft"

        table_name = None
        current_token = self.current_token
        self._next_token(stash=False)

        is_function = False
        if self.current_token is not None and self._is_current_token_equal_to(PAREN_OPEN):
            is_function = True
            datatype = get_func_type(current_token.value)
            self._stash_token(current_token)
            self._next_token()
            current_token = self.current_token

        should_stash = False
        if self._is_current_token_equal_to(ASTERISK):
            if not is_function:
                raise NotImplementedError("Selecting all fields is currently not supported")
            should_stash = True
        else:
            if current_token.match(T.Literal.Number.Integer, None) or current_token.match(T.Literal.String.Single,
                                                                                          None):
                self._stash_token(current_token)
            else:
                # here we have a column identifier
                table_name = current_token.value
                if table_name in self.columns:
                    stashed_token = self.columns[table_name]
                    if datatype != UNKNOWN_TYPE:
                        if stashed_token.datatype != UNKNOWN_TYPE and stashed_token.datatype != datatype:
                            self._raise_semantic_error(stashed_token.datatype, datatype)
                    else:
                        datatype = stashed_token.datatype

                self.columns[table_name] = ColumnToken(table_name, datatype)
                self.parsed_tokens.append(ColumnToken(table_name, datatype))

        if is_function:
            self._next_token(stash=should_stash)
            self._consume_token(PAREN_CLOSE)

        # Possible extension here: allow AS + identifier, e.g. "aircraft AS ac"

        return table_name, datatype

    def _consume_from(self):
        if self._optional_consume_any_of(DOCUMENTS_TABLE):
            pass
        elif self._optional_consume_any_of(PAREN_OPEN):
            self._consume_substatement()
            self._consume_token(PAREN_CLOSE)
        else:
            self._raise_syntax_error(f"{DOCUMENTS_TABLE} or subquery")

        if self._optional_consume_any_of(*ANY_JOIN):
            self._consume_join()

    def _consume_join(self):
        if self._optional_consume_any_of(DOCUMENTS_TABLE):
            pass
        elif self._optional_consume_any_of(PAREN_OPEN):
            self._consume_substatement()
            self._consume_token(PAREN_CLOSE)
        else:
            self._raise_syntax_error("'documents' or subquery")

        if self._optional_consume_any_of(ON):
            self._consume_expr()

    def _consume_expr(self, datatype=UNKNOWN_TYPE) -> str:
        column_name, column_datatype = None, UNKNOWN_TYPE
        self._optional_consume_any_of(NOT)
        if self._optional_consume_any_of(PAREN_OPEN):
            if self._is_current_token_equal_to(SELECT):
                self._consume_substatement()
            else:
                self._consume_expr(datatype)
            self._consume_token(PAREN_CLOSE)
        else:
            if self.current_token.match(T.Number.Integer, None):
                self._next_token()
                numeric_datatype = translate_datatype(T.Number.Integer)
                if datatype != UNKNOWN_TYPE and datatype != numeric_datatype:
                    self._raise_semantic_error(datatype, numeric_datatype)
                datatype = numeric_datatype
            elif self.current_token.match(T.String.Single, None):
                self._next_token()
                string_datatype = translate_datatype(T.String.Single)
                if datatype != UNKNOWN_TYPE and datatype != string_datatype:
                    self._raise_semantic_error(datatype, string_datatype)
                datatype = string_datatype
            else:
                column_name, column_datatype = self._consume_function_or_column(datatype)
                datatype = self._common_datatype(datatype, column_datatype)

        right_datatype = UNKNOWN_TYPE
        if self.current_token is not None:
            if self._optional_consume_any_of(AND, OR, IN):
                self._consume_expr(UNKNOWN_TYPE)
            elif self.current_token.match(T.Operator, None) or self.current_token.match(T.Comparison, None):
                self._next_token()
                right_datatype = self._consume_expr(datatype)
                if datatype != UNKNOWN_TYPE and datatype != right_datatype:
                    self._raise_semantic_error(datatype, right_datatype)
                if column_name is not None:
                    # sanity check, will raise error if datatypes are incompatible
                    new_datatype = self._common_datatype(self.columns[column_name].datatype, right_datatype)
                    self.columns[column_name].datatype = new_datatype
            elif self.current_token.match(T.Literal.Number.Integer, None):
                if not self.current_token.value.startswith('-'):
                    self._raise_syntax_error("Operator")
                self._next_token()

        return self._common_datatype(datatype, right_datatype)

    def _common_datatype(self, left_datatype: str, right_datatype: str) -> str:
        if left_datatype is not None and left_datatype != UNKNOWN_TYPE:
            if right_datatype is not None and right_datatype != UNKNOWN_TYPE:
                if left_datatype != right_datatype:
                    self._raise_semantic_error(left_datatype, right_datatype)
                return left_datatype
            return left_datatype
        return right_datatype

    def _consume_integer(self):
        if not self.current_token.match(T.Literal.Number.Integer, None):
            self._raise_syntax_error("Integer")
        self._next_token()

    def _consume_where(self):
        self._consume_expr()

    def _consume_group_by(self):
        self._consume_columns()

    def _consume_having(self):
        self._consume_expr()

    def _consume_order_by(self):
        self._consume_function_or_column()
        self._optional_consume_any_of(ASC, DESC)

    def _consume_limit(self):
        self._consume_integer()
        if self._optional_consume_any_of(COMMA, OFFSET):
            self._consume_integer()

    def _consume_substatement(self):
        parent_token_groups = self.parsed_groups
        self.parsed_groups = SQLStatement('Subquery')
        parent_token_stash = self.parsed_tokens
        self.parsed_tokens = []

        self._consume_statement()

        assert len(self.parsed_tokens) == 0
        self.parsed_tokens = parent_token_stash
        self.parsed_tokens.append(self.parsed_groups)
        self.parsed_groups = parent_token_groups
