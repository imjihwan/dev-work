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

    def test_failure_reasons_are_shared_counts_without_arbitrary_error_text(self):
        p=BulkProgress()
        with p.operation(4) as report:
            report.advance(False,error='이 사진 조합은 원본 비율에서도 인물이 잘릴 수 있어 등록하지 않았습니다. 첫·끝 사진을 같은 비율로 맞춰 주세요.')
            report.advance(False,error='이미 시작됐거나 대기열에서 빠진 항목입니다.')
            report.advance(False,error=ValueError('PRIVATE PROMPT /private/photo.png'))
            report.advance(True,verified=True)
            snapshot=p.snapshot();snapshot['failure_reasons'][0]['count']=999
        snapshot=p.snapshot()
        self.assertEqual({r['code']:r['count'] for r in snapshot['failure_reasons']},{'framing':1,'started':1,'other':1})
        self.assertNotIn('PRIVATE',str(snapshot));self.assertNotIn('photo.png',str(snapshot))
        self.assertEqual(snapshot['failed'],3)
        with p.operation(0):pass
        self.assertEqual(p.snapshot()['failure_reasons'],[])


if __name__=='__main__':unittest.main()
