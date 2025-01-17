unsigned short ch, i;
	i = 0;
    text_length= 0;

           unsigned short z2, xor_flag2;

    
   		 ch<<=8;

			for(z2=0; z2<8; z2++)
			{
				if ((bad_crc ^ ch) & 0x8000)
				{
					xor_flag2 = 1;
				}
				else
				{
					xor_flag2 = 0;
				}
				bad_crc = bad_crc << 1;
				if (xor_flag2)
				{
					bad_crc = bad_crc ^ poly;
				}
				ch = ch << 1;
			}
        z2++;
        text_length++;
    

	bad_crc = 0xffff;

    while((ch=text[i])!=0)
    {
           unsigned short z, xor_flag;

    /*
    Why are they shifting this byte left by 8 bits??
    How do the low bits of the poly ever see it?
    */
   		 ch<<=8;

			for(z=0; z<8; z++)
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
        z++;
        text_length++;
    }