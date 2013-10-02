#ifndef IOEXPANDER_H
#define IOEXPANDER_H

#define REMOTE_FIRST_PIN 100

void remoteDigitalWrite(uint8_t pin, uint8_t level);
uint8_t remoteDigitalRead(uint8_t pin);
void remotePinMode(uint8_t pin, uint8_t mode);

static inline void
augmentedPinMode(uint8_t pin, uint8_t mode)
{
  if (pin < REMOTE_FIRST_PIN)
    pinMode(pin, mode);
  else
    remotePinMode(pin - REMOTE_FIRST_PIN, mode);
}

static inline void
augmentedDigitalWrite(uint8_t pin, uint8_t level)
{
  if (pin < REMOTE_FIRST_PIN)
    digitalWrite(pin, level);
  else
    remoteDigitalWrite(pin - REMOTE_FIRST_PIN, level);
}

static inline uint8_t
augmentedDigitalRead(uint8_t pin)
{
  if (pin < REMOTE_FIRST_PIN)
    return digitalRead(pin);
  else
    return remoteDigitalRead(pin - REMOTE_FIRST_PIN);
}

#define digitalWrite augmentedDigitalWrite
#define digitalRead augmentedDigitalRead
#define pinMode augmentedPinMode

#endif
