/*
  Door lock
 */
#include <EEPROM.h>
#include <util/crc16.h>
#include "pinmap.h"

#include "mfrc522.h"

#define EEPROM_TAG_START 64
#define EEPROM_TAG_END 1023
#define DEBOUNCE_INTERVAL 100
#define GREEN_PERIOD 5000
#define QUICKLOCK_INTERVAL 1000

#define PIN_INTERVAL 10000
#define FAIL_INTERVAL 2000

#define RFID_SCAN_INTERVAL 500

// These will be inverted when no ping is seen for a while
#define STATUS_ON_PERIOD 2000
#define STATUS_OFF_PERIOD 200

static bool status_lit;
static unsigned long status_timeout;

#ifdef RFID2_CS_PIN
#define SCANOUT_INTERVAL 2000
static unsigned long scanout_time;
#else
#define scanout_time 0ul
#endif

#ifdef SENSE_PIN
#define SENSE_DEBOUNCE_INTERVAL 1000
static bool sense_open;
static unsigned long sense_debounce;
#endif

#ifdef BUTTON_PIN
#define BUTTON_DEBOUNCE_INTERVAL 1000
static bool button_state;
static unsigned long button_debounce;
#endif

// Pin 9 is also used by the RFID module
static const uint8_t kp_row_pin[4] = KP_ROW;
static const uint8_t kp_col_pin[3] = KP_COL;

static bool seen_event;

#define comSerial Serial

static uint32_t current_time;
static uint32_t last_time_tick;

#define PING_TIMEOUT 90
static int ping_ticks;

#define is_alive() (ping_ticks != 0)

#define MAX_TAG_LEN 20
unsigned long relock_time;
static unsigned long quicklock_time;
unsigned long green_time;
unsigned long fail_timeout;
static char last_tag[MAX_TAG_LEN + 1];
static char last_pin[MAX_TAG_LEN + 1];
static char *pin_pos;
static bool pin_valid;
static unsigned long pin_timeout;

#define MAX_MSG_SIZE 32
static uint8_t msg_buf[MAX_MSG_SIZE];
static int msg_buf_len;

// Must be a power of two
#define LOG_BUF_SIZE 256
uint8_t log_buf[LOG_BUF_SIZE];
// Bytes not sent to host
static int log_tail;
// Bytes not acked by host (may need retransmit)
static int log_ack_tail;
// First unused log byte
static int log_head;

uint8_t my_addr = '?';

/* Communication protocol is as follows:
    RS232, 9600 baud, 8N1
    5-pin 180deg DIN (same as MIDI), pinout:
      1 - +12V (Red)
      2 - Ground (Black)
      3 - N/C
      4 - Device data out (host RX) (Purple)
      5 - Device data in (host TX) (White)

    Multiple door lock devices may be connected in a loop with a
    single host pc interface.

    All communication is ASCII text, with the following frame format:
      Message type character (see MSG_* below)
      Address character
      Data bytes (if applicable, variable length)
      CRC16 (4 characters)
      Newline terminator (ascii 0x0A)

    Terminator bytes should never appear elsewhere in the frame.
    A host will typically send 'X\n' to force a frame reset.

    A device initially has an unassigned address ('?'). With the exception
    of MSG_SET_ADDRESS and MSG_PING, a device will pass through commands
    not addressed to it, and drop corrupted frames.  The address byte
    always identifies the device (source or destination depending on
    context).  The host does not have an address, and does not pass through
    messages.

    Messages will always be transmitted as a single, complete frame.

    Tag IDs are hex encoded, with a pair of hex characters for each ID byte.

    Timestamps are base64 encoded unix time values. 6 characters encode a

    Hex characters should be uppercase.

    CRC16 are calculated using the xmodem algorithm and encoded as 4 hex
    characters (big-endian byte order).

    After sending a command, a host should wait for the response before
    sending annother command.  If a response is not recieved then a
    full device re-enumeration should be performed.

    Enumeration commands:

      MSG_SET_ADDRESS
	Enumerate devices.  The address field should initially be set to '0'.
	The device will set its address to the value in the message address
	field.  The device will increment the message address field before
	forwarding this message.
	This allows operation of multiple devices in a ring.
	For a single device the expected response is MSG_SET_ADDRESS with
       	an address of '1'.
	Data: None

      MSG_PING
	Check that all devices are still alive and sync clocks.
	If the device address matches then the device will increment
	the address (as for MSG_SET_ADDRESS) and set its internal clock.
	If the address does not match then the device will set the address
	to '!'.  This indicated something strange has happened and
	full device Enumeration should be performed.
	Data: Current host timestamp

      MSG_COMMENT
	For debug prposes only.  These frames should be ignored, and do not
	follow the normal frame format.  All characters up to the next newline
	should be ignored.

    Host to device commands:

      MSG_LOG_GET
	Read the next log entry.
	Data: None
	Response: MSG_LOG_VALUE

      MSG_LOG_CLEAR
	Discard the current log entry.
	Data: None
	Response: MSG_ACK

      MSG_KEY_RESET
	Revoke all tags.  Resets the CRC returned by MSG_CRC_HASH.
	Data: None
	Response: MSG_ACK

      MSG_KEY_ADD
	Add an access tag.
	Data: Tag ID followed by optional space (ascii 0x20) and PIN
	Response: MSG_ACK

      MSG_KEY_INFO
	Calculate the current keyset hash.  This can be used to determine
       	whether a newly enumerated device matches the current access list.
	Data: None
	Response: MSG_KEY_HASH

    Device to host commands:

      MSG_EVENT
	Indicates something interesting happened.  Maybe be sent at any time,
	including between recipt of a command and transmission of the response.
	(though not in the middle of a message)
	Data: none

      MSG_LOG_VALUE
	The contents of the first log entry.  This must be explicitly
       	cleared with MSG_LOG_CLEAR before the next entry can be accessed.
	A log entry is a 6-byte timestamp, an event byte, and (optinally)
	a tag ID.
	Event bytes are as follows:
	  'R': Tag rejected
	  'P': Incorrect pin entered for tag
	  'U': Door unocked by tag.
	  'O': Door opened
	  'C': Door closed
	  'B': Button pressed
	  'T': Tag scanned out
	Data: Log entry, or empty if there are no remaining log entries.

      MSG_ACK
	Indicate successful completion of MSG_LOG_CLEAR, MSG_KEY_RESET or
	MSG_KEY_ADD command.
	Data: None

      MSG_KEY_HASH
	The hash of the current keyset.  This is the CRC16 of all
	previously MSG_ADD_KEY commands, plus a null terminator
       	after each one.
 */
enum {
    MSG_SET_ADDRESS = 'S',
    MSG_PING = 'P',
    MSG_COMMENT = '#',
    MSG_LOG_GET = 'G',
    MSG_LOG_CLEAR = 'C',
    MSG_KEY_RESET = 'R',
    MSG_KEY_ADD = 'N',
    MSG_KEY_INFO = 'K',
    MSG_EVENT = 'E',
    MSG_ACK = 'A',
    MSG_LOG_VALUE = 'V',
    MSG_KEY_HASH = 'H',
};

static void
init_rfid(void)
{
  MFRC522_Init();
}

// the setup routine runs once when you press reset:
void setup()
{
  comSerial.begin(9600);
}

static unsigned long
now_plus(long ms)
{
  unsigned long when;
  when = millis() + ms;
  if (when == 0)
    when = 1;
  return when;
}

static bool
time_after(unsigned long t)
{
  long delta;
  if (t == 0)
    return false;
  delta = millis() - t;
  return delta >= 0;
}

static char
hex_char(uint8_t val)
{
  if (val < 10)
    return '0' + val;
  else
    return 'A' + val - 10;
}

#if 0
static uint8_t
from_hex(char c)
{
  if (c >= '0' && c <= '9')
    return c - 9;
  if (c >= 'a' && c <= 'f')
    return c + 10 - 'a';
  if (c >= 'a' && c <= 'f')
    return c - 'a';
  return 0;
}
#endif

static void
write_hex8(char *buf, uint8_t val)
{
  buf[0] = hex_char(val >> 4);
  buf[1] = hex_char(val & 0xf);
}

static int
log_inc(int offset)
{
  return (offset + 1) & (LOG_BUF_SIZE - 1);
}

static char
log_pop(void)
{
  char c;

  c = log_buf[log_tail];
  log_tail = log_inc(log_tail);
  return c;
}

static void
log_push(char c)
{
  log_buf[log_head] = c;
  log_head = log_inc(log_head);
}

static uint16_t
calc_crc(const uint8_t *msg, int len)
{
  int i;
  uint16_t crc;

  crc = 0;
  for (i = 0; i < len; i++)
    crc = _crc_xmodem_update(crc, msg[i]);
  return crc;
}

static void
send_crc(const uint8_t *msg, int len)
{
  uint16_t crc;

  crc = calc_crc(msg, len);
  comSerial.write(hex_char(crc >> 12));
  comSerial.write(hex_char((crc >> 8) & 0xf));
  comSerial.write(hex_char((crc >> 4) & 0xf));
  comSerial.write(hex_char(crc & 0xf));
}

static void
send_packet(uint8_t *msg, int len)
{
  comSerial.write(msg, len);
  send_crc(msg, len);
  comSerial.write('\n');
}

static char encode64(int val)
{
  if (val < 26)
    return val + 'A';
  val -= 26;
  if (val < 26)
    return val + 'a';
  val -= 26;
  if (val < 10)
    return val + '0';
  val -= 10;
  if (val == 0)
    return '+';
  if (val == 1)
    return '/';
  return '*';
}

static uint8_t decode64(char c)
{
  if (c >= 'A' && c <= 'Z')
    return c - 'A';
  if (c >= 'a' && c <= 'z')
    return c + 26 - 'a';
  if (c >= '0' && c <= '9')
    return c + 52 - '0';
  if (c == '+')
    return 62;
  if (c == '/')
    return 63;
  // Invalid character
  return 0;
}

static void
log_push_time(void)
{
  uint32_t t;
  int i;
  t = current_time;
  for (i = 0; i < 6; i++)
    {
      log_push(encode64(t & 0x3f));
      t >>= 6;
    }
}

static void
set_time(uint8_t *msg)
{
  int i;
  uint32_t t;

  t = 0;
  for (i = 0; i < 6; i++)
    t |= (uint32_t)decode64(msg[i]) << (i * 6);

  current_time = t;
}

static void
log_tag(char action)
{
  const char *p = last_tag;

  log_push_time();
  log_push(action);
  while (*p)
    log_push(*(p++));
  log_push(0);
  seen_event = true;
}

static void
log_notag(char action)
{
  log_push_time();
  log_push(action);
  log_push(0);
  seen_event = true;
}

/* Returns -1 if not found.  */
static int
find_tag(const char *tag, char *pin)
{
  int offset;
  int match;
  const char *p;
  uint8_t c;

  if (pin)
    *pin = 0;

  offset = EEPROM_TAG_START;
  while (true)
    {
      p = tag;
      match = offset;
      c = EEPROM.read(offset);
      if (c == 0xff || c == EEPROM_TAG_END)
	return -1;
      while (true)
	{
	  offset++;
	  if (c == 0 || c == ' ')
	    break;
	  if (match != -1)
	    {
	      if (c == *p)
		p++;
	      else
		match = -1;
	    }
	  c = EEPROM.read(offset);
	}
      if (match != -1 && *p == 0)
	{
	  if (c == ' ' && pin)
	    {
	      while (c != 0 && offset != EEPROM_TAG_END)
		{
		  c = EEPROM.read(offset);
		  offset++;
		  *pin = c;
		  pin++;
		}
	    }
	  return match;
	}
    }
}

#ifdef RFID2_CS_PIN
static void
tag_scanout(const char *tag)
{
  if (find_tag(tag, last_pin) == -1)
    return;

  if (pin_timeout || scanout_time)
    return;

  strcpy(last_tag, tag);
  log_tag('T');
  scanout_time = now_plus(SCANOUT_INTERVAL);
}
#endif

static void
tag_scanned(const char *tag)
{
  if (find_tag(tag, last_pin) == -1)
    {
      fail_timeout = now_plus(FAIL_INTERVAL);
      pin_pos = NULL;
      pin_valid = false;
      pin_timeout = 0;
      if (strcmp(last_tag, tag) != 0)
	{
	  /* Unrecognised tag.  */
	  strcpy(last_tag, tag);
	  log_tag('R');
	}
      return;
    }

  fail_timeout = 0;
  pin_timeout = now_plus(PIN_INTERVAL);
  /* Ignore tag rescans unless they got the pin wrong.  */
  if (pin_pos && strcmp(last_tag, tag) == 0 && pin_valid)
    return;

  /* Wait for user to enter PIN.  */
  strcpy(last_tag, tag);
  pin_pos = last_pin;
  pin_valid = true;
}

static void
unlock_door(void)
{
  unsigned long old_time;

  old_time = relock_time;
  relock_time = now_plus(UNLOCK_PERIOD);
  green_time = now_plus(GREEN_PERIOD);

  if (old_time)
    return;

  log_tag('U');

  digitalWrite(LOCK_PIN, LOCK_ON);
}

static void
lock_door(void)
{
  relock_time = 0;
  quicklock_time = 0;
  last_tag[0] = 0;
  digitalWrite(LOCK_PIN, LOCK_OFF);
}

static void
send_log_packet(void)
{
  int i;
  char c;
  uint8_t buf[MAX_TAG_LEN + 3];

  buf[0] = MSG_LOG_VALUE;
  buf[1] = my_addr;
  i = 2;
  log_tail = log_ack_tail;
  while (log_head != log_tail)
    {
      c = log_pop();
      if (c == 0)
	break;
      buf[i++] = c;
    }
  send_packet(buf, i);
}

static void
send_ack(void)
{
  uint8_t buf[5];
  buf[0] = MSG_ACK;
  buf[1] = my_addr;
  send_packet(buf, 2);
}

static void
eeprom_update(int offset, uint8_t val)
{
  if (EEPROM.read(offset) != val)
    EEPROM.write(offset, val);
}

static void
add_key(uint8_t *key, int len)
{
  int offset = EEPROM_TAG_START;
  uint8_t c;

  while (true)
    {
      c = EEPROM.read(offset);
      if (c == 0xff || offset == EEPROM_TAG_END)
	break;
      offset++;
    }
  if (offset + len >= EEPROM_TAG_END)
    {
      Serial.println("#tag list full");
      return;
    }
  while (len)
    {
      eeprom_update(offset, *key);
      len--;
      key++;
      offset++;
    }
  eeprom_update(offset++, 0);
  eeprom_update(offset, 0xff);
  send_ack();
}

static void
reset_keys(void)
{
  eeprom_update(EEPROM_TAG_START, 0xff);
  send_ack();
}

static void
key_info(void)
{
  uint8_t buf[6];
  uint16_t crc;
  int offset;
  uint8_t val;

  buf[0] = MSG_KEY_HASH;
  buf[1] = my_addr;
  crc = 0;
  offset = EEPROM_TAG_START;
  while (true)
    {
      val = EEPROM.read(offset);
      if (val == 0xff || val == EEPROM_TAG_END)
	break;
      crc = _crc_xmodem_update(crc, val);
      offset++;
    }
  write_hex8((char *)buf + 2, crc >> 8);
  write_hex8((char *)buf + 4, crc & 0xff);
  send_packet(buf, 6);
}

static void
process_msg(uint8_t *msg, int len)
{
  if (msg[0] == MSG_SET_ADDRESS)
    {
      my_addr = msg[1];
      msg[1]++;
    }
  else if (msg[0] == MSG_PING)
    {
      if (msg[1] != my_addr)
	msg[1] = '!';
      else
	{
	  msg[1]++;
	  if (len == 8)
	    set_time(msg + 2);
	  ping_ticks = PING_TIMEOUT;
	}
    }
  else if (msg[0] != MSG_COMMENT)
    {
      if (msg[1] != my_addr)
	return;
      switch (msg[0])
	{
	case MSG_LOG_CLEAR:
	  if (len != 2)
	    return;
	  log_ack_tail = log_tail;
	  send_ack();
	  return;
	case MSG_LOG_GET:
	  if (len != 2)
	    break;
	  send_log_packet();
	  return;
	case MSG_KEY_RESET:
	  if (len != 2)
	    return;
	  reset_keys();
	  return;
	case MSG_KEY_ADD:
	  if (len < 4)
	    return;
	  add_key(msg + 2, len - 2);
	  return;
	case MSG_KEY_INFO:
	  if (len != 2)
	    return;
	  key_info();
	  return;
	default:
	  break;
	}
    }

  send_packet(msg, len);
}

/* Return true for corrupted packets.  */
static bool
verify_crc(const uint8_t *msg, int len)
{
  // TODO: Implement this
  return false;
}

static bool
is_terminator(char c)
{
  return (c == '\n' || c == '\r');
}

static void
do_serial(void)
{
  char c;

  while (comSerial.available())
    {
      c = comSerial.read();
      if (is_terminator(c))
	{
	  if (msg_buf_len >= 6)
	    {
	      if (!verify_crc(msg_buf, msg_buf_len))
		process_msg(msg_buf, msg_buf_len - 4);
	    }
	  msg_buf_len = 0;
	}
      else
	msg_buf[msg_buf_len++] = c;
    }
  if (seen_event)
    {
      uint8_t buf[2];

      buf[0] = MSG_EVENT;
      buf[1] = my_addr;
      send_packet(buf, 2);
      seen_event = false;
    }
}

static void
do_rfid(void)
{
  uint8_t uid[7];
  uint8_t uid_len;
  char ascii_tag[15];
  int i;
  static unsigned long next_scan;

  if (next_scan && !time_after(next_scan))
    return;

  next_scan = now_plus(RFID_SCAN_INTERVAL);

  if (relock_time || green_time || scanout_time)
    return;

  uid_len = MFRC522_GetID(uid, RFID1_RST_PIN, RFID1_CS_PIN);
  if (uid_len > 0)
    {
      char *p = ascii_tag;
      for (i = 0; i < uid_len; i++)
	{
	  write_hex8(p, uid[i]);
	  p += 2;
	}
      *p = 0;
      tag_scanned(ascii_tag);
      return;
    }

#ifdef RFID2_CS_PIN
  if (is_alive())
    {
      uid_len = MFRC522_GetID(uid, RFID2_RST_PIN, RFID2_CS_PIN);
      if (uid_len > 0)
	{
	  char *p = ascii_tag;
	  for (i = 0; i < uid_len; i++)
	    {
	      write_hex8(p, uid[i]);
	      p += 2;
	    }
	  *p = 0;
	  tag_scanout(ascii_tag);
	  return;
	}
    }
#endif
}

static void
do_timer(void)
{
  if (time_after(relock_time) || time_after(quicklock_time))
    lock_door();

  if (time_after(green_time))
    green_time = 0;

#ifdef RFID2_CS_PIN
  if (time_after(scanout_time))
    scanout_time = 0;
#endif

  if (time_after(pin_timeout))
    {
      log_tag('P');
      pin_timeout = 0;
      pin_pos = NULL;
      pin_valid = false;
      fail_timeout = now_plus(FAIL_INTERVAL);
    }

  if (time_after(fail_timeout))
    {
      fail_timeout = 0;
    }

  if (pin_pos && *pin_pos == 0 && pin_valid)
    {
      pin_pos = NULL;
      pin_valid = false;
      pin_timeout = 0;
      unlock_door();
    }

  if ((long)(millis() - last_time_tick) > 1000)
    {
      last_time_tick += 1000;
      current_time++;
      if (ping_ticks > 0)
	ping_ticks--;
    }

  if (status_timeout == 0 || time_after(status_timeout))
    {
      bool led_on;

      status_lit = !status_lit;
      led_on = status_lit;
      if (ping_ticks == 0)
	led_on = !led_on;
      digitalWrite(STATUS_PIN, led_on ? STATUS_ON : STATUS_OFF);
      status_timeout = now_plus(status_lit ? STATUS_ON_PERIOD : STATUS_OFF_PERIOD);
    }
}

static void
do_keypad(void)
{
  static unsigned long debounce_time;
  static char last_char;
  int row;
  int col;
  int n;
  unsigned long now;
  char c;

  for (n = 0; n < 3; n++)
    pinMode(kp_col_pin[n], INPUT);
  for (row = 0; row < 4; row++)
    pinMode(kp_row_pin[row], INPUT_PULLUP);

  n = -1;
  for (col = 0; col < 3; col++)
    {
      pinMode(kp_col_pin[col], OUTPUT);
      digitalWrite(kp_col_pin[col], 0);
      for (row = 0; row < 4; row++)
	{
	  if (digitalRead(kp_row_pin[row]) == 0)
	    {
	      if (n == -1)
		n = col + row * 3;
	      else
		n = -2;
	    }
	}
      pinMode(kp_col_pin[col], INPUT);
    }
  for (row = 0; row < 4; row++)
    pinMode(kp_row_pin[row], INPUT);

  if (n < 0)
    c = 0;
  else if (n < 9)
    c = '1' + n;
  else if (n == 9)
    c = '*';
  else if (n == 10)
    c = '0';
  else /* n == 11 */
    c = '#';


  now = millis();
  if (c == 0)
    {
      if (debounce_time && (now - debounce_time) >= DEBOUNCE_INTERVAL)
	{
	  debounce_time = 0;
	  last_char = 0;
	}
      return;
    }

  debounce_time = now;
  if (c == last_char)
    return;

  Serial.print("#Key:");
  Serial.println(c);
  last_char = c;
  debounce_time = now;

  if (pin_pos)
    {
      if (c == *pin_pos)
	pin_pos++;
      else
	pin_valid = false;
      pin_timeout = now_plus(PIN_INTERVAL);
    }
}

static void
do_buttons(void)
{
#ifdef SENSE_PIN
  if (time_after(sense_debounce))
    sense_debounce = 0;
  if (!sense_debounce) {
      bool old_sense;

      old_sense = sense_open;
      sense_open = digitalRead(SENSE_PIN) == 0;
      if (sense_open != old_sense) {
	  sense_debounce = now_plus(SENSE_DEBOUNCE_INTERVAL);
	  if (sense_open && relock_time && quicklock_time == 0) {
	      quicklock_time = now_plus(QUICKLOCK_INTERVAL);
	  }
	  log_notag(sense_open ? 'O' : 'C');
      }
  }
#endif
#ifdef RELEASE_PIN
  if (!digitalRead(RELEASE_PIN))
    {
      strcpy(last_tag, "MAGIC");
      unlock_door();
    }
#endif
#ifdef BUTTON_PIN
  if (time_after(button_debounce))
    button_debounce = 0;
  if (!button_debounce)
    {
      if (!digitalRead(BUTTON_PIN))
	{
	  if (!button_state)
	    {
	      sense_debounce = now_plus(SENSE_DEBOUNCE_INTERVAL);
	      button_state = true;
	      if (is_alive())
		log_notag('B');
	    }
	}
      else if (button_state)
	{
	  sense_debounce = now_plus(SENSE_DEBOUNCE_INTERVAL);
	  button_state = false;
	}
    }
#endif
}

static void
do_leds(void)
{
  digitalWrite(LED_R_PIN, fail_timeout || scanout_time ? LED_ON : LED_OFF);
  digitalWrite(LED_G_PIN, green_time ? LED_ON : LED_OFF);
  digitalWrite(LED_B_PIN, pin_timeout || scanout_time ? LED_ON : LED_OFF);
#ifdef SCANOUT_LED_PIN
  digitalWrite(SCANOUT_LED_PIN, scanout_time ? SCANOUT_LED_ON : SCANOUT_LED_OFF);
#endif
}

// the loop routine runs over and over again forever:
void loop()
{
  comSerial.println("#Hello");

  pinMode(RFID1_RST_PIN, OUTPUT);
  digitalWrite(RFID1_RST_PIN, LOW);

#ifdef RFID2_CS_PIN
  pinMode(RFID2_RST_PIN, OUTPUT);
  digitalWrite(RFID2_RST_PIN, LOW);
#endif

#ifdef RELEASE_PIN
  pinMode(RELEASE_PIN, INPUT_PULLUP);
#endif
#ifdef SENSE_PIN
  pinMode(SENSE_PIN, INPUT_PULLUP);
#endif
#ifdef BUTTON_PIN
  pinMode(BUTTON_PIN, INPUT_PULLUP);
#endif
  init_rfid();
  last_time_tick = millis();
  pinMode(LOCK_PIN, OUTPUT);
  digitalWrite(LOCK_PIN, LOCK_OFF);
  pinMode(STATUS_PIN, OUTPUT);
  digitalWrite(STATUS_PIN, STATUS_ON);

  pinMode(LED_R_PIN, OUTPUT);
  digitalWrite(LED_R_PIN, LED_OFF);
  pinMode(LED_G_PIN, OUTPUT);
  digitalWrite(LED_G_PIN, LED_ON);
  pinMode(LED_B_PIN, OUTPUT);
  digitalWrite(LED_B_PIN, LED_OFF);

#ifdef SCANOUT_LED_PIN
  pinMode(SCANOUT_LED_PIN, OUTPUT);
  digitalWrite(SCANOUT_LED_PIN, SCANOUT_LED_OFF);
#endif

  while (1)
    {
      do_rfid();
      do_buttons();
      do_keypad();
      do_timer();
      do_serial();
      do_leds();
    }
}
