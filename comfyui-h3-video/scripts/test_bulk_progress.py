"""Synthetic queue-edit counters only; no live tasks, media or network."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'simple_ui'))
from bulk_progress import BulkProgress


class BulkProgressTests(unittest.TestCase):
    def test_six_hundred_items_count_outcomes_and_verification_not_estimated_time(self):
        now=[100];p=BulkProgress(clock=lambda:now[0])
        with p.operation(600,all_pending=True) as report:
            for n in range(600):
                report.advance(n%100!=0,verified=True)
                s=p.snapshot();self.assertEqual(s['processed'],n+1)
                self.assertEqual(s['processed'],s['succeeded']+s['failed'])
                self.assertEqual(s['state'],'running')
            now[0]=400
        s=p.snapshot();self.assertEqual(s['state'],'done');self.assertEqual(s['percent'],100)
        self.assertEqual(s['succeeded'],594);self.assertEqual(s['failed'],6);self.assertEqual(s['verified'],594)
        self.assertEqual(s['elapsed_seconds'],300);self.assertNotIn('jobs',s);self.assertNotIn('prompt',s)

    def test_error_keeps_partial_counts_and_second_operation_cannot_reset_active_progress(self):
        p=BulkProgress()
        with self.assertRaises(RuntimeError):
            with p.operation(4) as report:
                report.advance(True)
                with self.assertRaises(ValueError):
                    with p.operation(10):pass
                self.assertEqual(p.snapshot()['total'],4)
                raise RuntimeError('PRIVATE ERROR CONTENT')
        s=p.snapshot();self.assertEqual(s['state'],'error');self.assertEqual(s['percent'],25)
        self.assertNotIn('PRIVATE',str(s))
        with p.operation(0):pass
        self.assertEqual(p.snapshot()['percent'],100);self.assertEqual(p.snapshot()['state'],'done')


if __name__=='__main__':unittest.main()
