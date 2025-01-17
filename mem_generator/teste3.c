#include <stdio.h>
#include <string.h>

short crc16_ccitt_false(*data, int len) {
    short crc = 0xFFFF;

    for (int pos = 0; pos < len; pos++) {
        crc ^= (short)data[pos] << 8;

        for (int i = 0; i < 8; i++) {
            if (crc & 0x8000) {
                crc = (crc << 1) ^ 0x1021;
            } else {
                crc <<= 1;
            }
        }
    }

    return crc;
}

int main() {
    char *data = "123456789"; 
    int len = strlen(data); 

    short crc = crc16_ccitt_false(data, len); 

    printf("CRC-16/CCITT-FALSE: 0x%04X\n", crc);

    return 0;
}