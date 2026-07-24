#include <stdio.h>

int main(void)
{
    unsigned int crc = 0xFFFFFFFF;
    unsigned int data;

    data = '1';
    crc ^= data;

    for (unsigned int j = 0; j < 8; j++)
    {
        if (crc & 1)
            crc = (crc >> 1) ^ 0xEDB88320;
        else
            crc >>= 1;
    }

    data = '2';
    crc ^= data;

    for (unsigned int j = 0; j < 8; j++)
    {
        if (crc & 1)
            crc = (crc >> 1) ^ 0xEDB88320;
        else
            crc >>= 1;
    }

    data = '3';
    crc ^= data;

    for (unsigned int j = 0; j < 8; j++)
    {
        if (crc & 1)
            crc = (crc >> 1) ^ 0xEDB88320;
        else
            crc >>= 1;
    }

    data = '4';
    crc ^= data;

    for (unsigned int j = 0; j < 8; j++)
    {
        if (crc & 1)
            crc = (crc >> 1) ^ 0xEDB88320;
        else
            crc >>= 1;
    }

    return (int)(~crc);
}