from typing import List, Optional, Union, Tuple

from wannadb_parsql.parsql import ColumnToken, SQLGroupType, SQLStatement, SQLToken, SQLTokenGroup, Parser

DOCUMENT_ID = "doc_id"


def rewrite_query(columns: List[ColumnToken], parsed: SQLStatement) -> Tuple[List[ColumnToken], str]:
    """Rewrites a given user-specified SQL query to a valid SQL query that can be executed on the WannaDB cache DB.
    Note that this method rewrites the given query in-place.

    :param columns: List of tokens that represents the attributes in the query.
    :type columns: List[ColumnToken]
    :param parsed: SQL query as returned by Parser.parse().
    :type parsed: SQLStatement
    :return: Tuple containing the original (not rewritten) columns and the rewritten SQL query.
    :rtype: Union[List[ColumnToken], str]
    """
    # Preserve original column names
    attributes = list(map(lambda column: column.name, columns))
    # Rewrite FROM clause
    _rewrite_from_clause(parsed, attributes)
    # Rewrite column names: "SELECT name ..." -> "SELECT name.value as name ..."
    _rewrite_columns(parsed)
    # Add a ";" at the very end if not present
    if ";" not in parsed.groups[-1].tokens[-1].name:
        parsed.groups[-1].tokens.append(SQLToken(";"))

    return columns, str(parsed)


def _rewrite_from_clause(parsed, attributes):
    if not isinstance(parsed, SQLStatement):
        raise ValueError("Given argument is not a SQLStatement.")

    found_from = False
    for group in parsed.groups:
        if group.group_type == SQLGroupType.FROM:
            found_from = True
            subquery = _get_subquery(group)
            if subquery is not None:
                _rewrite_from_clause(subquery, attributes)
            else:
                group.tokens = _build_new_from_clause(attributes)

    if not found_from:
        # In case there was only a select clause, it might end with a ";". Make sure to remove it.
        if len(parsed.groups) == 1 and ";" in parsed.groups[0].tokens[-1].name:
            parsed.groups[0].tokens = parsed.groups[0].tokens[:-1]
        tokens = _build_new_from_clause(attributes)
        parsed.groups.insert(1, SQLTokenGroup(tokens, SQLGroupType.FROM))


def _rewrite_columns(parsed):
    if not isinstance(parsed, SQLStatement):
        raise ValueError("Given argument is not a SQLStatement.")

    # First look if we have a FROM clause that might hold a subquery.
    from_clause = next(filter(lambda group: group.group_type == SQLGroupType.FROM, parsed.groups), None)
    if from_clause is not None:
        subquery = _get_subquery(from_clause)
    else:
        subquery = None

    # We only want to rewrite the subquery furthest down in the hierarchy.
    if subquery is not None:
        _rewrite_columns(subquery)
    else:
        for group in parsed.groups:
            new_tokens = []
            for token in group.tokens:
                if isinstance(token, ColumnToken):
                    # If column stands within a SELECT clause, we need to preserve the original name via "as <name>"
                    if group.group_type == SQLGroupType.SELECT:
                        new_name = f"{token.name}.value as {token.name}"
                    else:
                        new_name = f"{token.name}.value"
                    new_tokens.append(ColumnToken(new_name, token.datatype))
                else:
                    new_tokens.append(token)
            group.tokens = new_tokens


def _get_subquery(group: SQLTokenGroup) -> Optional[SQLStatement]:
    for token in group.tokens:
        if isinstance(token, SQLStatement):
            return token
    return None


def _build_new_from_clause(attributes) -> List[SQLToken]:
    tokens = [SQLToken("FROM")]
    for i, attribute in enumerate(attributes):
        if i != 0:
            # "<column1> INNER JOIN <column2> USING (<doc_id>)"
            tokens += [
                SQLToken("LEFT JOIN"),
                SQLToken(attribute),
                SQLToken("USING"),
                SQLToken("("),
                SQLToken(DOCUMENT_ID),
                SQLToken(")"),
            ]
        else:
            tokens.append(SQLToken(attribute))
    return tokens


def update_query_attribute_list(parsed_query, new_attributes_list: List[str]) -> str:
    _, parsed_attrs_only = Parser().parse(f"SELECT {', '.join(new_attributes_list)}")

    for sql_token_group in parsed_query.groups:
        if sql_token_group.group_type == SQLGroupType.SELECT:
            sql_token_group.tokens = parsed_attrs_only.groups[0].tokens

    return str(parsed_query).replace(" ,", ",")
