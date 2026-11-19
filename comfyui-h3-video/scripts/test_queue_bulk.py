"""Synthetic bulk transactions: no live server, user history or media is read."""
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'simple_ui'))
from queue_bulk import BuildCache, QueueBulkEditor


class Backend:
    def __init__(self, count=3):
        self.pending = [[n, f'synthetic-{n}', {'node': {'value': n}},
                         {'client_id': 'original', 'synthetic_metadata': n}, []] for n in range(count)]
        self.running = []
        self.history = {}
        self.calls = []
        self.queue_bytes = 0
        self.race = self.reject = self.lost_ack = self.ignore = self.stale = None
        self.unsupported = self.verification_unavailable = False
        self.finish = False

    def response(self, value):
        return io.BytesIO(json.dumps(value).encode())

    def request(self, path, data=None, headers=None):
        body = json.loads(data) if data else None
        self.calls.append((path, body))
        if path == '/queue' and body is None:
            if self.verification_unavailable and any(p == '/prompt' for p, _ in self.calls):
                raise urllib.error.URLError('Synthetic unavailable readback')
            result = self.response({'queue_pending': self.pending, 'queue_running': self.running})
            self.queue_bytes += len(result.getvalue())
            return result
        if path.startswith('/api/jobs/'):
            pid = path.rsplit('/', 1)[1]
            if self.unsupported:
                raise urllib.error.HTTPError(path, 404, 'Unsupported', {}, io.BytesIO(b'404: Not Found'))
            status = next(('in_progress' for row in self.running if row[1] == pid), None)
            status = status or next(('pending' for row in self.pending if row[1] == pid), None)
            status = status or ('completed' if pid in self.history else None)
            if status:
                return self.response({'id': pid, 'status': status})
            raise urllib.error.HTTPError(path, 404, 'Absent', {}, self.response({'error': 'Job not found'}))
        if path.startswith('/history/'):
            pid = path.rsplit('/', 1)[1]
            return self.response({pid: {'prompt': self.history[pid]}} if pid in self.history else {})
        if path == '/queue':
            for pid in body['delete']:
                row = next((row for row in self.pending if row[1] == pid), None)
                self.pending = [r for r in self.pending if r[1] != pid]
                if self.race == pid and row:
                    self.running.append(row)
            return self.response({})
        if path == '/prompt':
            pid = body['prompt_id']
            if self.reject == pid and body['prompt'] == {'updated': pid}:
                raise urllib.error.URLError('Synthetic validation failure')
            graph = {'wrong': True} if self.ignore == pid else copy.deepcopy(body['prompt'])
            row = [body['number'], pid, graph, body.get('extra_data', {}), []]
            if self.finish:
                self.history[pid] = row
            else:
                self.pending.append(row)
            if self.lost_ack == pid:
                raise urllib.error.URLError('Synthetic response lost after accept')
            return self.response({'prompt_id': pid, 'node_errors': {}})
        raise AssertionError(path)


class QueueBulkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.backend = Backend()
        self.commits = []
        self.editor = QueueBulkEditor(self.backend.request, threading.Lock(), self.tmp.name,
                                      self.save, lambda changes: self.commits.append(copy.deepcopy(changes)))

    def save(self, path, value):
        temp = path + '.tmp'
        Path(temp).write_text(json.dumps(value), encoding='utf8')
        os.replace(temp, path)

    def changes(self):
        return [{'id': r[1], 'before': copy.deepcopy(r[2]), 'prompt': {'updated': r[1]},
                 'entry': {'id': r[1], 'prompt': 'Synthetic', 'edited_at': 2}, 'job': {'id': r[1]}}
                for r in self.backend.pending]

    def backups(self):
        return list(Path(self.tmp.name).glob('*.json'))

    def test_six_hundred_edits_use_two_full_snapshots_and_one_history_commit_per_group(self):
        self.backend = Backend(600)
        self.editor.request = self.backend.request
        before = copy.deepcopy(self.backend.pending)
        changes = self.changes()
        succeeded = []
        for i in range(0, 600, 25):
            ok, failed = self.editor.apply(changes[i:i+25])
            self.assertEqual(failed, [])
            succeeded.extend(ok)
        self.assertEqual(len(succeeded), 600)
        self.assertEqual(sum(path == '/queue' and body is None for path, body in self.backend.calls), 48)
        self.assertEqual(len(self.commits), 24)
        after = sorted(self.backend.pending, key=lambda row: row[0])
        for old, new in zip(before, after):
            self.assertEqual(old[:2], new[:2])
            self.assertEqual(old[3:], new[3:])
            self.assertEqual(new[2], {'updated': old[1]})
        self.assertEqual(self.backups(), [])
        self.assertFalse(any(path == '/interrupt' for path, _ in self.backend.calls))

    def test_mixed_success_failure_and_stale_changes_are_reported_separately(self):
        changes = self.changes()
        self.backend.reject = changes[0]['id']
        self.backend.pending[1][2] = {'externally': 'changed'}
        ok, failed = self.editor.apply(changes)
        self.assertEqual([c['id'] for c in ok], [changes[2]['id']])
        self.assertEqual({c['id'] for c in failed}, {changes[0]['id'], changes[1]['id']})
        rows = {row[1]: row for row in self.backend.pending}
        self.assertEqual(rows[changes[0]['id']][2], changes[0]['before'])
        self.assertEqual(rows[changes[1]['id']][2], {'externally': 'changed'})

    def test_start_race_never_duplicates_or_interrupts_running_job(self):
        changes = self.changes()
        self.backend.race = changes[0]['id']
        ok, failed = self.editor.apply(changes)
        self.assertEqual(len(ok), 2)
        self.assertEqual(len(failed), 1)
        self.assertEqual(self.backend.running[0][2], changes[0]['before'])
        self.assertFalse(any(path == '/prompt' and body['prompt_id'] == changes[0]['id'] for path, body in self.backend.calls))

    def test_lost_response_is_checked_and_never_blindly_retried_or_restored(self):
        changes = self.changes()[:1]
        self.backend.lost_ack = changes[0]['id']
        ok, failed = self.editor.apply(changes)
        self.assertEqual(len(ok), 1)
        self.assertEqual(failed, [])
        self.assertEqual(sum(path == '/prompt' for path, _ in self.backend.calls), 1)
        self.assertEqual(sum(row[1] == changes[0]['id'] for row in self.backend.pending), 1)

    def test_wrong_native_graph_is_not_committed_as_success(self):
        changes = self.changes()[:1]
        self.backend.ignore = changes[0]['id']
        ok, failed = self.editor.apply(changes)
        self.assertEqual(ok, [])
        self.assertEqual(len(failed), 1)
        self.assertEqual(self.commits, [])
        self.assertEqual(len(self.backups()), 1)

    def test_failed_readback_retains_recovery_and_does_not_claim_success(self):
        self.backend.verification_unavailable = True
        ok, failed = self.editor.apply(self.changes()[:1])
        self.assertEqual(ok, [])
        self.assertEqual(len(failed), 1)
        self.assertEqual(self.commits, [])
        self.assertEqual(len(self.backups()), 1)

    def test_lost_response_and_unavailable_readback_does_not_restore_or_retry(self):
        changes = self.changes()[:1]
        self.backend.lost_ack = changes[0]['id']
        self.backend.verification_unavailable = True
        ok, failed = self.editor.apply(changes)
        self.assertEqual(ok, [])
        self.assertEqual(len(failed), 1)
        self.assertEqual(sum(path == '/prompt' for path, _ in self.backend.calls), 1)
        self.assertEqual(len(self.backups()), 1)

    def test_removed_job_is_never_recreated_and_oversized_group_writes_nothing(self):
        changes = self.changes()
        self.backend.pending.pop(0)
        ok, failed = self.editor.apply(changes)
        self.assertEqual(len(ok), 2)
        self.assertEqual([item['id'] for item in failed], [changes[0]['id']])
        self.assertFalse(any(path == '/prompt' and body['prompt_id'] == changes[0]['id'] for path, body in self.backend.calls))
        self.backend.calls.clear()
        with self.assertRaises(ValueError):
            self.editor.apply(changes * 9)
        self.assertEqual(self.backend.calls, [])

    def test_fast_finished_graph_is_verified_in_native_history(self):
        self.backend.finish = True
        ok, failed = self.editor.apply(self.changes()[:1])
        self.assertEqual(len(ok), 1)
        self.assertEqual(failed, [])

    def test_old_native_version_uses_safe_full_queue_fallback(self):
        self.backend.unsupported = True
        ok, failed = self.editor.apply(self.changes()[:1])
        self.assertEqual(len(ok), 1)
        self.assertEqual(failed, [])

    def test_identical_graphs_need_no_native_delete_or_submit(self):
        changes = self.changes()
        for c in changes:
            c['prompt'] = copy.deepcopy(c['before'])
        ok, failed = self.editor.apply(changes)
        self.assertEqual(len(ok), 3)
        self.assertEqual(failed, [])
        self.assertFalse(any(body is not None for _, body in self.backend.calls))

    def test_recovery_commits_only_verified_metadata_without_submitting_jobs(self):
        change = self.changes()[0]
        def crash(changes):
            raise OSError('Synthetic history checkpoint interrupted')
        self.editor.commit = crash
        with self.assertRaises(OSError):
            self.editor.apply([change])
        self.assertEqual(len(self.backups()), 1)
        self.editor.commit = lambda changes: self.commits.append(copy.deepcopy(changes))
        self.backend.calls.clear()
        self.assertEqual(self.editor.recover({change['id']: {'id': change['id'], 'edited_at': 1}}), 1)
        self.assertEqual(len(self.commits), 1)
        self.assertTrue(all(body is None for _, body in self.backend.calls))
        self.assertEqual(self.backups(), [])

    def test_recovery_never_resurrects_deleted_history_or_overwrites_newer_metadata(self):
        c = self.changes()[0]
        path = self.editor.backup_path(c['id'])
        record = {'prompt_id': c['id'], 'replacement': c['before'], 'history_after': c['entry']}
        self.save(path, record)
        self.assertEqual(self.editor.recover({}), 0)
        self.assertTrue(Path(path).exists())
        self.assertEqual(self.editor.recover({c['id']: {'edited_at': 3}}), 0)
        self.assertEqual(self.commits, [])
        self.assertFalse(Path(path).exists())

    def test_recovery_keeps_unconfirmed_copy_and_never_submits_an_absent_job(self):
        c = self.changes()[0]
        self.save(self.editor.backup_path(c['id']), {
            'prompt_id': c['id'], 'replacement': c['prompt'], 'history_after': c['entry']})
        self.assertEqual(self.editor.recover({c['id']: {'edited_at': 1}}), 0)
        self.assertEqual(self.commits, [])
        self.backend.pending.clear()
        self.assertEqual(self.editor.recover({c['id']: {'edited_at': 1}}), 0)
        self.assertTrue(all(body is None for _, body in self.backend.calls))
        self.assertEqual(len(self.backups()), 1)

    def test_build_cache_is_scoped_and_returns_independent_values(self):
        cache = BuildCache()
        reads = []
        def read():
            reads.append(1)
            return {'value': [1]}
        a = cache.get('template', read)
        a['value'].append(2)
        self.assertEqual(cache.get('template', read), {'value': [1]})
        self.assertEqual(len(reads), 1)
        BuildCache().get('template', read)
        self.assertEqual(len(reads), 2)


if __name__ == '__main__':
    unittest.main()
