
ARDUINO_LIBS = SoftwareSerial EEPROM SPI
ARDUINO_PORT = /dev/ttyACM0

ifeq (1, 1)
RESET_CMD = /bin/true
ARDUINO_PORT = usb
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
