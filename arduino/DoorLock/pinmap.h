#ifndef PINMAP_H
#define PINMAP_H

//#define UPSTAIRS 1
//#define DOWNSTAIRS 1
#define THIRD_DOOR 1


#include "ioexpander.h"

// IO expander pins
#define GPA(n) (100 + (n))
#define GPB(n) (108 + (n))

#ifdef UPSTAIRS

#define LED_R_PIN 7
#define LED_G_PIN 6
#define LED_B_PIN 5
#define LED_ON 1
#define LED_OFF 0

// Pin 9 is also used by the RFID module
#define KP_ROW {9, GPB(5), GPB(4), GPB(3)}
#define KP_COL {GPB(2), GPB(1), GPB(0)}

// Pin 9 also used by keypad
#define RFID1_CS_PIN 9
#define RFID1_RST_PIN 8

#define RFID2_CS_PIN GPA(7)
#define RFID2_RST_PIN GPA(1)

#define SCANOUT_LED_PIN GPA(4)
#define SCANOUT_LED_ON 0
#define SCANOUT_LED_OFF 1

#define SENSE_PIN 3

//#define BUTTON_PIN GPA(0)
// Internal release button
#define RELEASE_PIN GPA(0)


#define UNLOCK_PERIOD 10000

// Blinkenlight
#define STATUS_PIN 4
#define STATUS_OFF 1
#define STATUS_ON 0

#define REMOTE_IO_RST_PIN A3

#define EXTERNAL_EEPROM 1

#endif /* UPSTAIRS */


#ifdef DOWNSTAIRS

/* downstairs keypad link cable pinout:
    GND-1 8-RST
    3v3-2 7-MOSI
    SDA-3 6-MISO
    SCL-4 5-SCK */

#define LED_R_PIN GPB(2)
#define LED_G_PIN GPB(0)
#define LED_B_PIN GPB(1)
#define LED_ON 0
#define LED_OFF 1

#define KP_ROW {GPA(7), GPA(6), GPA(1), GPA(2)}
#define KP_COL {GPA(5), GPA(4), GPA(3)}

#define RFID1_CS_PIN GPB(6)
#define RFID1_RST_PIN GPB(7)

// Lock remains open once activated, so only need to trigger for a short amount of time.
#define UNLOCK_PERIOD 1000

// Blinkenlight
#define STATUS_PIN 4
#define STATUS_OFF 1
#define STATUS_ON 0

#define REMOTE_IO_RST_PIN A3

#define SENSE_PIN 8

#endif /* DOWNSTAIRS */


#ifdef THIRD_DOOR

/* downstairs keypad link cable pinout:
    GND-1 8-RST
    3v3-2 7-MOSI
    SDA-3 6-MISO
    SCL-4 5-SCK */

#define LED_R_PIN GPB(2)
#define LED_G_PIN GPB(0)
#define LED_B_PIN GPB(1)
#define LED_ON 1
#define LED_OFF 0

#define KP_ROW {GPA(1), GPA(2), GPA(7), GPA(6)}
#define KP_COL {GPA(3), GPA(4), GPA(5)}

#define RFID1_CS_PIN GPB(6)
#define RFID1_RST_PIN GPB(7)

// Lock remains open once activated, so only need to trigger for a short amount of time.
#define UNLOCK_PERIOD 1000

// Blinkenlight
#define STATUS_PIN 4
#define STATUS_OFF 0
#define STATUS_ON 1

#define REMOTE_IO_RST_PIN A2

#define SENSE_PIN 8

#define RELEASE_PIN A2

#define EXTERNAL_EEPROM 1

#endif /* THIRD_DOOR */


#ifndef RFID1_CS_PIN
#error Must select a config
#endif


// Lock release
#define LOCK_PIN 2
#define LOCK_OFF 0
#define LOCK_ON 1

#ifdef EXTERNAL_EEPROM

#define SDA_PORT PORTC
#define SDA_PIN 1 // A1
#define SCL_PORT PORTC
#define SCL_PIN 0 // A0

// AT24C256 (32kbyte) external EEPROM
#define EEPROM_TAG_END 0x7fff

#else

// 1kbyte internal EEPROM
#define EEPROM_TAG_END 1023

#endif

#endif
