#include <stdio.h>

typedef unsigned int u32;

#define ROTL(x, n) (((x) << (n)) | ((x) >> (32U - (n))))

#define STEP(F, A, B, C, D, X, T, S) \
    A = B + ROTL(A + F(B, C, D) + X + T, S)

#define F(x, y, z) ((x & y) | (~x & z))
#define G(x, y, z) ((x & z) | (y & ~z))
#define H(x, y, z) (x ^ y ^ z)
#define I(x, y, z) (y ^ (x | ~z))

int main(void)
{
    u32 x[16];
    u32 a = 0x67452301U;
    u32 b = 0xefcdab89U;
    u32 c = 0x98badcfeU;
    u32 d = 0x10325476U;

    u32 aa = a;
    u32 bb = b;
    u32 cc = c;
    u32 dd = d;

    u32 i;
    u32 result;

    /*
     * Bloco MD5 pronto para "1234".
     *
     * MD5 usa little-endian.
     */
    x[0] = 0x34333231U;
    x[1] = 0x00000080U;

    for (i = 2U; i < 14U; i++) {
        x[i] = 0U;
    }

    x[14] = 32U;
    x[15] = 0U;

    /* Rodada 1 */
    STEP(F, a, b, c, d, x[0],  0xd76aa478U, 7U);
    STEP(F, d, a, b, c, x[1],  0xe8c7b756U, 12U);
    STEP(F, c, d, a, b, x[2],  0x242070dbU, 17U);
    STEP(F, b, c, d, a, x[3],  0xc1bdceeeU, 22U);

    STEP(F, a, b, c, d, x[4],  0xf57c0fafU, 7U);
    STEP(F, d, a, b, c, x[5],  0x4787c62aU, 12U);
    STEP(F, c, d, a, b, x[6],  0xa8304613U, 17U);
    STEP(F, b, c, d, a, x[7],  0xfd469501U, 22U);

    STEP(F, a, b, c, d, x[8],  0x698098d8U, 7U);
    STEP(F, d, a, b, c, x[9],  0x8b44f7afU, 12U);
    STEP(F, c, d, a, b, x[10], 0xffff5bb1U, 17U);
    STEP(F, b, c, d, a, x[11], 0x895cd7beU, 22U);

    STEP(F, a, b, c, d, x[12], 0x6b901122U, 7U);
    STEP(F, d, a, b, c, x[13], 0xfd987193U, 12U);
    STEP(F, c, d, a, b, x[14], 0xa679438eU, 17U);
    STEP(F, b, c, d, a, x[15], 0x49b40821U, 22U);

    /* Rodada 2 */
    STEP(G, a, b, c, d, x[1],  0xf61e2562U, 5U);
    STEP(G, d, a, b, c, x[6],  0xc040b340U, 9U);
    STEP(G, c, d, a, b, x[11], 0x265e5a51U, 14U);
    STEP(G, b, c, d, a, x[0],  0xe9b6c7aaU, 20U);

    STEP(G, a, b, c, d, x[5],  0xd62f105dU, 5U);
    STEP(G, d, a, b, c, x[10], 0x02441453U, 9U);
    STEP(G, c, d, a, b, x[15], 0xd8a1e681U, 14U);
    STEP(G, b, c, d, a, x[4],  0xe7d3fbc8U, 20U);

    STEP(G, a, b, c, d, x[9],  0x21e1cde6U, 5U);
    STEP(G, d, a, b, c, x[14], 0xc33707d6U, 9U);
    STEP(G, c, d, a, b, x[3],  0xf4d50d87U, 14U);
    STEP(G, b, c, d, a, x[8],  0x455a14edU, 20U);

    STEP(G, a, b, c, d, x[13], 0xa9e3e905U, 5U);
    STEP(G, d, a, b, c, x[2],  0xfcefa3f8U, 9U);
    STEP(G, c, d, a, b, x[7],  0x676f02d9U, 14U);
    STEP(G, b, c, d, a, x[12], 0x8d2a4c8aU, 20U);

    /* Rodada 3 */
    STEP(H, a, b, c, d, x[5],  0xfffa3942U, 4U);
    STEP(H, d, a, b, c, x[8],  0x8771f681U, 11U);
    STEP(H, c, d, a, b, x[11], 0x6d9d6122U, 16U);
    STEP(H, b, c, d, a, x[14], 0xfde5380cU, 23U);

    STEP(H, a, b, c, d, x[1],  0xa4beea44U, 4U);
    STEP(H, d, a, b, c, x[4],  0x4bdecfa9U, 11U);
    STEP(H, c, d, a, b, x[7],  0xf6bb4b60U, 16U);
    STEP(H, b, c, d, a, x[10], 0xbebfbc70U, 23U);

    STEP(H, a, b, c, d, x[13], 0x289b7ec6U, 4U);
    STEP(H, d, a, b, c, x[0],  0xeaa127faU, 11U);
    STEP(H, c, d, a, b, x[3],  0xd4ef3085U, 16U);
    STEP(H, b, c, d, a, x[6],  0x04881d05U, 23U);

    STEP(H, a, b, c, d, x[9],  0xd9d4d039U, 4U);
    STEP(H, d, a, b, c, x[12], 0xe6db99e5U, 11U);
    STEP(H, c, d, a, b, x[15], 0x1fa27cf8U, 16U);
    STEP(H, b, c, d, a, x[2],  0xc4ac5665U, 23U);

    /* Rodada 4 */
    STEP(I, a, b, c, d, x[0],  0xf4292244U, 6U);
    STEP(I, d, a, b, c, x[7],  0x432aff97U, 10U);
    STEP(I, c, d, a, b, x[14], 0xab9423a7U, 15U);
    STEP(I, b, c, d, a, x[5],  0xfc93a039U, 21U);

    STEP(I, a, b, c, d, x[12], 0x655b59c3U, 6U);
    STEP(I, d, a, b, c, x[3],  0x8f0ccc92U, 10U);
    STEP(I, c, d, a, b, x[10], 0xffeff47dU, 15U);
    STEP(I, b, c, d, a, x[1],  0x85845dd1U, 21U);

    STEP(I, a, b, c, d, x[8],  0x6fa87e4fU, 6U);
    STEP(I, d, a, b, c, x[15], 0xfe2ce6e0U, 10U);
    STEP(I, c, d, a, b, x[6],  0xa3014314U, 15U);
    STEP(I, b, c, d, a, x[13], 0x4e0811a1U, 21U);

    STEP(I, a, b, c, d, x[4],  0xf7537e82U, 6U);
    STEP(I, d, a, b, c, x[11], 0xbd3af235U, 10U);
    STEP(I, c, d, a, b, x[2],  0x2ad7d2bbU, 15U);
    STEP(I, b, c, d, a, x[9],  0xeb86d391U, 21U);

    aa += a;
    bb += b;
    cc += c;
    dd += d;

    /*
     * Primeiros 32 bits do MD5 de "1234":
     * 81dc9bdb
     */
    result =
        ((aa & 0x000000ffU) << 24U) |
        ((aa & 0x0000ff00U) << 8U)  |
        ((aa & 0x00ff0000U) >> 8U)  |
        ((aa & 0xff000000U) >> 24U);

    return (int)result;
}