/*
demonstrates how the incorrect check value of 0x29B1 may be reported
for the test string “123456789” when it should be 0xE5CC.
*/
#include <stdio.h>
#include <string.h>

#define           poly     0x1021          /* crc-ccitt mask */

/* global variables */
char text[1000];
unsigned short good_crc;
unsigned short bad_crc;
unsigned short text_length;

int main(void)
{
    sprintf(text, "%s", "123456789");
       go();

    return 0;
}

void go(void)
{


    unsigned short ch, i;

    good_crc = 0xffff;
    bad_crc = 0xffff;
    i = 0;
    text_length= 0;
    while((ch=text[i])!=0)
    {
        update_bad_crc(ch);
        i++;
        text_length++;
    }

    printf(
    " Bad_CRC = %04X ",bad_crc
    );
}

void repeat_character(unsigned char ch, unsigned short n)
{
    unsigned short i;
    for (i=0; i<n; i++)
    {
        text[i] = ch;
    }
    text[n] = 0;
}

void update_bad_crc(unsigned short ch)
{
    /* based on code found at
    http://www.programmingparadise.com/utility/crc.html
    */

    unsigned short i, xor_flag;

    /*
    Why are they shifting this byte left by 8 bits??
    How do the low bits of the poly ever see it?
    */
    ch<<=8;

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
    }
}