#include <stdio.h>

typedef unsigned int u32;

#define ROTR(x, n) (((x) >> (n)) | ((x) << (32U - (n))))

#define ROUND(K, W)                                                   \
    do {                                                              \
        s1 = ROTR(e, 6U) ^ ROTR(e, 11U) ^ ROTR(e, 25U);              \
        ch = (e & f) ^ ((~e) & g);                                    \
        t1 = h + s1 + ch + (K) + (W);                                 \
                                                                       \
        s0 = ROTR(a, 2U) ^ ROTR(a, 13U) ^ ROTR(a, 22U);              \
        maj = (a & b) ^ (a & c) ^ (b & c);                            \
        t2 = s0 + maj;                                                 \
                                                                       \
        h = g;                                                         \
        g = f;                                                         \
        f = e;                                                         \
        e = d + t1;                                                    \
        d = c;                                                         \
        c = b;                                                         \
        b = a;                                                         \
        a = t1 + t2;                                                   \
    } while (0)

int main(void)
{
    u32 w[64];
    u32 i;

    u32 a = 0x6a09e667U;
    u32 b = 0xbb67ae85U;
    u32 c = 0x3c6ef372U;
    u32 d = 0xa54ff53aU;
    u32 e = 0x510e527fU;
    u32 f = 0x9b05688cU;
    u32 g = 0x1f83d9abU;
    u32 h = 0x5be0cd19U;

    u32 s0;
    u32 s1;
    u32 ch;
    u32 maj;
    u32 t1;
    u32 t2;

    /*
     * Bloco SHA-256 pronto para a mensagem "1234".
     *
     * 0x31323334 = ASCII "1234"
     * 0x80000000 = padding
     * 0x00000020 = tamanho da mensagem: 32 bits
     */
    w[0] = 0x31323334U;
    w[1] = 0x80000000U;

    for (i = 2U; i < 15U; i++) {
        w[i] = 0U;
    }

    w[15] = 0x00000020U;

    /*
     * Expansão das 16 palavras para 64 palavras.
     */
    for (i = 16U; i < 64U; i++) {
        s0 =
            ROTR(w[i - 15U], 7U) ^
            ROTR(w[i - 15U], 18U) ^
            (w[i - 15U] >> 3U);

        s1 =
            ROTR(w[i - 2U], 17U) ^
            ROTR(w[i - 2U], 19U) ^
            (w[i - 2U] >> 10U);

        w[i] =
            w[i - 16U] +
            s0 +
            w[i - 7U] +
            s1;
    }

    /*
     * As constantes estão diretamente nas instruções.
     * Não existe tabela K[64].
     */
    ROUND(0x428a2f98U, w[0]);
    ROUND(0x71374491U, w[1]);
    ROUND(0xb5c0fbcfU, w[2]);
    ROUND(0xe9b5dba5U, w[3]);
    ROUND(0x3956c25bU, w[4]);
    ROUND(0x59f111f1U, w[5]);
    ROUND(0x923f82a4U, w[6]);
    ROUND(0xab1c5ed5U, w[7]);
    ROUND(0xd807aa98U, w[8]);
    ROUND(0x12835b01U, w[9]);
    ROUND(0x243185beU, w[10]);
    ROUND(0x550c7dc3U, w[11]);
    ROUND(0x72be5d74U, w[12]);
    ROUND(0x80deb1feU, w[13]);
    ROUND(0x9bdc06a7U, w[14]);
    ROUND(0xc19bf174U, w[15]);
    ROUND(0xe49b69c1U, w[16]);
    ROUND(0xefbe4786U, w[17]);
    ROUND(0x0fc19dc6U, w[18]);
    ROUND(0x240ca1ccU, w[19]);
    ROUND(0x2de92c6fU, w[20]);
    ROUND(0x4a7484aaU, w[21]);
    ROUND(0x5cb0a9dcU, w[22]);
    ROUND(0x76f988daU, w[23]);
    ROUND(0x983e5152U, w[24]);
    ROUND(0xa831c66dU, w[25]);
    ROUND(0xb00327c8U, w[26]);
    ROUND(0xbf597fc7U, w[27]);
    ROUND(0xc6e00bf3U, w[28]);
    ROUND(0xd5a79147U, w[29]);
    ROUND(0x06ca6351U, w[30]);
    ROUND(0x14292967U, w[31]);
    ROUND(0x27b70a85U, w[32]);
    ROUND(0x2e1b2138U, w[33]);
    ROUND(0x4d2c6dfcU, w[34]);
    ROUND(0x53380d13U, w[35]);
    ROUND(0x650a7354U, w[36]);
    ROUND(0x766a0abbU, w[37]);
    ROUND(0x81c2c92eU, w[38]);
    ROUND(0x92722c85U, w[39]);
    ROUND(0xa2bfe8a1U, w[40]);
    ROUND(0xa81a664bU, w[41]);
    ROUND(0xc24b8b70U, w[42]);
    ROUND(0xc76c51a3U, w[43]);
    ROUND(0xd192e819U, w[44]);
    ROUND(0xd6990624U, w[45]);
    ROUND(0xf40e3585U, w[46]);
    ROUND(0x106aa070U, w[47]);
    ROUND(0x19a4c116U, w[48]);
    ROUND(0x1e376c08U, w[49]);
    ROUND(0x2748774cU, w[50]);
    ROUND(0x34b0bcb5U, w[51]);
    ROUND(0x391c0cb3U, w[52]);
    ROUND(0x4ed8aa4aU, w[53]);
    ROUND(0x5b9cca4fU, w[54]);
    ROUND(0x682e6ff3U, w[55]);
    ROUND(0x748f82eeU, w[56]);
    ROUND(0x78a5636fU, w[57]);
    ROUND(0x84c87814U, w[58]);
    ROUND(0x8cc70208U, w[59]);
    ROUND(0x90befffaU, w[60]);
    ROUND(0xa4506cebU, w[61]);
    ROUND(0xbef9a3f7U, w[62]);
    ROUND(0xc67178f2U, w[63]);

    /*
     * Retorna o primeiro word do SHA-256 de "1234".
     *
     * Resultado esperado:
     * x10/a0 = 0x03ac6742
     */
    return (int)(0x6a09e667U + a);
}