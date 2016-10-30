
ARDUINO_LIBS = EEPROM SPI Wire
ARDUINO_PORT = /dev/ttyACM0

ifeq (1, 1)
RESET_CMD = /bin/true
ARD_PORT = usb
BOARD_TAG = eightmeg
BOARDS_TXT=$(ARDUINO_SKETCHBOOK)/hardware/misc/boards.txt
ARDUINO_VAR_PATH=$(ARDUINO_SKETCHBOOK)/hardware/misc/variants
ARDUINO_CORE_PATH=$(ARDUINO_SKETCHBOOK)/hardware/misc/cores/arduino
else

BOARD_TAG = minimus32
BOARDS_TXT=$(ARDUINO_SKETCHBOOK)/hardware/minimus/boards.txt
ARDUINO_VAR_PATH=$(ARDUINO_SKETCHBOOK)/hardware/minimus/variants
ARDUINO_CORE_PATH=$(ARDUINO_SKETCHBOOK)/hardware/minimus/cores/minimus
endif

include $(HOME)/bin/Arduino.mk

fuses:
	avrdude -P usb -p atmega328p -c stk500v2 -U lfuse:w:0xff:m -U hfuse:w:0xd9:m -U efuse:w:0xfd:m
	#avrdude -P usb -p atmega328p -c stk500v2 -U lfuse:w:0xe2:m -U hfuse:w:0xd9:m -U efuse:w:0xff:m
