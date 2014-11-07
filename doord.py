#! /usr/bin/env python

# NOTE: The master copy of this script is kept in github.
# Please keep that up to date when making changes.

# Control electronic door locks

# This script uses threads extensively, so attention needs to be paid
# to locking.  
# Long-running blocking operations shouldbe done outside the thread lock
# When calling a methods accross thread objects there is potential for
# deadlock.  A dispatch mechanism allows callbacks to be run at a later point
# from the main thread with no locks held.

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
import subprocess
import fcntl
import traceback

def schedule(fn, *args, **kwargs):
    g.schedule(fn, *args, **kwargs)

def OpenSerial(dev):
    ser = serial.Serial(dev, 9600, timeout=SERIAL_POLL_PERIOD, writeTimeout=SERIAL_POLL_PERIOD)
    try:
        fcntl.flock(ser, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except:
        ser.close()
        raise
    return ser

def CloseSerial(ser):
    if ser is None:
        return
    try:
        fcntl.flock(ser, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except:
        pass
    ser.close()

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
# Also keep network devices for 15 minutes, so rebooting a machine doesn't
# cause it to disappear
ARP_LIFETIME = 15 * 60

debug_lock = threading.Lock()

port_door_map = {"door_up" : "internaldoor",
        "door_down" : "externaldoor"};

def dbg(msg):
    if do_debug:
        print msg
    tstr = time.strftime("%Y-%m-%d %H:%M:%S")
    with debug_lock:
        with open("/var/log/doord.log", 'at') as log_fh:
            log_fh.write("%s: %s\n" % (tstr, msg))

class KillableThread(threading.Thread):
    def __init__(self):
        super(KillableThread, self).__init__()
        self._killed = False
        self._cond = threading.Condition()
        self.notify = self._cond.notify

    def __enter__(self):
        self._cond.acquire()

    def __exit__(self, exc_type, exc_value, traceback):
        self._cond.release()
        return False

    def kill(self):
        self._killed = True
        with self:
            self._cond.notify()

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
        self.tags = []
        self.door_state = {}
        for k in port_door_map.values():
            self.door_state[k] = False
        self.space_open_state = None
        self.last_tag_out = None

    def dbg(self, msg):
        dbg("dbt: %s" % (msg))

    def dbwrapper(fn):
        def _dbwrapper(self, *args, **kwargs):
            with self:
                db = None
                cursor = None
                try:
                    # We used to use a persistent database connection.  However this has strange 
                    db = MySQLdb.connect(host="localhost", user=self.db_user,
                            passwd=self.db_passwd, db="hackspace")
                    cursor = db.cursor()
                    rc = fn(self, cursor, *args, **kwargs)
                finally:
                    if cursor is not None:
                        cursor.close()
                    if db is not None:
                        db.close()
                return rc
        return _dbwrapper


    def _keylist(self, fn):
        k = []
        for t in self.tags:
            if fn(t):
                k.append(t.tag_id + ' ' + t.pin)
        return k

    @dbwrapper
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
    @dbwrapper
    def poll_webcam(self, cur):
        cur.execute( \
            "SELECT value" \
            " FROM prefs " \
            " WHERE ref='webcam';")
        row = cur.fetchone()
        if row is not None:
            self.g.aux.set_servo(int(row[0]))

    # Read and update tag list from database
    @dbwrapper
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
                        self.dbg("Tags changed");
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
            self.sync_keys()

    def _recent_tag_out(self):
        if self.last_tag_out is None:
            return False
        return self.last_tag_out > time.time() - 60

    @dbwrapper
    def _really_update(self, cur):
        self.dbg("Running state update")
        old_state = self.space_open_state
        # Expire temporarily hidden devices
        cur.execute( \
            "UPDATE systems AS s" \
            " SET s.hidden=0" \
            " WHERE s.hidden=2" \
            "  AND s.id NOT IN" \
            "  (SELECT p.system FROM presence_deadline AS p" \
            "   WHERE p.expires > now());")
        # Who is here?
        # If the space is closed, then only look for RFID cards.
        # If already open then also look for network devices.
        if old_state:
            extra_cond = ""
        else:
            extra_cond = " AND s.source = 'r'"
        cur.execute( \
            "SELECT people.name" \
            " FROM (systems AS s" \
            " INNER JOIN presence_deadline as pd"\
            "  ON s.id = pd.system)" \
            " INNER JOIN people" \
            "  ON s.owner = people.id" \
            " WHERE s.hidden = 0" \
            "  AND pd.expires > now()" \
            "  AND people.member = 'YES'" \
            "  %s" \
            " LIMIT 1;" \
            % extra_cond)
        row = cur.fetchone();
        if row is None:
            # Nobody here
            # If the door is closed (or someone tagged out) then close the space
            if self._recent_tag_out():
                new_state = False
            else:
                new_state = self.door_state["internaldoor"]
            if old_state and not new_state:
                self.space_open_state = False
                self.g.irc.send("The space is closed")
                self.g.hifi.cmd("stop")
        else:
            # Somebody here
            if not old_state:
                # Open the space
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

    # Can be safely called from other threads
    def update_space_state(self):
        schedule(self._really_update)

    @dbwrapper
    def _really_log(self, cur, t, msg):
        tstr = time.strftime("%Y-%m-%d %H:%M:%S", t)
        self.dbg("LOG: %s %s" % (tstr, msg));
        cur.execute( \
                "INSERT INTO security (time, message)" \
                " VALUES ('%s', '%s');" % (tstr, msg))

    # Can be safely called from other threads
    def log(self, t, msg):
        schedule(self._really_log, t, msg)

    # Called from other threads
    @dbwrapper
    def do_tag_in(self, cur, tag):
        self._add_presence_entry(cur, tag, 'r')
        cur.execute( \
            "UPDATE (systems INNER JOIN rfid_tags" \
            "  ON (systems.owner = rfid_tags.user_id))" \
            " SET systems.hidden = 0" \
            " WHERE rfid_tags.card_id = '%s' AND systems.hidden = 2;" \
            % (tag))
        self.update_space_state();

    # Called from other threads
    @dbwrapper
    def do_tag_out(self, cur, tag):
        cur.execute( \
            "UPDATE (systems INNER JOIN rfid_tags" \
            "  ON (systems.owner = rfid_tags.user_id))" \
            " SET systems.hidden = 2" \
            " WHERE rfid_tags.card_id = '%s' AND systems.hidden = 0;" \
            % (tag))
        self.last_tag_out = time.time()
        self.update_space_state();

    # Called from other threads
    @dbwrapper
    def seen_star(self, cur, port):
        if port_door_map[port] != "internaldoor":
            return
        if not self._recent_tag_out():
            return
        self.dbg("Force-close")
        # Force-close by temporarily ignoring all currently present devices
        cur.execute( \
            "UPDATE systems" \
            " SET systems.hidden = 2" \
            " WHERE systems.hidden = 0;")
        self.update_space_state()

    def _add_presence_entry(self, cur, mac, source):
        if source == 'r':
            lifetime = RFID_SCAN_LIFETIME
        else:
            lifetime = ARP_LIFETIME
        cur.execute( \
            "REPLACE INTO presence_deadline" \
            " SELECT id, now() + interval %d second" \
            " FROM systems" \
            " WHERE source = '%s' AND mac = '%s'" \
            % (lifetime, source, mac))


    # Called from other threads
    @dbwrapper
    def update_arp_entries(self, cur, macs):
        for m in macs:
            self._add_presence_entry(cur, m, 'e')
        self.update_space_state();

    # Called from other threads
    @dbwrapper
    def check_bogon(self, cur, mac, ip):
        self.dbg("Checking bogon %s (%s)" % (mac, ip))
        cur.execute( \
            "REPLACE INTO bogons (address, info)" \
            " SELECT * FROM" \
            "  (SELECT '%s' as mac, '%s') AS tmp" \
            " WHERE NOT EXISTS" \
            "  (SELECT systems.mac" \
            "   FROM systems" \
            "   WHERE systems.mac = tmp.mac" \
            "    AND systems.source = 'e');" \
            % (mac, ip))

    @dbwrapper
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
        with self:
            return self.space_open_state

    # Can be safely called from other threads
    @dbwrapper
    def query_override(self, cur, tag, match=""):
        def is_open_evening():
            now = datetime.datetime.now()
            if (now.weekday() == 1) and (now.hour >= 17):
                return True
            cur.execute( \
                "SELECT *" \
                " FROM open_days" \
                " WHERE (start <= now()) AND (end > now())" \
                " LIMIT 1;")
            row = cur.fetchone()
            dbg("%s" % (row is not None))
            if row is not None:
                return True;
            return False
        if tag == '!#':
            # Magic hack for Tuesday open evenings.
            return is_open_evening() and self.space_open_state
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
                self.dbg("Matching '%s'/'%s'" % (val, match))
                if val == match[-len(val):]:
                    self.dbg("Matched OTP key %s" % val)
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

    # Can be called from other threads
    @dbwrapper
    def record_temp(self, cur, temp):
        self.dbg("Logging temperature %d" % temp)
        cur.execute( \
            "INSERT INTO environmental(temperature)" \
            " VALUES (%d)" \
            % (temp))

    # Can be called from other threads
    @dbwrapper
    def set_door_state(self, cur, port, state):
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

    def sync_keys(self):
        self.dbg("Triggering key sync");
        schedule(self.g.door_up.set_keys, self._keylist(Tag.upstairs_ok))
        schedule(self.g.door_down.set_keys, self._keylist(Tag.downstairs_ok))

    def run(self):
        while True:
            try:
                self.poll_space_open()
                self.poll_tags()
                self.poll_webcam()
                self.sync_dummy_tags()
                with self:
                    self.wait(DB_POLL_PERIOD)
            except KeyboardInterrupt:
                self.dbg("Stopped");
                break;
            except BaseException as e:
                self.dbg(str(e))
            except:
                self.dbg("Wonky exception")

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
# Extra care must be taken to avoid deadlock between this DBThread
# In particular AuxMonitor.work() is called with the lock held and
# calls synchronous locking DBThread functions.
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
        self.bell_duration = None
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
        with self:
            self.temp_due = True
            self.update()
            self.g.schedule_delay(self.temp_trigger, 60)

    def sync_temp(self):
        if self.temp_due:
            self.temp_due = False
            r = self.do_cmd("T")
            if r[:5] != "TEMP=":
                raise Exception("Bad temperature response")
            schedule(self.g.dbt.record_temp, int(r[5:]))

    def sync_bell(self):
        if self.bell_duration is not None:
            self.do_cmd_expect("B%d" % self.bell_duration, "OK", "Failed to ring the bell")
            self.bell_duration = None

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
            self.dbg("Sign")
            self.sync_sign()
            self.dbg("Servo")
            self.sync_servo()
            self.dbg("Temperature")
            self.sync_temp()
            self.dbg("Bell")
            self.sync_bell()
            self.dbg("Done")
            self.need_sync = False
            while not self.need_sync:
                self.dbg("Waiting")
                self.wait()

    def run(self):
        with self:
            self.temp_trigger()
        while True:
            try:
                self.dbg("Opening serial port")
                self.ser = OpenSerial("/dev/" + self.port_name)
                # Opening the port resets the arduino,
                # which takes a few seconds to come back to life
                self.delay(5);
                self.ser.write("X\n")
                # Wait for a 1s quiet period
                while self.ser.inWaiting():
                    while self.ser.inWaiting():
                        self.ser.read(1)
                    time.sleep(1)
                with self:
                    self.work()
            except KeyboardInterrupt:
                # We use KeyboardInterrupt for thread termination
                self.dbg("Stopped")
                break
            except BaseException as e:
                self.dbg(str(e))
            except:
                self.dbg("Wonky exception")
                raise
            finally:
                self.dbg("Closing serial port")
                if self.ser is not None:
                    CloseSerial(self.ser)
                    self.ser = None
            try:
                self.dbg("Waiting")
                self.delay(SERIAL_PING_INTERVAL)
            except KeyboardInterrupt:
                break

    # Called from other threads
    def update(self):
        def updatefn():
            with self:
                self.need_sync = True;
                self.notify()
        self.g.schedule(updatefn)

    # Called from other threads
    def set_servo(self, pos):
        def servofn():
            with self:
                if self.servo_pos != pos:
                    self.servo_pos = pos
                    self.update()
        self.g.schedule(servofn)

    # Called from other threads
    def bell_trigger(self, duration):
        def bellfn(self):
            with self:
                self.bell_duration = duration
                self.update()
        self.g.schedule(bellfn)

    # Called from other threads
    def servo_override(self, angle):
        def servo_overridefn(self):
            with self:
                self.servo_override_pos = angle
                self.servo_override_time = time.time() + 10
                self.g.schedule_delay(self.update, 10)
                self.update()
        self.g.schedule(servo_overridefn)

# Communicate with door locks.
# For Protocol details see DoorLock.ino
class DoorMonitor(KillableThread):
    def __init__(self, g, port):
        super(DoorMonitor, self).__init__()
        self.g = g
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
                self._cond.release()
            try:
                c = self.ser.read()
            finally:
                if not block:
                    self._cond.acquire()
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
            self.ser = OpenSerial("/dev/" + self.port_name)
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
            if c == '*':
                g.dbt.seen_star(self.port_name)
            elif c != '#':
                c = self.otp + c;
                self.otp = c
                self.otp_expires = time.time() + 60
            if g.dbt.query_override('!' + c, self.otp):
                self.remote_open = True
            elif c == '#':
                g.aux.bell_trigger(2)
        if self.remote_open:
            self.remote_open = False
            self.do_cmd_expect("U0", "A0", "Error doing remote open")
        if self.otp_expires is not None:
            if self.otp_expires < time.time():
                self.dbg("OTP expired")
                self.otp = ''
                self.otp_expires = None

    # Called from other threads
    # keys will be used directly, and must not be modified later
    def set_keys(self, keys):
        with self:
            self.keys = keys
            self.sync = False
            self.seen_event = True

    def run(self):
        while self.keys is None:
            self.delay(1)
        while True:
            with self:
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
                    if self.ser is not None:
                        CloseSerial(self.ser)
                        self.ser = None
                    break
                except BaseException as e:
                    self.dbg(str(e))
                    if self.ser is not None:
                        CloseSerial(self.ser)
                        self.ser = None
                    self.sync = False
                except:
                    raise

class HifiMonitor(KillableThread):
    def __init__(self, g):
        super(HifiMonitor, self).__init__()
        self.g = g
        self.pending = None

    def dbg(self, msg):
        dbg("hifi: %s" % (msg))

    # Can be called from other threads
    def cmd(self, cmd):
        with self:
            self.pending = cmd
            self.notify()

    def run(self):
        while True:
            try:
                self.check_kill()
                with self:
                    while self.pending is None:
                        self.wait()
                    cmd = self.pending
                    self.pending = None
                os.system("/usr/bin/mpc -h wifihifi %s" % cmd)
            except KeyboardInterrupt:
                self.dbg("Stopped")
                break
            except BaseException as e:
                dbg(str(e))
            except:
                pass

class IRCSpammer(KillableThread):
    def __init__(self, g):
        super(IRCSpammer, self).__init__()
        self.g = g
        self.msgq = []

    def send(self, msg):
        with self:
            self.msgq.append(msg)
            self.notify()

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
            try:
                with self:
                    self.check_kill()
                    while len(self.msgq) == 0:
                        self.wait()
                    msg = self.msgq.pop(0);
                self.really_send(msg)
            except KeyboardInterrupt:
                dbg("irc: Stopped")
                break
            except BaseException as e:
                dbg("irc:" + str(e))
            except:
                pass

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
        self.g.schedule_delay(self.scan_arp, ARP_SCAN_INTERVAL)
        with self:
            self.dbg("scanning table")
            new_ip = set()
            mac_map = {}
            new_mac = set()
            with open("/proc/net/arp") as f:
                # Skip header
                f.readline()
                for l in f:
                    r = l.split()
                    ip = r[0]
                    flags = r[2]
                    mac = r[3]
                    if flags != '0x0' and mac != '00:00:00:00:00:00':
                        new_ip.add(ip)
                        mac_map[mac] = ip
            missing_ip = self.current_ip - new_ip
            self.current_ip = new_ip
            if len(missing_ip) > 0:
                self.ping_pending |= missing_ip
                self.notify()
            new_mac = set(mac_map.keys())
            self.g.dbt.update_arp_entries(new_mac)
            unseen_mac = new_mac - self.current_mac
            self.current_mac = new_mac
            for m in unseen_mac:
                schedule(self.g.dbt.check_bogon, m, mac_map[m])

    def ping(self, ip):
        self.dbg("Pinging %s" % ip)
        try:
            p = subprocess.Popen(["ping", "-c", "1", "-W", "5", ip], \
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            p.communicate()
            p.wait()
        except:
            self.dbg("ping failed")

    def ping_all(self, pending):
        for ip in pending:
            self.check_kill()
            self.ping(ip)

    def run(self):
        self.g.schedule(self.scan_arp)
        while True:
            try:
                with self:
                    pending = self.ping_pending
                    self.ping_pending = set()
                    if len(pending) == 0:
                        self.wait()
                self.ping_all(pending)
            except KeyboardInterrupt:
                self.dbg("Stopped")
                break;
            except BaseException as e:
                self.dbg(str(e))
            except:
                self.dbg("Wonky exception")

class Closure(object):
    def __init__(self, fn, timeout, args, kwargs):
        self.timeout = timeout
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
    def __call__(self):
        self._fn(*self._args, **self._kwargs)
    def __str__(self):
        return "<Closure %s %s %s>" % (self._fn, self._args, self._kwargs)

class Globals(object):
    def __init__(self, config):
        self.config = config
        self.cond = threading.Condition()
        self.triggers = []
        self.threads = []
        self.dbt = self.add_thread(DBThread(self))
        self.door_up = self.add_thread(DoorMonitor(self, "door_up"))
        self.door_down = self.add_thread(DoorMonitor(self, "door_down"))
        self.aux = self.add_thread(AuxMonitor(self, "arduino"))
        self.irc = self.add_thread(IRCSpammer(self))
        self.arp = self.add_thread(ARPMonitor(self))
        self.hifi = self.add_thread(HifiMonitor(self))

    def add_thread(self, t):
        self.threads.append(t)
        t.daemon = True
        return t

    # Run a function from the main thread with no locks held after a delay
    def schedule_delay(self, fn, delay, *args, **kwargs):
        with self.cond:
            self.triggers.append(Closure(fn, time.time()+delay, args, kwargs))
            self.cond.notify()

    # Run a function from the main thread with no locks held
    def schedule(self, fn, *args, **kwargs):
        self.schedule_delay(fn, 0, *args, **kwargs)

    def run(self):
        # Start all the worker threads
        dbg("Starting threads");
        for t in self.threads:
            t.start()
        try:
            while True:
                with self.cond:
                    now = time.time()
                    deadline = None
                    triggers = self.triggers
                    self.triggers = []
                    expired = []
                    for cl in triggers:
                        timeout = cl.timeout
                        if timeout > now:
                            self.triggers.append(cl)
                            if deadline is None or timeout < deadline:
                                deadline = timeout
                        else:
                            expired.append(cl)
                    if len(expired) == 0:
                        if deadline is None:
                            timeout = None
                        else:
                            timeout = deadline - now;
                        dbg("Waiting %s" % (str(timeout)))
                        self.cond.wait(deadline - now)
                for cl in expired:
                    try:
                        cl()
                    except KeyboardInterrupt:
                        dbg("Got kbint")
                        raise
                    except BaseException as e:
                        dbg("main(%s)")
                        traceback.print_exc()
        except KeyboardInterrupt:
            dbg("Got kbint2")
            pass
        finally:
            dbg("Stopping threads")
            for t in self.threads:
                t.kill()
            for t in self.threads:
                t.join(30)
            dbg("Exiting")

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
