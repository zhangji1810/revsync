from collections import defaultdict
import json
import redis
import threading
import traceback

key_dec = {
    'c': 'cmd',
    'a': 'addr',
    'u': 'user',
    't': 'text',
}
key_enc = {v: k for k, v in key_dec.items()}

def decode(data):
    d = json.loads(data)
    return {key_dec.get(k, k): v for k, v in d.items()}

def dtokey(d):
    return tuple(((k, v) for k, v in d.items() if k != 'user'))

class Client:
    def __init__(self, host, port, nick, password=None):
        self.r = redis.StrictRedis(host=host, port=port, password=password)
        self.nick = nick
        self.ps = {}
        self.nolock = threading.Lock()
        self.nosend = defaultdict(list)
        self.norecv = defaultdict(list)

    def _sub_thread(self, ps, cb, key):
        for item in ps.listen():
            try:
                if item['type'] == 'message':
                    data = decode(item['data'])
                    with self.nolock:
                        dkey = dtokey(data)
                        no = self.norecv[key]
                        if dkey in no:
                            no.remove(dkey)
                            continue
                        else:
                            self.nosend[key].append(dkey)

                    cb(key, data)
                elif item['type'] == 'subscribe':
                    for data in self.r.lrange(key, 0, -1):
                        try:
                            cb(key, decode(data), replay=True)
                        except Exception:
                            print 'error replaying history', data
                            traceback.print_exc()
                else:
                    print 'unknown redis push', item
            except Exception:
                print 'error processing item', item
                traceback.print_exc()

    def join(self, key, cb):
        ps = self.r.pubsub()
        ps.subscribe(key)
        t = threading.Thread(target=self._sub_thread, args=(ps, cb, key))
        t.daemon = True
        t.start()

        self.ps[key] = ps
        self.publish(key, {'cmd': 'join'}, perm=False)

    def leave(self, key):
        ps = self.ps.pop(key, None)
        if ps:
            ps.unsubscribe(key)

    def publish(self, key, data, perm=True):
        with self.nolock:
            dkey = dtokey(data)
            no = self.nosend[key]
            if dkey in no:
                no.remove(dkey)
                return
            else:
                self.norecv[key].append(dkey)

        data['user'] = self.nick
        data = {key_enc.get(k, k): v for k, v in data.items()}
        data = json.dumps(data, separators=(',', ':'), sort_keys=True)
        if perm:
            self.r.rpush(key, data)
        self.r.publish(key, data)
