#ifndef TAGSTORE_H
#define TAGSTORE_H

#define MAX_TAG_LEN 20

void reset_keys(void);
void init_keys(void);
const char *add_tag(uint8_t *key, int len);
uint16_t get_tag_hash(void);
/* Returns false if not found.  */
bool find_tag(const char *tag, char *pin);

#endif
