import json
import pathlib
import tempfile
import unittest
from cloud_store import CloudStore, UnsupportedRequest


def request(op, profile='recipient', doc='mailbox', key='', value='', policy='0'):
    return {k: [v] for k, v in dict(ops=op, profileNames=profile, docKeys=doc,
                                    keys=key, values=value, policy=policy).items()}


class StorageTests(unittest.TestCase):
    def setUp(self):
        with tempfile.NamedTemporaryFile(dir=pathlib.Path(__file__).parent,
                                         prefix='cloud-test-', suffix='.sqlite', delete=False) as tmp:
            self.path = pathlib.Path(tmp.name)
        self.store = CloudStore(self.path)

    def tearDown(self):
        for suffix in ('', '-journal', '-wal', '-shm'):
            pathlib.Path(str(self.path) + suffix).unlink(missing_ok=True)

    def test_gift_payload_persists_and_is_scoped_to_recipient(self):
        payload = 'opaque payload with commas, quotes " and Unicode: подарок'
        self.store.execute(request('MAP_SET', key='gift-1', value=payload))
        reopened = CloudStore(self.path)
        result = reopened.execute(request('MAP_GET'))
        records = json.loads(result[1][0][1])
        self.assertEqual(records[0][0], 'gift-1')
        self.assertEqual(records[0][1][0], payload)
        self.assertEqual(reopened.execute(request('MAP_GET', profile='other')),
                         [0, [[0, '', 0, 0, '']]])

    def test_failed_batch_rolls_back_prior_write(self):
        params = request('SET,GET', profile='recipient,recipient', doc='first,absent',
                         key=',', value='saved,', policy='0,0')
        with self.assertRaises(UnsupportedRequest):
            self.store.execute(params)
        with self.assertRaises(UnsupportedRequest):
            CloudStore(self.path).execute(request('GET', doc='first'))

    def test_ambiguous_batch_fails_before_writes(self):
        with self.assertRaises(UnsupportedRequest):
            self.store.execute(request('MAP_SET,MAP_SET', profile='a,b', doc='m,m',
                                       key='1,2', value='one,two,three', policy='0,0'))
        self.assertEqual(self.store.execute(request('MAP_GET', profile='a')),
                         [0, [[0, '', 0, 0, '']]])

    def test_remove_does_not_touch_other_recipient(self):
        for profile in ('a', 'b'):
            self.store.execute(request('MAP_SET', profile=profile, key='same', value='item'))
        self.store.execute(request('MAP_REMOVE', profile='a', key='same'))
        self.assertEqual(self.store.execute(request('MAP_GET', profile='a'))[1][0][1], '')
        self.assertTrue(self.store.execute(request('MAP_GET', profile='b'))[1][0][1])


if __name__ == '__main__':
    unittest.main()
