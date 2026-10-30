"""Durable local THQ cloud storage for the loopback emulator.

Wire tuples were recovered from DS2 serializers b3280a, b32450, b05f18,
b05e49. Authentication is outside this loopback research component.
"""
import json
import sqlite3
import time
from contextlib import contextmanager


class UnsupportedRequest(ValueError):
    pass


class CloudStore:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS documents '
                       '(profile TEXT, doc TEXT, value TEXT, policy INTEGER, modified INTEGER, '
                       'PRIMARY KEY(profile,doc))')
            db.execute('CREATE TABLE IF NOT EXISTS entries '
                       '(profile TEXT, doc TEXT, key TEXT, value TEXT, modified INTEGER, '
                       'PRIMARY KEY(profile,doc,key))')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute('PRAGMA synchronous=FULL')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def parameters(params):
        def one(name, default=''):
            values = params.get(name, [default])
            if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], str):
                raise UnsupportedRequest('Ambiguous parameter')
            return values[0]

        ops = one('ops').split(',')
        if not 1 <= len(ops) <= 100:
            raise UnsupportedRequest('Invalid batch size')
        allowed = {'GET', 'SET', 'MAP_GET', 'MAP_SET', 'MAP_REMOVE'}
        if any(op not in allowed for op in ops):
            raise UnsupportedRequest('Unsupported operation')
        fields = {}
        for name in ('profileNames', 'docKeys', 'keys', 'values', 'policy'):
            raw = one(name)
            values = [raw] if len(ops) == 1 else raw.split(',')
            if len(values) != len(ops):
                raise UnsupportedRequest('Ambiguous batch delimiter')
            fields[name] = values
        if any(not doc for doc in fields['docKeys']):
            raise UnsupportedRequest('Missing document')
        return ops, fields

    def execute(self, params):
        ops, f = self.parameters(params)
        results = []
        now = int(time.time())
        # Commit every write before returning success. Any unsupported member
        # aborts the whole batch. Keys are bound SQL values, never filesystem paths.
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for i, op in enumerate(ops):
                profile, doc, key, value = (f[n][i] for n in
                                           ('profileNames', 'docKeys', 'keys', 'values'))
                document = ''
                policy = 0
                modified = 0
                if op == 'MAP_GET':
                    rows = db.execute('SELECT key,value,modified FROM entries WHERE '
                                      'profile=? AND doc=? ORDER BY key', (profile, doc)).fetchall()
                    if rows:
                        document = json.dumps([[k, [v, '', t]] for k, v, t in rows],
                                              separators=(',', ':'), ensure_ascii=False)
                        modified = max(row[2] for row in rows)
                elif op == 'GET':
                    row = db.execute('SELECT value,policy,modified FROM documents '
                                     'WHERE profile=? AND doc=?', (profile, doc)).fetchone()
                    if row is None:
                        # Missing-document status enum has not been established.
                        raise UnsupportedRequest('Missing document status unverified')
                    document, policy, modified = row
                elif op == 'SET':
                    try:
                        policy = int(f['policy'][i] or '0')
                    except ValueError as exc:
                        raise UnsupportedRequest('Invalid policy') from exc
                    db.execute('INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?)',
                               (profile, doc, value, policy, now))
                    modified = now
                elif op == 'MAP_SET':
                    if not key:
                        raise UnsupportedRequest('Missing map key')
                    db.execute('INSERT OR REPLACE INTO entries VALUES (?,?,?,?,?)',
                               (profile, doc, key, value, now))
                    modified = now
                elif op == 'MAP_REMOVE':
                    if not key:
                        raise UnsupportedRequest('Missing map key')
                    db.execute('DELETE FROM entries WHERE profile=? AND doc=? AND key=?',
                               (profile, doc, key))
                    modified = now
                results.append([0, document, policy, modified, ''])
        return [0, results]
