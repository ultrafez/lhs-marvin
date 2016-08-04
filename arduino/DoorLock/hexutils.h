static char
hex_char(uint8_t val)
{
  if (val < 10)
    return '0' + val;
  else
    return 'A' + val - 10;
}

static uint8_t __attribute__((__unused__))
from_hex(char c)
{
  if (c >= '0' && c <= '9')
    return c - '0';
  if (c >= 'a' && c <= 'f')
    return c + 10 - 'a';
  if (c >= 'A' && c <= 'F')
    return c + 10 - 'A';
  return 0xff;
}

static void
write_hex8(char *buf, uint8_t val)
{
  buf[0] = hex_char(val >> 4);
  buf[1] = hex_char(val & 0xf);
}

