#include <stdio.h>
int main() {
    short crc = 0xFFFF;
	char data[] = {0x31,0x32,0x33,0x34,0x35,0x36,0x37,0x38,0x39};
	size_t len = 9 ;
    for (size_t pos = 0; pos < len; pos++) {
        crc ^= (short)data[pos] << 8;

        for (int i = 0; i < 8; i++) {
            if (crc & 0x8000) {
                crc = (crc << 1) ^ 0x1021;
            } else {
                crc <<= 1;
            }
        }
    }

    printf("CRC-16/CCITT-FALSE: 0x%04X\n", crc);

    return 32;
}
