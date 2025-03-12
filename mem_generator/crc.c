#include <stdio.h>
int main() {
   int  crc = 0;
	//   char *data = "123456789";
    int data[0] ;
    data[1] = 1;
    data[2] = 2;
    data[3] = 3;
    data[4] = 4;
    data[5] = 5;
    data[6] = 6;
    data[7] = 7;
    data[8] = 8;
    data[9] = 9;
     //{0, 1, 2, 3, 4, 5, 6, 7, 8,9}; 
    // for (size_t i = 0; i < 5; i++)
    // {
    //      printf("CRC-16/CCITT-FALSE: ");
    // }
    
	 size_t len = 10 ;
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
    data[10] = (short)crc;

    //  printf("CRC-16/CCITT-FALSE: 0x%04X\n", crc);

    return (short)crc;
}
