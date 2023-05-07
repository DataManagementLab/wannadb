import os
import sqlite3
from pathlib import Path
from sqlite3 import Error
from typing import List, Any, Generator

import pandas as pd

from .parsql import ColumnToken
from .rewrite import DOCUMENT_ID
from .sql_tokens import UNKNOWN_TYPE


def create_connection(db_file):
    """ create a database connection to the SQLite database
        specified by db_file
    :param db_file: database file
    :return: Connection object or None
    """
    conn = None
    try:
        conn = sqlite3.connect(db_file, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    except Error as e:
        print(e)

    return conn


def alter_table(conn, entry):
    if entry["type"] is None:
        entry["type"] = 'text'
    sql = ''' ALTER TABLE {} ADD COLUMN {} {}'''.format(entry["table"], entry["attribute"], entry["type"])
    cur = conn.cursor()
    cur.execute(sql)
    conn.commit()
    return cur.lastrowid


class SQLiteCacheDB:

    def __init__(self, db_file="wannadb_cache.db"):
        self.db_file = db_file
        self.conn = create_connection(self.db_file)

    def existing_tables(self):
        c = self.conn.cursor()
        c.execute("select name from sqlite_master where type = 'table';")
        # name of all existing tables
        return [str(row[0]).lower() for row in c.fetchall()]

    def table_empty(self, attribute_name):
        c = self.conn.cursor()
        c.execute(f'SELECT * FROM {attribute_name}')
        return c.fetchone() is None

    def create_tables(self, attributes: List[ColumnToken]):
        for attribute in attributes:
            self.create_table(attribute)

    def create_table_by_name(self, attribute_name):
        self.create_table(ColumnToken(attribute_name, UNKNOWN_TYPE))

    def create_table(self, attribute: ColumnToken):
        if self.conn is None:
            raise EnvironmentError("No database connection found.")
        data = []

        data.append({"table": attribute.name, "attribute": "value", "type": attribute.datatype})
        data.append({"table": attribute.name, "attribute": DOCUMENT_ID, "type": "integer"})

        tableName = attribute.name

        try:
            c = self.conn.cursor()
            c.execute(
                ''' SELECT count(name) FROM sqlite_master WHERE type='table' AND name='{}' '''.format(tableName))
        except Error as e:
            print(e)

        # if the count is 1, then table exists and does not need to be created again
        if c.fetchone()[0] != 1:

            sql_create_table = """ CREATE TABLE IF NOT EXISTS {} (
                                            id integer PRIMARY KEY
                                        )""".format(tableName)

            try:
                c = self.conn.cursor()
                c.execute(sql_create_table)
            except Error as e:
                print(e)

            with self.conn:
                for entry in data:
                    # Insert the attributes
                    alter_table(self.conn, entry)

    def create_input_docs_table(self, table_name, documents):
        self.create_table_by_name(table_name)
        self.store_many(table_name, ((i, Path(doc.name).name) for i, doc in enumerate(documents)))

    def delete_tables(self, attributes: List[ColumnToken]):
        c = self.conn.cursor()
        for attribute in attributes:
            c.execute(''' DELETE FROM {}  '''.format(attribute.name))

    def delete_table(self, attribute):
        self.conn.execute(f"DROP TABLE IF EXISTS {attribute}")

    def execute_queries(self, *queries) -> List[pd.DataFrame]:
        res = []

        for query in queries:
            cur = self.conn.cursor()
            cur.execute(query)

            data = []
            for row in cur.fetchall():
                entry = {}
                for key in row.keys():
                    entry[key] = row[key]
                data.append(entry)
            res.append(pd.DataFrame(data))

        return res

    def store_many(self, attr, iter: Generator[tuple[int, Any], None, None]):
        self.conn.executemany(f"INSERT INTO {attr}({DOCUMENT_ID}, value) VALUES (?, ?)", iter)

    def store_and_split_entry(self, data):
        for doc_idx, item in enumerate(data):

            question_marks = ",".join(["?"] * 2)
            attrs = []
            val = []
            for attribute, value in item.items():
                attrs = [DOCUMENT_ID, "value"]
                val = [doc_idx, value]
                sql = ' INSERT INTO ' + attribute + "(" + ",".join(attrs) + ")" + ' VALUES(' + question_marks + ')'

                cur = self.conn.cursor()
                cur.execute(sql, val)
                self.conn.commit()

    def drop_all_and_reconnect(self):
        self.conn.close()
        os.remove(self.db_file)
        # creating a new connection will recreate the DB file
        self.conn = create_connection(self.db_file)
