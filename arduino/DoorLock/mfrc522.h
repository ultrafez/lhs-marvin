#ifndef MFRC522_H
#define MFRC255_H

void MFRC522_Init(void);
int MFRC522_GetID(uint8_t *uid, uint8_t reset_pin, uint8_t cs);

#endif
