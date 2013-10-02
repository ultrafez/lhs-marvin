#ifndef PINMAP_H
#define PINMAP_H

//#define UPSTAIRS 1
//#define DOWNSTAIRS 1


#ifdef UPSTAIRS

#define LED_R_PIN 7
#define LED_G_PIN 6
#define LED_B_PIN 5
#define LED_ON 1
#define LED_OFF 0

// Pin 9 is also used by the RFID module
#define KP_ROW {9, A0, A1, A2}
#define KP_COL {A3, A4, A5}

// Pin 9 also used by keypad
#define RFID_CS_PIN 9
#define NRSTPD 8

#define SENSE_PIN 3

#define UNLOCK_PERIOD 10000

// Blinkenlight
#define STATUS_PIN 4
#define STATUS_OFF 1
#define STATUS_ON 0

#endif /* UPSTAIRS */


#ifdef DOWNSTAIRS

#include "ioexpander.h"

/* downstairs keypad link cable pinout:
    GND-1 8-
    3v3-2 7-MOSI
    SDA-3 6-MISO
    SCL-4 5-SCK */

// IO expander pins
#define GPA(n) (100 + (n))
#define GPB(n) (108 + (n))

#define LED_R_PIN GPB(2)
#define LED_G_PIN GPB(0)
#define LED_B_PIN GPB(1)
#define LED_ON 0
#define LED_OFF 1

#define KP_ROW {GPA(7), GPA(6), GPA(2), GPA(1)}
#define KP_COL {GPA(5), GPA(4), GPA(3)}

#define RFID_CS_PIN GPB(6)
#define NRSTPD GPB(7)

// Lock remains open once activated, so only need to trigger for a short amount of time.
#define UNLOCK_PERIOD 1000

// Blinkenlight
#define STATUS_PIN 4
#define STATUS_OFF 1
#define STATUS_ON 0

#endif /* DOWNSTAIRS */


#ifndef RFID_CS_PIN
#error Must select a config
#endif


// Lock release
#define LOCK_PIN 2
#define LOCK_OFF 0
#define LOCK_ON 1

// Internal release button
//#define RELEASE_PIN 3

#endif
