/*
 * MCP23017 IO expander support code
 * FIXME: Code is not reentrant.
 * i.e. do not use from interrupt handlers.
 */
 
#include <Arduino.h>
#include <Wire.h>
#include "ioexpander.h"
#include "pinmap.h"

#define MCP23_I2C_ADDR 0x20

#define MCP23_IODIRA 0x00
#define MCP23_IODIRB 0x01
#define MCP23_GPPUA 0x0c
#define MCP23_GPPUB 0x0d
#define MCP23_GPIOA 0x12
#define MCP23_GPIOB 0x13
#define MCP23_IOLATA 0x14
#define MCP23_IOLATB 0x15

static bool done_i2c_init;

static uint16_t remote_iodir;
static uint16_t remote_pullup;
static uint16_t remote_gpio;

static void
remote_write16(uint8_t addr, uint16_t val)
{
  Wire.beginTransmission(MCP23_I2C_ADDR);
  Wire.write(addr);
  Wire.write(val & 0xff);
  Wire.write(val >> 8);
  Wire.endTransmission(true);
}

static void
remote_pins_init(void)
{
  Wire.begin();
  remote_iodir = 0xffff;
#ifdef REMOTE_IO_RST_PIN
  pinMode(REMOTE_IO_RST_PIN, OUTPUT);
  digitalWrite(REMOTE_IO_RST_PIN, LOW);
  delay(1);
  digitalWrite(REMOTE_IO_RST_PIN, HIGH);
  delay(1);
#endif
  // FIXME: Should read current state from IO expander.
  done_i2c_init = true;
}

void
remoteDigitalWrite(uint8_t pin, uint8_t level)
{
  uint16_t old_gpio;

  if (!done_i2c_init)
    remote_pins_init();

  old_gpio = remote_gpio;
  if (level)
    remote_gpio |= (1u << pin);
  else
    remote_gpio &= ~(1u << pin);
  if (remote_gpio == old_gpio)
    return;
  remote_write16(MCP23_IOLATA, remote_gpio);
}

uint8_t
remoteDigitalRead(uint8_t pin)
{
  uint16_t bita;
  uint16_t bitb;
  if (!done_i2c_init)
    remote_pins_init();
  Wire.beginTransmission(MCP23_I2C_ADDR);
  Wire.write(MCP23_GPIOA);
  Wire.endTransmission(false);
  Wire.requestFrom(MCP23_I2C_ADDR, 2, true);
  bita = Wire.read();
  bitb = Wire.read();
  if (pin < 8)
    return (bita & (1 << pin)) ? HIGH : LOW;
  else
    return (bitb & (1 << (pin - 8))) ? HIGH : LOW;
}

void
remotePinMode(uint8_t pin, uint8_t mode)
{
  if (!done_i2c_init)
    remote_pins_init();
  if (mode != OUTPUT) {
      if (mode == INPUT_PULLUP)
	remote_pullup |= 1u << pin;
      else
	remote_pullup &= ~(1u << pin);
      remote_write16(MCP23_GPPUA, remote_pullup);
  }
  if (mode == OUTPUT)
    remote_iodir &= ~(1 << pin);
  else
    remote_iodir |= 1 << pin;
  remote_write16(MCP23_IODIRA, remote_iodir);
}
