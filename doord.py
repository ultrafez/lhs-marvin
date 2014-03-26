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
import socket

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

IRC_TIMEOUT = 30

ARP_SCAN_INTERVAL = 60
# RFID tags keep the space open for 15 minutes
RFID_SCAN_LIFETIME = 15 * 60

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
        self._cond = threading.Condition()
        self.acquire = self._cond.acquire
        self.release = self._cond.release
        self.notify = self._cond.notify

    def kill(self):
        self._killed = True
        self._cond.acquire()
        self._cond.notify()
        self._cond.release()

    def wait(self, timeout=None):
        self.check_kill()
        self._cond.wait(timeout)
        self.check_kill()

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
        self.space_open_state = None

    def wrapper(self, fn):
        self.acquire()
        try:
            if self.db is None:
                self.db = MySQLdb.connect(host="localhost", user=self.db_user,
                        passwd=self.db_passwd, db="hackspace")
            rc = fn(self.db.cursor())
        except:
            if self.db is not None:
                self.db.close()
            self.db = None
            raise
        finally:
            self.release()
        return rc

    def schedule_wrapper(self, fn):
        def wrapperfn():
            self.wrapper(fn)
        self.g.schedule(wrapperfn)

    def _keylist(self, fn):
        k = []
        for t in self.tags:
            if fn(t):
                k.append(t.tag_id + ' ' + t.pin)
        return k

    def sync_dummy_tags(self, cur):
        # Create dummy system entries for RFID cards
        # Delete removed tags
        cur.execute( \
            "DELETE FROM systems" \
            " WHERE source='r' AND (mac, owner) NOT IN" \
            "  (SELECT r.card_id, r.user_id FROM rfid_tags AS r);")
        # Add new ones
        cur.execute( \
            "INSERT INTO systems(mac, description, owner, source, hidden)" \
            " SELECT r.card_id, 'RFID', r.user_id, 'r', 0" \
            " FROM rfid_tags AS r" \
            " WHERE r.card_id NOT IN" \
            " (SELECT s.mac FROM systems AS s" \
            "  WHERE s.source='r');")

    # Read and update webcam servo position from database
    def poll_webcam(self, cur):
        cur.execute( \
            "SELECT value" \
            " FROM prefs " \
            " WHERE ref='webcam';")
        row = cur.fetchone()
        if row is not None:
            self.g.aux.update(int(row[0]))

    # Read and update tag list from database
    def poll_tags(self, cur):
        changed = False
        try:
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
            self.tags = []
            raise
        if changed:
            self.g.schedule(self.sync_keys)

    # Can be safely called from other threads
    def update_space_state(self):
        def updatefn(cur):
            dbg("Running state update")
            # Expire temporarily hidden devices
            cur.execute( \
                "UPDATE systems AS s" \
                " SET s.hidden=0" \
                " WHERE s.hidden=2 AND s.id NOT IN"\
                " (SELECT p.system FROM presence_deadline AS p" \
                "  WHERE p.expires => now();")
            # How many people are here?
            cur.execute( \
                "SELECT people.name" \
                " FROM (systems AS s INNER JOIN presence"\
                "  ON s.id = presence.system)" \
                " INNER JOIN people" \
                " ON s.owner = people.id" \
                " WHERE s.hidden = 0" \
                "  AND presence.time > now() - interval 2 minute" \
                " LIMIT 1;")
            row = cur.fetchone();
            old_state = self.space_open_state
            if row is None:
                # Nobody here
                # If the door is closed then close the space
                if old_state and not self.door_state["internaldoor"]:
                    self.space_open_state = False
                    self.g.irc.send("The space is closed")
            else:
                # Somebody here
                if not old_state:
                    # Open the space
                    # TODO: Only open the space if somebody has also unlocked the door?
                    self.space_open_state = True
                    self.g.irc.send("The space is open! %s is here!" % row[0])
            if self.space_open_state != old_state:
                if self.space_open_state:
                    state_val = 0
                else:
                    state_val = 2
                cur.execute( \
                    "UPDATE prefs" \
                    " SET value=%d" \
                    " WHERE ref = 'space-state';" \
                    % state_val)
                self.g.aux.update()
        self.schedule_wrapper(updatefn)

    # Can be safely called from other threads
    def log(self, t, msg):
        tstr = time.strftime("%Y-%m-%d %H:%M:%S", t)
        def logfn(cur):
            dbg("LOG: %s %s" % (tstr, msg));
            cur.execute( \
                    "INSERT INTO security (time, message)" \
                    " VALUES ('%s', '%s');" % (tstr, msg))
        self.schedule_wrapper(logfn)

    # Can be safely called from other threads
    def do_tag_in(self, tag):
        def tagfn(cur):
            self.add_presence_entry(cur, tag, 'r')
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
            self.update_space_state();
        self.wrapper(tagfn)

    # Can be safely called from other threads
    def do_tag_out(self, tag):
        def tagfn(cur):
            cur.execute( \
                "UPDATE (systems INNER JOIN rfid_tags" \
                "  ON (systems.owner = rfid_tags.user_id))" \
                " SET systems.hidden = 2" \
                " WHERE rfid_tags.card_id = '%s' AND systems.hidden = 0;" \
                % (tag))
            self.update_space_state();
        self.wrapper(tagfn)

    def add_presence_entry(self, cur, mac, source):
        if source == 'r':
            lifetime = RFID_SCAN_LIFETIME
        else:
            lifetime = int(ARP_SCAN_INTERVAL * 2.5)
        cur.execute( \
            "REPLACE INTO presence_deadline" \
            " SELECT id, now() + interval %d second" \
            " FROM systems" \
            " WHERE source = '%s' AND mac = '%s'" \
            % (lifetime, source, mac))


    # Can be safely called from other threads
    def update_arp_entries(self, macs):
        def add_macs(cur):
            for m in macs:
                self.add_presence_entry(cur, m, 'e')
        self.wrapper(add_macs)

    def poll_space_open(self, cur):
        cur.execute( \
            "SELECT *" \
            " FROM prefs " \
            " WHERE ref='space-state' and value = 0;")
        row = cur.fetchone()
        last_state = self.space_open_state
        self.space_open_state = (row is not None)
        if last_state != self.space_open_state:
            self.g.aux.update()

    # Can be safely called from other threads
    def is_space_open(self):
        self.acquire()
        is_open = self.space_open_state
        self.release()
        return is_open

    # Can be safely called from other threads
    def query_override(self, tag, match=""):
        def queryfn(cur):
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
            return False
        return self.wrapper(queryfn)

    # Can be safely called from other threads
    def record_temp(self, temp):
        def tempfn(cur):
            dbg("Logging temperature %d" % temp)
            cur.execute( \
                "INSERT INTO environmental(temperature)" \
                " VALUES (%d)" \
                % (temp))
        self.wrapper(tempfn)

    # Can be safely called from other threads
    def set_door_state(self, port, state):
        def doorfn(cur):
            door_name = port_door_map[port]
            if self.door_state[door_name] != state:
                if state:
                    state_name = "open"
                else:
                    state_name = "closed"
                cur.execute( \
                    "REPLACE INTO prefs"\
                    " VALUES ('%s','%s')" \
                    % (door_name, state_name))
                self.door_state[door_name] = state
                if door_name == "internaldoor":
                    if state:
                        self.g.aux.servo_override(180)
                    if not self.space_open_state:
                        self.g.irc.send("Internal door %s" % state_name)
            self.update_space_state();
        self.wrapper(doorfn)

    def sync_keys(self):
        dbg("Triggering key sync");
        self.acquire()
        try:
            self.g.door_up.set_keys(self._keylist(Tag.upstairs_ok))
            self.g.door_down.set_keys(self._keylist(Tag.downstairs_ok))
        finally:
            self.release()

    def run(self):
        while True:
            self.acquire()
            try:
                self.wrapper(self.poll_space_open)
                self.wrapper(self.poll_tags)
                self.wrapper(self.poll_webcam)
                self.wrapper(self.sync_dummy_tags)
                self.wait(DB_POLL_PERIOD)
            except KeyboardInterrupt:
                dbg("DB thread stopped");
                break;
            except BaseException as e:
                dbg(str(e))
            except:
                pass
            finally:
                self.release()

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
        self.last_servo = None
        self.servo_override_pos = None
        self.servo_override_time = None
        self.temp_due = True
        self.g = g

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
        if self.servo_override_time <= time.time():
            self.servo_override_pos = None
        if self.servo_override_pos is not None:
            newpos = self.servo_override_pos
        elif self.servo_pos is not None:
            newpos = self.servo_pos
        else:
            newpos = self.last_servo
        if self.last_servo != newpos:
            self.do_cmd_expect("W%d" % newpos, "OK", "Failed to move servo")
            self.last_servo = newpos

    def temp_trigger(self):
        self.acquire()
        self.temp_due = True
        self.update()
        self.release()
        self.g.schedule(self.temp_trigger, 60)

    def sync_temp(self):
        if self.temp_due:
            self.temp_due = False
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
            while not self.need_sync:
                self.wait()

    def run(self):
        self.temp_trigger()
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
                    self.acquire()
                    self.work()
                finally:
                    self.release()
            except KeyboardInterrupt:
                # We use KeyboardInterrupt for thread termination
                self.dbg("Stopped")
                break
            except BaseException as e:
                if self.ser is not None:
                    self.ser.close()
                self.dbg(str(e))
            except:
                raise
            self.delay(SERIAL_PING_INTERVAL)

    # Called from other threads
    def update(self, servo=None):
        def updatefn():
            self.acquire()
            self.need_sync = True;
            if servo is not None:
                self.servo_pos = servo
            self.notify()
            self.release()
        self.g.schedule(updatefn)

    # Called from other threads
    def servo_override(self, angle):
        self.acquire()
        self.servo_override_pos = angle
        self.servo_override_time = time.time() + 10
        self.g.schedule(self.update, 10)
        self.update()
        self.release()

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
        self.flush_backlog = True
        self.last_door_state = None
        self.keys = None
        self.seen_kp = None
        self.otp = ''
        self.otp_expires = None
        self.current_response = ""

    def dbg(self, msg):
        dbg("%s: %s" % (self.port_name, msg))

    def read_response(self, block):
        c = ''
        while c != '\n':
            self.check_kill()
            if not block:
                self.release()
            try:
                c = self.ser.read()
            finally:
                if not block:
                    self.acquire()
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
        self.flush_backlog = True

    def poll_event(self):
        if not self.sync:
            if self.seen_event:
                return True;
            self.wait(SERIAL_POLL_PERIOD);
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
        if (action == 'R' or action == 'Q') and not self.flush_backlog:
            # Allow all member tags if space is open
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
            self.flush_backlog = False
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
        self.acquire()
        self.keys = keys[:]
        self.sync = False
        self.seen_event = True
        self.release()

    def run(self):
        while self.keys is None:
            self.delay(1)
        while True:
            self.acquire()
            try:
                self.check_kill()
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
                self.dbg(str(e))
            except:
                raise
            finally:
                self.release()

class IRCSpammer(KillableThread):
    def __init__(self, g):
        super(IRCSpammer, self).__init__()
        self.g = g
        self.msgq = []

    def send(self, msg):
        self.acquire()
        self.msgq.append(msg)
        self.notify()
        self.release()

    def really_send(self, msg):
        address = (self.g.config.get("ircbot", "msghost"), self.g.config.get("ircbot", "msgport"))
        channel = self.g.config.get("ircbot", "msgchannel")
        s = socket.create_connection(address, IRC_TIMEOUT)
        try:
            s.sendall("%s %s\n" % (channel, msg))
            s.shutdown(socket.SHUT_RDWR)
        finally:
            s.close()

    def run(self):
        while True:
            self.acquire()
            try:
                self.check_kill()
                if len(self.msgq) == 0:
                    self.wait()
                else:
                    s = self.msgq.pop(0);
                    self.release()
                    try:
                        self.really_send(s)
                    finally:
                        self.acquire()
            except KeyboardInterrupt:
                dbg("IRC thread stopped")
                break
            except BaseException as e:
                dbg(str(e))
            except:
                pass
            finally:
                self.release()

class ARPMonitor(KillableThread):
    def __init__(self, g):
        super(ARPMonitor, self).__init__()
        self.g = g
        self.current_ip = set()
        self.current_mac = set()
        self.ping_pending = set()

    def dbg(self, msg):
        dbg("arp: %s" % (msg))

    def scan_arp(self):
        self.acquire()
        try:
            self.dbg("scanning table")
            new_ip = set()
            new_mac = set()
            f = open("/proc/net/arp")
            # Skip header
            try:
                f.readline()
                for l in f:
                    r = l.split()
                    ip = r[0]
                    flags = r[2]
                    mac = r[3]
                    if flags != '0x0' and mac != '00:00:00:00:00:00':
                        new_ip.add(ip)
                        new_mac.add(mac)
            finally:
                f.close()
            missing_ip = self.current_ip - new_ip
            self.current_ip = new_ip
            if len(missing_ip) > 0:
                self.ping_pending |= missing_ip
                self.notify()
            self.g.dbt.update_arp_entries(new_mac)
            unseen_mac = new_mac - self.current_mac
            self.current_mac = new_mac
        finally:
            self.release()
            self.g.schedule(self.scan_arp, ARP_SCAN_INTERVAL)

    def ping(self, ip):
        self.dbg("Pinging %s" % ip)
        try:
            os.system("ping -c 1 -W 5 %s" % ip)
        except:
            pass

    def ping_all(self, pending):
        for ip in pending:
            self.ping(ip)

    def run(self):
        self.g.schedule(self.scan_arp)
        while True:
            try:
                self.acquire()
                try:
                    pending = self.ping_pending
                    self.ping_pending = set()
                    if len(pending) == 0:
                        self.wait()
                finally:
                    self.release()
                self.ping_all(pending)
            except KeyboardInterrupt:
                self.dbg("stopped")
                break;
            except BaseException as e:
                self.dbg(str(e))

class Globals(object):
    def __init__(self, config):
        self.config = config
        self.dbt = DBThread(self)
        self.door_up = DoorMonitor("door_up")
        self.door_down = DoorMonitor("door_down")
        self.aux = AuxMonitor(self, "arduino")
        self.irc = IRCSpammer(self)
        self.arp = ARPMonitor(self)
        self.cond = threading.Condition()
        self.triggers = []

    # Run a function from the main thread with no locks held
    def schedule(self, fn, delay=0):
        self.cond.acquire()
        self.triggers.append((fn, time.time()+delay))
        self.cond.notify()
        self.cond.release()

    def run(self):
        # Start all the worker threads
        self.dbt.start()
        self.door_up.start()
        self.door_down.start()
        self.aux.start()
        self.irc.start()
        self.arp.start()
        self.cond.acquire()
        try:
            while True:
                now = time.time()
                deadline = now  + SERIAL_POLL_PERIOD
                triggers = self.triggers
                self.triggers = []
                for (fn, timeout) in triggers:
                    if timeout > now:
                        self.triggers.append((fn, timeout))
                        if timeout < deadline:
                            deadline = timeout
                    else:
                        self.cond.release()
                        try:
                            fn()
                        except KeyboardInterrupt:
                            pass
                        except BaseException as e:
                            dbg(str(e))
                        finally:
                            self.cond.acquire()
                self.cond.wait(deadline - now)
        except KeyboardInterrupt:
            pass
        finally:
            dbg("Exiting")
            self.cond.release()
            self.door_up.kill()
            self.door_down.kill()
            self.dbt.kill()
            self.aux.kill()
            self.irc.kill()
            self.arp.kill()

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
