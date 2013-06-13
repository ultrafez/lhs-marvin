/*
  Door lock
 */
#include <EEPROM.h>
#include <util/crc16.h>

#define RFID_522 1

#if defined(RFID_SERIAL)
#include <SoftwareSerial.h> 
#elif defined(RFID_532)
#include <Adafruit_NFCShield_I2C.h>
#elif defined(RFID_522)
#include "mfrc522.h"
#endif

#define EEPROM_TAG_START 64
#define EEPROM_TAG_END 1023
#define UNLOCK_PERIOD 5000
#define DEBOUNCE_INTERVAL 100

#define PIN_INTERVAL 5000
#define FAIL_INTERVAL 2000

#define RFID_SCAN_INTERVAL 500

#define LED_R_PIN 7
#define LED_G_PIN 6
#define LED_B_PIN 5
#define LED_ON 1
#define LED_OFF 0

// Internal release button
#define RELEASE_PIN 3

#define STATUS_PIN 4

#define LOCK_PIN 2
#define LOCK_OFF 0
#define LOCK_ON 1

// Blinkenlight
#define STATUS_PIN 4
#define STATUS_OFF 1
#define STATUS_ON 0

#define STATUS_ON_PERIOD 200
#define STATUS_OFF_PERIOD 2000

static bool status_lit;
static unsigned long status_timeout;

// Pin 9 is also used by the RFID module
static const uint8_t kp_row_pin[4] = {9, A0, A1, A2};
static const uint8_t kp_col_pin[3] = {A3, A4, A5};

#ifdef RFID_SERIAL
#define RFID_RX 2
#define RFID_TX 3

SoftwareSerial rfidSerial(RFID_RX, RFID_TX);

#elif defined(RFID_532)
#define NFC_IRQ   (4)

Adafruit_NFCShield_I2C nfc(A3, A2);
#elif defined(RFID_522)

#else
#endif

// Color convention for serial wires:
//  White: Computer->Door
//  Purple: Door->Computer
#define comSerial Serial

uint32_t current_time;
uint32_t last_time_tick;

#define MAX_TAG_LEN 20
unsigned long relock_time;
unsigned long fail_timeout;
static char last_tag[MAX_TAG_LEN + 1];
static char last_pin[MAX_TAG_LEN + 1];
static char *pin_pos;
static bool pin_valid;
static unsigned long pin_timeout;

#define MAX_MSG_SIZE 32
static uint8_t msg_buf[MAX_MSG_SIZE];
int msg_buf_len;

// Must be a power of two
#define LOG_BUF_SIZE 1024
uint8_t log_buf[LOG_BUF_SIZE];
int log_tail;
int log_head;

uint8_t my_addr = '?';

enum {
    MSG_SET_ADDRESS = 'S',
    MSG_ACK = 'A',
    MSG_EVENT = 'E',
    MSG_GET_LOG = 'G',
    MSG_LOG_VALUE = 'V',
    MSG_PING = 'P',
    MSG_COMMENT = '#',
    MSG_KEY = 'K',
};

#if defined(RFID_SERIAL)
static void
init_rfid(void)
{
  rfidSerial.begin(9600);
}
#elif defined(RFID_532)
static void
init_rfid(void)
{
  uint32_t ver;

  nfc.begin();
  ver = nfc.getFirmwareVersion();
  if (!ver)
    die();

  nfc.setPassiveActivationRetries(0x01);
  nfc.SAMConfig();
}
#elif defined(RFID_522)
static void
init_rfid(void)
{
  MFRC522_Init();
}
#else
#endif

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
  uint8_t buf[2];

  log_push_time();
  log_push(action);
  while (*p)
    log_push(*(p++));
  log_push(0);
  buf[0] = MSG_EVENT;
  buf[1] = my_addr;
  send_packet(buf, 2);
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

static void
tag_scanned(const char *tag)
{
  if (find_tag(tag, last_pin) == -1)
    {
      if (strcmp(last_tag, tag) != 0)
	{
	  /* Unrecognised tag.  */
	  strcpy(last_tag, tag);
	  log_tag('R');
	  fail_timeout = now_plus(FAIL_INTERVAL);
	  pin_pos = NULL;
	  pin_valid = false;
	  pin_timeout = 0;
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

  if (old_time)
    return;

  log_tag('O');

  digitalWrite(LOCK_PIN, LOCK_ON);
}

static void
lock_door(void)
{
  relock_time = 0;
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

  if (find_tag((char *)key, NULL) != -1)
    {
      send_ack();
      return;
    }

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
  uint8_t buf[7];
  uint16_t crc;
  int offset;
  uint8_t val;

  buf[0] = MSG_KEY;
  buf[1] = my_addr;
  buf[2] = 'i';
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
  write_hex8((char *)buf + 3, crc >> 8);
  write_hex8((char *)buf + 5, crc & 0xff);
  send_packet(buf, 7);
}

static void
process_msg(uint8_t *msg, int len)
{
  if (len < 1)
    return;

  switch (msg[0])
    {
    case MSG_SET_ADDRESS:
      if (len < 2)
	return;
      my_addr = msg[1];
      msg[1]++;
      break;
    case MSG_ACK:
      if (msg[1] != my_addr)
	break;
      return;
    case MSG_GET_LOG:
      if (len != 2)
	break;
      if (msg[1] != my_addr)
	break;
      send_log_packet();
      return;
    case MSG_PING:
      if (len < 2)
	return;
      if (msg[1] != my_addr)
	{
	  msg[1] = '!';
	  break;
	}
      msg[1]++;
      if (len == 8)
	set_time(msg + 2);
      break;
    case MSG_COMMENT:
      break;
    case MSG_KEY:
      if (len < 3)
	return;
      if (msg[1] != my_addr)
	break;
      if (msg[2] == '+')
	add_key(msg + 3, len - 3);
      else if (msg[2] == '*')
	reset_keys();
      else if (msg[2] == '?')
	key_info();
      return;
    default:
      break;
    }

  send_packet(msg, len);
}

/* Return true for corrupted packets.  */
static bool
verify_crc(const uint8_t *msg, int len)
{
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

  if (comSerial.available())
    {
      c = comSerial.read();
      if (is_terminator(c))
	{
	  if (msg_buf_len > 4)
	    {
	      if (!verify_crc(msg_buf, msg_buf_len))
		process_msg(msg_buf, msg_buf_len - 4);
	    }
	  msg_buf_len = 0;
	}
      else
	msg_buf[msg_buf_len++] = c;
    }
}

#if defined(RFID_SERIAL)
static void
do_rfid(void)
{
  static char tag[MAX_TAG_LEN + 1];
  static int tag_len = -1;
  char c;

  if (!rfidSerial.available())
    return;
  c = rfidSerial.read();
  if (c == 2)
    {
      tag_len = 0;
    }
  else if (tag_len >= 0)
    {
      if (c == 3)
	{
	  tag[tag_len] = 0;
	  unlock_door(tag);
	  tag_len = -1;
	}
      else if (tag_len >= MAX_TAG_LEN)
	{
	  tag_len = -1;
	}
      else
	{
	  tag[tag_len++] = c;
	}
    }
}
#elif defined(RFID_532)
static void
do_rfid(void)
{
  boolean success;
  uint8_t uid[7];
  uint8_t uid_len;
  char ascii_tag[15];
  int i;
  static unsigned long next_scan;

  if (next_scan && !time_after(next_scan))
    return;

  next_scan = now_plus(RFID_SCAN_INTERVAL);
  success = nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, &uid[0], &uid_len);
  if (success)
    {
      char *p = ascii_tag;
      for (i = 0; i < uid_len; i++)
	{
	  write_hex8(p, uid[i]);
	  p += 2;
	}
      *p = 0;
      unlock_door(ascii_tag);
    }
}
#elif defined(RFID_522)
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

  if (relock_time)
    return;

  uid_len = MFRC522_GetID(uid);
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
    }
}
#else
static void
do_rfid(void)
{
}
#endif

static void
do_timer(void)
{
  if (time_after(relock_time))
    lock_door();

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
    }

  if (status_timeout == 0 || time_after(status_timeout))
    {
      status_lit = !status_lit;
      digitalWrite(STATUS_PIN, status_lit ? STATUS_ON : STATUS_OFF);
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
  if (!digitalRead(RELEASE_PIN))
    {
      strcpy(last_tag, "MAGIC");
      unlock_door();
    }
}

static void
do_leds(void)
{
  digitalWrite(LED_R_PIN, fail_timeout ? LED_ON : LED_OFF);
  digitalWrite(LED_G_PIN, relock_time ? LED_ON : LED_OFF);
  digitalWrite(LED_B_PIN, pin_timeout ? LED_ON : LED_OFF);
}

// the loop routine runs over and over again forever:
void loop()
{
  comSerial.println("#Hello");

  pinMode(RELEASE_PIN, INPUT_PULLUP);
  init_rfid();
  last_time_tick = millis();
  pinMode(LOCK_PIN, OUTPUT);
  digitalWrite(LOCK_PIN, LOCK_OFF);
  pinMode(STATUS_PIN, OUTPUT);
  digitalWrite(STATUS_PIN, STATUS_OFF);

  pinMode(LED_R_PIN, OUTPUT);
  digitalWrite(LED_R_PIN, LED_OFF);
  pinMode(LED_G_PIN, OUTPUT);
  digitalWrite(LED_G_PIN, LED_OFF);
  pinMode(LED_B_PIN, OUTPUT);
  digitalWrite(LED_B_PIN, LED_OFF);

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
