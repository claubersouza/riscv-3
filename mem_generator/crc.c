/*
demonstrates how the incorrect check value of 0x29B1 may be reported
for the test string “123456789” when it should be 0xE5CC.
*/
#include <stdio.h>
#include <stdint.h>

short main(void)
{
uint16_t poly = 0x1021 ;
char text[] = {'1','2','3'};
uint16_t bad_crc = 0xffff;
uint16_t ch = 0;
uint16_t teste = 0;
uint16_t i, xor_flag;

short qe = 0;

	for (qe = 0 ; qe < 4; qe++)
	{
	ch= (uint16_t)text[qe];
	

	xor_flag = 0;
    ch =  ch<<=8;
	
    for(i=0; i<8; i++)
    {
		if ((bad_crc ^ ch) & 0x8000)
		{
			xor_flag = 1;
		}
		else
		{
			xor_flag = 0;
		}
		bad_crc = bad_crc << 1;
		if (xor_flag)
		{
			bad_crc = bad_crc ^ poly;
		}
		ch = ch << 1;	
		teste++;		
    }		
}
	
	// printf("CRC-16/CCITT-FALSE: %d\n",  bad_crc);
	//     printf(
    // " Bad_CRC = %d",bad_crc);
    
        return bad_crc;
	//  return (uint16_t)teste;
}
	
