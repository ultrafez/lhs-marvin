#include <Arduino.h>
#include <util/crc16.h>
#include "pinmap.h"
#include "tagstore.h"
#include "hexutils.h"

#ifdef EXTERNAL_EEPROM

#define I2C_TIMEOUT 10 // timeout after 10 msec
#include <SoftI2CMaster.h>

#define EEPROMADDR 0xA0 // 8-bit address including RW bit

static uint8_t eeprom_buf[64];
static int eeprom_page = -1;
static bool eeprom_dirty;
#define EEPROM_PAGE_SIZE 64
#define EEPROM_PAGE_MASK (EEPROM_PAGE_SIZE - 1)

static void eeprom_fetch_page(int addr);

static void
eeprom_flush(void)
{
    uint8_t i;

    if (!eeprom_dirty) {
        return;
    }

    // issue a start condition, send device address and write direction bit
    i2c_start_wait(EEPROMADDR | I2C_WRITE);
    // send the address
    if (!i2c_write((eeprom_page >> 8) & 0xFF))
        return;
    if (!i2c_write(eeprom_page & 0xFF))
        return;

    // send data to EEPROM
    for (i = 0; i < 64; i++) {
        i2c_write(eeprom_buf[i]);
    }

    i2c_stop();
    delay(6);
    eeprom_dirty = false;
}

static void
eeprom_fetch_page(int addr)
{
    int n;
    uint8_t *dest;

    addr &= ~EEPROM_PAGE_MASK;
    if (addr == eeprom_page) {
        return;
    }
    eeprom_flush();
    memset(eeprom_buf, 0xff, EEPROM_PAGE_SIZE);
    // issue a start condition, send device address and write direction bit
    i2c_start_wait(EEPROMADDR | I2C_WRITE);
    // send the address
    if (!i2c_write((addr >> 8) & 0xFF))
        return;
    if (!i2c_write(addr & 0xFF))
        return;

    // issue a repeated start condition, send device address and read direction bit
    if (!i2c_rep_start(EEPROMADDR | I2C_READ))
        return;

    // Read data
    dest = eeprom_buf;
    for (n = 0; n < EEPROM_PAGE_SIZE - 1; n++) {
        *(dest++) = i2c_read(false);
    }
    *dest = i2c_read(true);
    i2c_stop();
    eeprom_page = addr;
}

static void
eeprom_write(int addr, uint8_t val) {
    eeprom_fetch_page(addr);
    if (eeprom_buf[addr & EEPROM_PAGE_MASK] != val) {
        eeprom_buf[addr & EEPROM_PAGE_MASK] = val;
        eeprom_dirty = true;
    }
}

uint8_t
static eeprom_read(int addr) {
    eeprom_fetch_page(addr);
    return eeprom_buf[addr & EEPROM_PAGE_MASK];
}

static void
eeprom_init(void)
{
    i2c_init();
}

#else

#include <EEPROM.h>

static void
eeprom_init(void)
{
}

static uint8_t
eeprom_read(int addr)
{
    return EEPROM.read(addr);
}

static void
eeprom_write(int addr, uint8_t val)
{
    if (EEPROM.read(addr) != val) {
        EEPROM.write(addr, val);
    }
}

static void
eeprom_flush(void)
{
}

#endif /* !EXTERNAL_EEPROM */

#define EEPROM_VERSION_OFFSET 63
#define TAG_VERSION_ID 1
#define EEPROM_TAG_START 64
static char eeprom_tag_id[MAX_TAG_LEN + 1];
static char eeprom_tag_pin[MAX_TAG_LEN + 1];

static int eeprom_offset;
static int eeprom_last_offset;

static void
eeprom_rewind()
{
    eeprom_offset = EEPROM_TAG_START;
}

/* Returns false if no more tags are available.  */
static bool
eeprom_read_tag()
{
    uint8_t len;
    uint8_t c;
    uint8_t n;
    char *p;

    if (eeprom_offset < 0) {
        goto fail;
    }
    len = eeprom_read(eeprom_offset);
    if (len == 0xff) {
        goto fail;
    }
    if (eeprom_offset + len + 5 > EEPROM_TAG_END) {
        goto fail;
    }
    eeprom_offset++;

    p = eeprom_tag_id;
    for (n = 0; n < 4; n++) {
        c = eeprom_read(eeprom_offset);
        eeprom_offset++;
        write_hex8(p, c);
        p += 2;
    }
    *p = 0;
    p = eeprom_tag_pin;
    while (len > 0) {
        c = eeprom_read(eeprom_offset);
        eeprom_offset++;
        *(p++) = c;
        len--;
    }
    *p = 0;
    return true;
fail:
    if (eeprom_offset > eeprom_last_offset) {
        eeprom_last_offset = eeprom_offset;
    }
    eeprom_offset = -1;
    *eeprom_tag_id = 0;
    *eeprom_tag_pin = 0;
    return false;
}

static uint16_t
crc_string(uint16_t crc, char *s)
{
    uint8_t val;

    while (*s) {
        val = *(s++);
        crc = _crc_xmodem_update(crc, val);
    }
    return crc;
}

const char *
add_tag(uint8_t *key, int len)
{
    int offset = EEPROM_TAG_START;
    uint8_t c;
    uint8_t val;
    int n;

    // 8 digit ID + ' ' + 4(minimum) digit PIN.
    if (len < 13) {
        return "tag too short";
    }
    if (eeprom_last_offset <= 0) {
        eeprom_rewind();
        while (eeprom_read_tag()) {
            /* No-op */
        }
    }
    offset = eeprom_last_offset;
    // The tag id is saved in binary, which saves us 4 bytes
    if (offset + len - 4 >= EEPROM_TAG_END) {
        return "#tag list full";
    }
    len -= 9;
    eeprom_write(offset, len);
    offset++;
    for (n = 0; n < 4; n++) {
        c = from_hex(key[0]);
        val = from_hex(key[1]);
        if ((c == 0xff) || (val == 0xff)) {
            return "Bad tag";
        }
        val |= c << 4;
        eeprom_write(offset, val);
        offset++;
        key += 2;
    }
    if (*key != ' ') {
        return "Tag too long";
    }
    key++;
    while (len) {
        eeprom_write(offset, *key);
        len--;
        key++;
        offset++;
    }
    eeprom_write(offset, 0xff);
    eeprom_last_offset = offset;
    return NULL;
}

uint16_t
get_tag_hash(void)
{
    uint16_t crc;

    crc = 0;
    eeprom_flush();
    eeprom_rewind();
    while (eeprom_read_tag()) {
        crc = crc_string(crc, eeprom_tag_id);
        crc = _crc_xmodem_update(crc, ' ');
        crc = crc_string(crc, eeprom_tag_pin);
        crc = _crc_xmodem_update(crc, 0);
    }
    Serial.print("# ");
    Serial.print(EEPROM_TAG_END - eeprom_last_offset);
    Serial.println(" bytes EEPROM free");
    return crc;
}

/* Returns false if not found.  */
bool
find_tag(const char *tag, char *pin)
{
    eeprom_rewind();
    while (eeprom_read_tag()) {
        if (strcmp(tag, eeprom_tag_id) == 0) {
            if (pin)
                strcpy(pin, eeprom_tag_pin);
            return true;
        }
    }

    if (pin)
        *pin = 0;

    return false;
}

void
reset_keys(void)
{
    eeprom_write(EEPROM_VERSION_OFFSET, TAG_VERSION_ID);
    eeprom_flush();
    eeprom_write(EEPROM_TAG_START, 0xff);
    eeprom_last_offset = 0;
}

void
init_keys(void)
{
    eeprom_init();
    if (eeprom_read(EEPROM_VERSION_OFFSET) != TAG_VERSION_ID) {
        reset_keys();
    }
}

