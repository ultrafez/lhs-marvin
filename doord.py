#! /usr/bin/env python

import crc16
import serial
import time
import MySQLdb
import ConfigParser;

POLL_TIMEOUT = 60
POLL_PERIOD = 1

class Tag(object):
    NONE = 0
    DOWNSTAIRS = 1
    BOTH = 3
    def __init__(self, tag_id, pin, access_str):
        self.tag_id = tag_id.upper()
        self.pin = pin
        if access_str == 'DOWNSTAIRS':
            self.access = Tag.DOWNSTAIRS
        elif access_str == 'BOTH':
            self.access = Tag.BOTH
        else:
            self.access = Tag.NONE
    def upstairs_ok(self):
        return self.access == Tag.BOTH
    def downstairs_ok(self):
        return self.access == Tag.BOTH or self.access == Tag.DOWNSTAIRS
    def __eq__(self, other):
        return self.tag_id == other.tag_id \
                and self.pin == other.pin \
                and self.access == other.access
    def __ne__(self, other):
        return not self.__eq__(other)

class TagDB(object):
    def __init__(self, user, passwd):
        self.db_user = user
        self.db_passwd = passwd
        self.db = None
        self.tags = []
    def keylist(self, fn):
        k = []
        for t in self.tags:
            if fn(t):
                k.append(t.tag_id + ' ' + t.pin)
        return k
    # Returns true if tag list has changed
    def update(self):
        changed = False
        try:
            self.db = MySQLdb.connect(host="localhost", user=self.db_user,
                    passwd=self.db_passwd, db="hackspace")
            cur = self.db.cursor()
            cur.execute( \
                "SELECT rfid_tags.card_id, rfid_tags.pin, people.access" \
                " FROM people INNER JOIN rfid_tags" \
                " ON (people.id = rfid_tags.user_id)" \
                " WHERE (people.access != 'NO')" \
                " ORDER BY rfid_tags.card_id;")
            tag_num = 0
            while True:
                row = cur.fetchone()
                if row is None:
                    break;
                t = Tag(row[0], row[1], row[2])
                if not changed:
                    if (tag_num == len(self.tags)) or (self.tags[tag_num] != t):
                        changed = True
                        del self.tags[tag_num:]
                    else:
                        tag_num += 1
                if changed:
                    self.tags.append(t)
        except:
            if self.db:
                self.db.close()
            self.db = None
            self.tags = []
            raise
        return changed

def dbg(msg):
    if True:
        print msg

def encode64(val):
    if val < 26:
        return chr(val + ord("A"))
    val -= 26;
    if val < 26:
        return chr(val + ord("a"))
    val -= 26;
    if val < 10:
        return chr(val + ord("0"))
    val -= 10;
    if val == 0:
        return '+';
    if val == 1:
        return '/';
    return '*';

def decode64(c):
    if c >= 'A' and c <= 'Z':
        return ord(c) - ord('A')
    if c >= 'a' and c <= 'z':
        return ord(c) + 26 - ord('a')
    if c >= '0' and c <= '9':
        return ord(c) + 52 - ord('0')
    if c == '+':
        return 62
    if c == '/':
        return 63
    raise Exception("Bad base64 character: '%s'" % c)

def encoded_time():
    t = int(time.time())
    s = ""
    for i in xrange(0, 6):
        s += encode64(t & 0x3f)
        t >>= 6;
    return s

def decode_time(s):
    t = 0
    for i in xrange(0, len(s)):
        t |= decode64(s[i]) << (i * 6)
    return t

def crc_str(s):
    return "%04X" % crc16.crc16xmodem(s)

class DoorMonitor(object):
    def __init__(self, port):
        self.portname = port;
        self.ser = None
        self.seen_event = False
        self.sync = False
        self.keys = []

    def read_response(self):
        while True:
            r = self.ser.readline()
            if r == "":
                raise Exception("No response from target")
            dbg("Response: %s" % r[:-1])
            if len(r) < 5:
                continue
            if r[0] == '#':
                continue
            crc = r[-5:-1]
            r = r[:-5]
            # FIXME: check CRC
            if crc != crc_str(r):
                raise Exception("CRC mismatch (exp %s got %s)" % (crc, crc_str(r)))
            if r[0] == 'E':
                dbg("Seen event")
                self.seen_event = True;
                continue;
            return r

    def do_cmd(self, cmd):
        dbg("Sending %s" % cmd)
        self.ser.write(cmd)
        self.ser.write(crc_str(cmd))
        self.ser.write("\n")
        return self.read_response()

    def send_ping(self):
        t = encoded_time()
        r = self.do_cmd("P0" + t)
        if r != "P1" + t:
            raise Exception("Device not accepting ping")

    def resync(self):
        dbg("Resync")
        if self.ser is None:
            self.ser = serial.Serial(self.portname, 9600, timeout=1)
            self.ser.write("X\n")
            # Wait for a 1s quiet period
            while self.ser.inWaiting():
                while self.ser.inWaiting():
                    self.ser.read(1)
                time.sleep(1)

        # Re-enumerate devices
        r = self.do_cmd("S0")
        if r != 'S1':
            raise Exception("Device not accepting address")
        self.send_ping()
        r = self.do_cmd("K0?")
        if r != "K0i" + self.key_hash():
            dbg("Uploading keys")
            r = self.do_cmd("K0*")
            if r != 'A0':
                raise Exception("Device not accepting keys")
            for key in self.keys:
                self.do_cmd("K0+" + key)
        self.sync = True

    def poll_event(self):
        if not self.sync:
            return False
        return self.ser.inWaiting();

    def key_hash(self):
        crc = 0
        for key in self.keys:
            crc = crc16.crc16xmodem(key, crc)
            crc = crc16.crc16xmodem(chr(0), crc)
        dbg("key hash %04X" % crc)
        return "%04X" % crc

    def handle_log(self, msg):
        t = decode_time(msg[0:6])
        action = msg[6]
        tag = msg[7:]
        tstr = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))
        print "%s %s %s" % (tstr, action, tag)

    def work(self):
        dbg("Work")
        try:
            if self.sync:
                self.send_ping()
            else:
                self.resync()
            self.seen_event = False
            while True:
                r = self.do_cmd("G0")
                if r[:2] != "V0":
                    raise Exception("Failed to get event log")
                if len(r) == 2:
                    break
                dbg("Log event: %s" % r[2:])
                self.handle_log(r[2:])
        except KeyboardInterrupt:
            raise
        except BaseException as e:
            if self.ser is not None:
                self.ser.close()
            self.ser = None
            self.sync = False
            print e
        except:
            raise

    def set_keys(self, keys):
        self.keys = keys[:]
        self.sync = False

config = ConfigParser.SafeConfigParser()
config.read("/etc/marvin.conf")
tags = TagDB(config.get("db", "user"), config.get("db", "password"))
door_up = DoorMonitor("/dev/door_up")
door_down = DoorMonitor("/dev/door_down")
tags.update()
update_tags = True
while True:
    if update_tags:
        door_up.set_keys(tags.keylist(Tag.upstairs_ok))
        door_down.set_keys(tags.keylist(Tag.downstairs_ok))
    dbg("Upstairs")
    door_up.work()
    dbg("Downstairs")
    door_down.work()
    timeout = 0
    while timeout < POLL_TIMEOUT and not (door_up.poll_event() or door_down.poll_event()):
        time.sleep(POLL_PERIOD)
        update_tags = tags.update()
        timeout += POLL_PERIOD
