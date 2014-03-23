#! /usr/bin/env python

# NOTE: The master copy of this script is kept in github.
# Please keep that up to date when making changes.

# Control electronic door locks

import sys
import crc16
import serial
import time
import MySQLdb
import ConfigParser
import threading
import daemon
import optparse
import os
import datetime
import setproctitle

class PidFile(object):
    """Context manager that locks a pid file.  Implemented as class
    not generator because daemon.py is calling .__exit__() with no parameters
    instead of the None, None, None specified by PEP-343."""
    # pylint: disable=R0903

    def __init__(self, path):
        self.path = path
        self.pidfile = None

    def __enter__(self):
        self.pidfile = open(self.path, "a+")
        self.pidfile.seek(0)
        self.pidfile.truncate()
        self.pidfile.write(str(os.getpid()))
        self.pidfile.flush()
        self.pidfile.seek(0)
        return self.pidfile

    def __exit__(self, exc_type=None, exc_value=None, exc_tb=None):
        try:
            self.pidfile.close()
        except IOError as err:
            # ok if file was just closed elsewhere
            if err.errno != 9:
                raise
        os.remove(self.path)

SERIAL_PING_INTERVAL = 60
# Polling period is also serial read timeout
SERIAL_POLL_PERIOD = 5

DB_POLL_PERIOD = 20

debug_lock = threading.Lock()

port_door_map = {"door_up" : "internaldoor",
        "door_down" : "externaldoor"};

def dbg(msg):
    if do_debug:
        print msg
    debug_lock.acquire()
    tstr = time.strftime("%Y-%m-%d %H:%M:%S")
    log_fh = open("/var/log/doord.log", 'at')
    log_fh.write("%s: %s\n" % (tstr, msg))
    log_fh.close()
    debug_lock.release()

class KillableThread(threading.Thread):
    def __init__(self):
        super(KillableThread, self).__init__()
        self._killed = False

    def kill(self):
        self._killed = True

    def check_kill(self):
        if self._killed:
            raise KeyboardInterrupt

    def delay(self, secs):
        for i in xrange(0, secs):
            self.check_kill()
            time.sleep(1)

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

# Handles both key updates and logging
class DBThread(KillableThread):
    def __init__(self, g):
        super(DBThread, self).__init__()
        self.g = g
        self.db_user = self.g.config.get("db", "user")
        self.db_passwd = self.g.config.get("db", "password")
        self.db = None
        self.tags = []
        self.door_state = {}
        for k in port_door_map.values():
            self.door_state[k] = False
        self.lock = threading.Lock()

    def _keylist(self, fn):
        k = []
        for t in self.tags:
            if fn(t):
                k.append(t.tag_id + ' ' + t.pin)
        return k
    def _db_cursor(self):
        if self.db is None:
            self.db = MySQLdb.connect(host="localhost", user=self.db_user,
                    passwd=self.db_passwd, db="hackspace")
        return self.db.cursor();
    # Returns true if tag list has changed
    def update(self):
        changed = False
        try:
            self.poll_space_open()
            cur = self._db_cursor()
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
                        dbg("Tags changed");
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
    def _write_log(self, tstr, msg):
        dbg("LOG: %s %s" % (tstr, msg));
        cur = self._db_cursor()
        cur.execute( \
                "INSERT INTO security (time, message)" \
                " VALUES ('%s', '%s');" % (tstr, msg))

    # Can be safely called from other threads
    def update_space_state(self):
        def updatefn():
            self.lock.acquire()
            try:
                dbg("Running space state update");
                try:
                    script = self.g.config.get("scripts", "update_state")
                    os.system(script)
                    self.poll_space_open()
                finally:
                    dbg("Done");
            finally:
                self.lock.release()
        self.g.schedule(updatefn)

    # Can be safely called from other threads
    def log(self, t, msg):
        tstr = time.strftime("%Y-%m-%d %H:%M:%S", t)
        # Closure to avoid deadlock
        def logfn():
            self.lock.acquire()
            self._write_log(tstr, msg)
            self.lock.release()
        self.g.schedule(logfn)

    # Can be safely called from other threads
    def do_tag_in(self, tag):
        self.lock.acquire()
        try:
            cur = self._db_cursor()
            cur.execute( \
                "INSERT INTO presence(system)" \
                " SELECT id FROM systems" \
                " WHERE mac = '%s' AND source='r';" \
                % (tag))
            cur.execute( \
                "UPDATE (systems INNER JOIN rfid_tags" \
                "  ON (systems.owner = rfid_tags.user_id))" \
                " SET systems.hidden = 0" \
                " WHERE rfid_tags.card_id = '%s' AND systems.hidden = 2;" \
                % (tag))
        finally:
            self.lock.release()
        self.update_space_state();

    # Can be safely called from other threads
    def do_tag_out(self, tag):
        self.lock.acquire()
        try:
            cur = self._db_cursor()
            cur.execute( \
                "UPDATE (systems INNER JOIN rfid_tags" \
                "  ON (systems.owner = rfid_tags.user_id))" \
                " SET systems.hidden = 2" \
                " WHERE rfid_tags.card_id = '%s' AND systems.hidden = 0;" \
                % (tag))
        finally:
            self.lock.release()
        self.update_space_state();

    def poll_space_open(self):
        cur = self._db_cursor()
        cur.execute( \
            "SELECT *" \
            " FROM prefs " \
            " WHERE ref='space-state' and value = 0;")
        row = cur.fetchone()
        self.space_open_state = (row is not None)
        self.g.aux.update()

    # Can be safely called from other threads
    def is_space_open(self):
        self.lock.acquire()
        is_open = self.space_open_state
        self.lock.release()
        return is_open

    # Can be safely called from other threads
    def query_override(self, tag, match=""):
        self.lock.acquire()
        try:
            cur = self._db_cursor()

            if tag == '!#':
                # Magic hack for Tuesday open evenings.
                now = datetime.datetime.now()
                if (now.weekday() != 1) or (now.hour < 17):
                    return False
                return self.space_open_state
            if tag[0] == '!':
                # OTP
                t = int(time.time())
                cur.execute( \
                    "SELECT val" \
                    " FROM otp_keys" \
                    " where (expires > now());")
                for row in cur.fetchall():
                    val = row[0]
                    if len(val) < 6:
                        continue
                    dbg("Matching '%s'/'%s'" % (val, match))
                    if val == match[-len(val):]:
                        dbg("Matched OTP key %s" % val)
                        cur.execute( \
                            "UPDATE otp_keys" \
                            " SET expires = now() + interval 10 minute" \
                            " WHERE (val = '%s')" \
                            % val);
                        return True
                return False
            else:
                cur.execute( \
                    "SELECT people.member" \
                    " FROM people INNER JOIN rfid_tags" \
                    " ON (people.id = rfid_tags.user_id)" \
                    " WHERE (rfid_tags.card_id = '%s' and people.member = 'YES');" \
                    % tag)
                row = cur.fetchone()
                if row is None:
                    return False
                return self.space_open_state
        finally:
            self.lock.release()
        return False

    # Can be safely called from other threads
    def record_temp(self, temp):
        self.lock.acquire()
        try:
            dbg("Logging temperature %d" % temp)
            cur = self._db_cursor()
            cur.execute( \
                "INSERT INTO environmental(temperature)" \
                " VALUES (%d)" \
                % (temp))
        finally:
            self.lock.release()

    # Can be safely called from other threads
    def set_door_state(self, port, state):
        self.lock.acquire()
        try:
            door_name = port_door_map[port]
            if self.door_state[door_name] != state:
                if state:
                    state_name = 'open'
                else:
                    state_name = 'closed'
                cur = self._db_cursor()
                cur.execute( \
                    "REPLACE INTO prefs"\
                    " VALUES ('%s','%s')" \
                    % (door_name, state_name))
                self.door_state[door_name] = state
        finally:
            self.lock.release()
        g.dbt.update_space_state();

    def sync_keys(self):
        dbg("Triggering key sync");
        self.lock.acquire()
        try:
            self.g.door_up.set_keys(self._keylist(Tag.upstairs_ok))
            self.g.door_down.set_keys(self._keylist(Tag.downstairs_ok))
        finally:
            self.lock.release()
    def run(self):
        try:
            while True:
                self.lock.acquire()
                try:
                    if self.update():
                        self.g.schedule(self.sync_keys)
                finally:
                    self.lock.release()
                self.delay(DB_POLL_PERIOD)
        except KeyboardInterrupt:
            dbg("DB thread stopped");

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

# Communicate with auxiliary arduino (sign, webcam)
class AuxMonitor(KillableThread):
    def __init__(self, g, port):
        super(AuxMonitor, self).__init__()
        self.port_name = port;
        self.ser = None
        self.servo_pos = None
        self.next_temp_tick = None
        self.g = g
        self.cond = threading.Condition()

    def dbg(self, msg):
        dbg("%s: %s" % (self.port_name, msg))

    def do_cmd(self, cmd):
        self.dbg("Sending %s" % cmd);
        self.ser.write(cmd + '\n')
        r = self.ser.readline()
        if (r is None):
            raise Exception("No response from command '%s'", cmd)
        r = r.rstrip()
        self.dbg("Response %s" % r);
        return r

    def do_cmd_expect(self, cmd, response, error):
        r = self.do_cmd(cmd)
        if r != response:
            raise Exception(error + ("'%s/%s'" %(r, response)))

    def sync_sign(self):
        new_sign = self.g.dbt.is_space_open()
        if (self.last_sign is None) or (self.last_sign != new_sign):
            self.last_sign = new_sign
            if new_sign:
                cmd = "S1"
            else:
                cmd = "S0"
            self.do_cmd_expect(cmd, "OK", "Failed to set sign")

    def sync_servo(self):
        if self.last_servo == None:
            r = self.do_cmd("W")
            if r[:6] != "ANGLE=":
                raise Exception("Bad servo response: %s" % r)
            self.last_servo = int(r[6:])
        if self.servo_pos is None:
            self.servo_pos = self.last_servo
        if self.last_servo != self.servo_pos:
            self.do_cmd_expect("W%d" % self.servo_pos, "OK", "Failed to move servo")
            self.last_servo = self.servo_pos;

    def sync_temp(self):
        now = time.time()
        if (self.next_temp_tick is None) or (self.next_temp_tick < now):
            if (self.next_temp_tick is None) or (self.next_temp_tick < now - 30):
                self.next_temp_tick = now
            self.next_temp_tick += 60
            r = self.do_cmd("T")
            if r[:5] != "TEMP=":
                raise Exception("Bad temperature response")
            self.g.dbt.record_temp(int(r[5:]))

    def resync(self):
        self.dbg("Full resync")
        self.need_sync = True
        self.last_sign = None
        self.last_servo = None

    def work(self):
        self.resync()
        while True:
            self.check_kill()
            r = self.do_cmd("?")
            if r[:10] !=  "Marvin 1.5":
                raise Exception("Marvin went AWOL")
            if r[10:] == "+":
                self.resync()
            self.sync_sign()
            self.sync_servo()
            self.sync_temp()
            self.need_sync = False
            while (not self.need_sync) and (time.time() < self.next_temp_tick):
                self.check_kill()
                self.cond.wait(SERIAL_POLL_PERIOD)

    def run(self):
        while True:
            try:
                self.ser = serial.Serial("/dev/" + self.port_name, 9600, timeout=SERIAL_POLL_PERIOD, writeTimeout=SERIAL_POLL_PERIOD)
                # Opening the port resets the arduino,
                # which takes a few seconds to come back to life
                self.delay(5);
                self.ser.write("X\n")
                # Wait for a 1s quiet period
                while self.ser.inWaiting():
                    while self.ser.inWaiting():
                        self.ser.read(1)
                    time.sleep(1)
                try:
                    self.cond.acquire()
                    self.work()
                finally:
                    self.cond.release()
            except KeyboardInterrupt:
                # We use KeyboardInterrupt for thread termination
                self.dbg("Stopped")
                break
            except BaseException as e:
                if self.ser is not None:
                    self.ser.close()
                print e
            except:
                raise
            self.delay(SERIAL_PING_INTERVAL)

    # Called from other threads
    def update(self, servo=None):
        def updatefn():
            self.cond.acquire()
            self.need_sync = True;
            if servo is not None:
                self.servo_pos = pos
            self.cond.notify()
            self.cond.release()
        self.g.schedule(updatefn)

# Communicate with door locks.
# For Protocol details see DoorLock.ino
class DoorMonitor(KillableThread):
    def __init__(self, port):
        super(DoorMonitor, self).__init__()
        self.port_name = port;
        self.ser = None
        self.seen_event = False
        self.remote_open = False
        self.sync = False
        self.last_door_state = None
        self.keys = []
        self.seen_kp = None
        self.otp = ''
        self.otp_expires = None
        self.lock = threading.Lock()
        self.current_response = ""

    def dbg(self, msg):
        dbg("%s: %s" % (self.port_name, msg))

    def read_response(self, block):
        c = ''
        while c != '\n':
            self.check_kill()
            if not block:
                self.lock.release()
            try:
                c = self.ser.read()
            finally:
                if not block:
                    self.lock.acquire()
            if c == "":
                if block:
                    raise Exception("No response from %s" % self.port_name)
                return None
            self.current_response += c
        r = self.current_response
        self.current_response = ""
        self.dbg("Response: %s" % r[:-1])
        if len(r) < 5:
            return None
        if r[0] == '#':
            return None
        crc = r[-5:-1]
        r = r[:-5]
        if crc != crc_str(r):
            raise Exception("CRC mismatch (exp %s got %s)" % (crc, crc_str(r)))
        if r[0] == 'E':
            self.seen_event = True;
        elif r[0] == 'Y':
            kp_char = r[2]
            if self.seen_kp is None:
                self.seen_kp = ''
            self.seen_kp += kp_char
        else:
            return r
        return None

    def do_cmd(self, cmd):
        self.dbg("Sending %s" % cmd)
        self.ser.write(cmd)
        self.ser.write(crc_str(cmd))
        self.ser.write("\n")
        r = None
        while r is None:
            r = self.read_response(True)
        return r

    def do_cmd_expect(self, cmd, response, error):
        r = self.do_cmd(cmd)
        if r != response:
            raise Exception(error)

    def send_ping(self):
        t = encoded_time()
        self.do_cmd_expect("P0" + t, "P1" + t, "Machine does not go ping")

    def resync(self):
        self.dbg("Resync")
        if self.ser is None:
            self.ser = serial.Serial("/dev/" + self.port_name, 9600, timeout=SERIAL_POLL_PERIOD)
            self.ser.write("X\n")
            # Wait for a 1s quiet period
            while self.ser.inWaiting():
                while self.ser.inWaiting():
                    self.ser.read(1)
                time.sleep(1)

        # Enumerate devices
        self.do_cmd_expect("S0", "S1", "Device not accepting address")
        self.send_ping()
        r = self.do_cmd("K0")
        if r != "H0" + self.key_hash():
            self.dbg("Uploading keys")
            self.do_cmd_expect("R0", "A0", "Device key reset failed")
            for key in self.keys:
                self.do_cmd_expect("N0" + key, "A0", "Device not accepting keys")
        self.sync = True

    def poll_event(self):
        if not self.sync:
            if self.seen_event:
                return True;
            self.lock.release()
            try:
                self.delay(SERIAL_POLL_PERIOD);
            finally:
                self.lock.acquire()
            return False;
        r = self.read_response(False)
        if r is not None:
            raise Exception("Unexpected spontaneous response");
        return self.seen_event or (self.seen_kp is not None)

    def key_hash(self):
        crc = 0
        for key in self.keys:
            crc = crc16.crc16xmodem(key, crc)
            crc = crc16.crc16xmodem(chr(0), crc)
        self.dbg("key hash %04X" % crc)
        return "%04X" % crc

    def handle_log(self, msg):
        t = decode_time(msg[0:6])
        action = msg[6]
        tag = msg[7:]
        lt = time.localtime(t)
        if action == 'R':
            astr = "Rejected"
        elif action == 'U':
            g.dbt.do_tag_in(tag);
            astr = "Unlocked"
        elif action == 'P':
            astr = "BadPIN"
        elif action == 'O':
            astr = "Opened"
            g.dbt.set_door_state(self.port_name, True)
        elif action == 'C':
            astr = "Closed"
            g.dbt.set_door_state(self.port_name, False)
        elif action == 'B':
            astr = "Button"
        elif action == 'T':
            astr = "Scanout"
            g.dbt.do_tag_out(tag);
        elif action == 'Q':
            astr = "Query"
        else:
            astr = "Unknown"

        g.dbt.log(lt, "%s: %s %s" % (self.port_name, astr, tag))
        if action == 'R' or action == 'Q':
            # Allow all member tags if space is open
            # FIXME: Ignore old events if catching up after a resync
            if g.dbt.query_override(tag):
                g.dbt.do_tag_in(tag);
                self.remote_open = True;

    def work(self):
        self.dbg("Working")
        if self.seen_event:
            self.seen_event = False
            if self.sync:
                self.send_ping()
            else:
                self.resync()
            while True:
                r = self.do_cmd("G0")
                if r[:2] != "V0":
                    raise Exception("Failed to get event log")
                if len(r) == 2:
                    break
                self.dbg("Log event: %s" % r[2:])
                self.handle_log(r[2:])
                self.do_cmd_expect("C0", "A0", "Error clearing event log")
        if self.seen_kp is not None:
            c = self.seen_kp
            self.seen_kp = None
            if c != '#':
                c = self.otp + c;
                self.otp = c
                self.otp_expires = time.time() + 60
            if g.dbt.query_override('!' + c, self.otp):
                self.remote_open = True
        if self.remote_open:
            self.remote_open = False
            self.do_cmd_expect("U0", "A0", "Error doing remote open")
        if self.otp_expires is not None:
            if self.otp_expires < time.time():
                self.dbg("OTP expired")
                self.otp = ''
                self.otp_expires = None

    def set_keys(self, keys):
        self.lock.acquire()
        self.keys = keys[:]
        self.sync = False
        self.seen_event = True
        self.lock.release()

    def run(self):
        self.seen_event = True
        in_delay = False
        while True:
            self.lock.acquire()
            try:
                self.work()
                timeout = 0.0
                while not self.poll_event():
                    timeout += SERIAL_POLL_PERIOD
                    if timeout >= SERIAL_PING_INTERVAL:
                            self.seen_event = True
            except KeyboardInterrupt:
                # We use KeyboardInterrupt for thread termination
                self.dbg("Stopped")
                break
            except BaseException as e:
                if self.ser is not None:
                    self.ser.close()
                self.ser = None
                self.sync = False
                print e
            except:
                raise
            finally:
                self.lock.release()

class Globals(object):
    def __init__(self, config):
        self.config = config
        self.dbt = DBThread(self)
        self.door_up = DoorMonitor("door_up")
        self.door_down = DoorMonitor("door_down")
        self.aux = AuxMonitor(self, "arduino")
        self.cond = threading.Condition()
        self.triggers = []

    # Run a function from the main thread with no locks held
    def schedule(self, fn):
        self.cond.acquire()
        self.triggers.append(fn)
        self.cond.notify()
        self.cond.release()

    def run(self):
        # Ugly.  Do a manual key sync
        self.dbt.update()
        self.dbt.sync_keys()

        self.cond.acquire()
        # Start all the worker threads
        self.dbt.start()
        self.door_up.start()
        self.door_down.start()
        self.aux.start()
        try:
            while True:
                triggers = self.triggers
                self.triggers = []
                if len(triggers) == 0:
                    self.cond.wait(1)
                else:
                    self.cond.release()
                    for fn in triggers:
                        fn()
                    self.cond.acquire()
        finally:
            dbg("Exiting")
            self.door_up.kill()
            self.door_down.kill()
            self.dbt.kill()
            self.aux.kill()


op = optparse.OptionParser()
op.add_option("-d", "--debug", action="store_true", dest="debug", default=False)
(options, args) = op.parse_args()
do_debug = options.debug

cfg = ConfigParser.SafeConfigParser()
cfg.read("/etc/marvin.conf")

dc = daemon.DaemonContext()
dc.pidfile = PidFile('/var/run/doord.pid')
if do_debug:
    dc.detach_process = False
    dc.stdout = sys.stdout
    dc.stderr = sys.stderr
with dc:
    setproctitle.setproctitle("doord")
    g = Globals(cfg)
    g.run()
