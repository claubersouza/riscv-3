#include <stdint.h>

#define AES_BLOCK_SIZE         16U
#define AES256_KEY_SIZE        32U
#define AES256_ROUNDS          14U
#define AES256_ROUND_KEY_SIZE  240U

/*
 * Resultado completo da criptografia.
 * Pode ser inspecionado na memória pelo testbench.
 */
volatile uint8_t ciphertext[AES_BLOCK_SIZE];

/*
 * Chave AES-256:
 *
 * D4A91F6C83B72EE15A0C947FD8E32651
 * C7F40B9A6D18E25CF3A17B80E94D62AF
 */
static const uint8_t key[AES256_KEY_SIZE] = {
    0xD4, 0xA9, 0x1F, 0x6C,
    0x83, 0xB7, 0x2E, 0xE1,
    0x5A, 0x0C, 0x94, 0x7F,
    0xD8, 0xE3, 0x26, 0x51,
    0xC7, 0xF4, 0x0B, 0x9A,
    0x6D, 0x18, 0xE2, 0x5C,
    0xF3, 0xA1, 0x7B, 0x80,
    0xE9, 0x4D, 0x62, 0xAF
};

/*
 * Plaintext: "teste"
 *
 * AES/CBC/NoPadding exige exatamente 16 bytes.
 * Os 11 bytes restantes são preenchidos manualmente com zero.
 *
 * Hexadecimal:
 * 74657374650000000000000000000000
 */
static const uint8_t plaintext[AES_BLOCK_SIZE] = {
    0x74, 0x65, 0x73, 0x74,
    0x65, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00
};

/*
 * IV interno zerado:
 * 00000000000000000000000000000000
 */
static const uint8_t iv[AES_BLOCK_SIZE] = {
    0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00
};

static const uint8_t sbox[256] = {
    0x63,0x7C,0x77,0x7B,0xF2,0x6B,0x6F,0xC5,
    0x30,0x01,0x67,0x2B,0xFE,0xD7,0xAB,0x76,
    0xCA,0x82,0xC9,0x7D,0xFA,0x59,0x47,0xF0,
    0xAD,0xD4,0xA2,0xAF,0x9C,0xA4,0x72,0xC0,
    0xB7,0xFD,0x93,0x26,0x36,0x3F,0xF7,0xCC,
    0x34,0xA5,0xE5,0xF1,0x71,0xD8,0x31,0x15,
    0x04,0xC7,0x23,0xC3,0x18,0x96,0x05,0x9A,
    0x07,0x12,0x80,0xE2,0xEB,0x27,0xB2,0x75,
    0x09,0x83,0x2C,0x1A,0x1B,0x6E,0x5A,0xA0,
    0x52,0x3B,0xD6,0xB3,0x29,0xE3,0x2F,0x84,
    0x53,0xD1,0x00,0xED,0x20,0xFC,0xB1,0x5B,
    0x6A,0xCB,0xBE,0x39,0x4A,0x4C,0x58,0xCF,
    0xD0,0xEF,0xAA,0xFB,0x43,0x4D,0x33,0x85,
    0x45,0xF9,0x02,0x7F,0x50,0x3C,0x9F,0xA8,
    0x51,0xA3,0x40,0x8F,0x92,0x9D,0x38,0xF5,
    0xBC,0xB6,0xDA,0x21,0x10,0xFF,0xF3,0xD2,
    0xCD,0x0C,0x13,0xEC,0x5F,0x97,0x44,0x17,
    0xC4,0xA7,0x7E,0x3D,0x64,0x5D,0x19,0x73,
    0x60,0x81,0x4F,0xDC,0x22,0x2A,0x90,0x88,
    0x46,0xEE,0xB8,0x14,0xDE,0x5E,0x0B,0xDB,
    0xE0,0x32,0x3A,0x0A,0x49,0x06,0x24,0x5C,
    0xC2,0xD3,0xAC,0x62,0x91,0x95,0xE4,0x79,
    0xE7,0xC8,0x37,0x6D,0x8D,0xD5,0x4E,0xA9,
    0x6C,0x56,0xF4,0xEA,0x65,0x7A,0xAE,0x08,
    0xBA,0x78,0x25,0x2E,0x1C,0xA6,0xB4,0xC6,
    0xE8,0xDD,0x74,0x1F,0x4B,0xBD,0x8B,0x8A,
    0x70,0x3E,0xB5,0x66,0x48,0x03,0xF6,0x0E,
    0x61,0x35,0x57,0xB9,0x86,0xC1,0x1D,0x9E,
    0xE1,0xF8,0x98,0x11,0x69,0xD9,0x8E,0x94,
    0x9B,0x1E,0x87,0xE9,0xCE,0x55,0x28,0xDF,
    0x8C,0xA1,0x89,0x0D,0xBF,0xE6,0x42,0x68,
    0x41,0x99,0x2D,0x0F,0xB0,0x54,0xBB,0x16
};

static const uint8_t rcon[15] = {
    0x00, 0x01, 0x02, 0x04,
    0x08, 0x10, 0x20, 0x40,
    0x80, 0x1B, 0x36, 0x6C,
    0xD8, 0xAB, 0x4D
};

static void copy_bytes(
    uint8_t *destination,
    const uint8_t *source,
    uint32_t length)
{
    uint32_t i;

    for (i = 0U; i < length; i++) {
        destination[i] = source[i];
    }
}

static uint8_t xtime(uint8_t value)
{
    uint8_t result;

    result = (uint8_t)(value << 1U);

    if ((value & 0x80U) != 0U) {
        result ^= 0x1BU;
    }

    return result;
}

static void add_round_key(
    uint8_t state[AES_BLOCK_SIZE],
    const uint8_t *round_key)
{
    uint32_t i;

    for (i = 0U; i < AES_BLOCK_SIZE; i++) {
        state[i] ^= round_key[i];
    }
}

static void sub_bytes(uint8_t state[AES_BLOCK_SIZE])
{
    uint32_t i;

    for (i = 0U; i < AES_BLOCK_SIZE; i++) {
        state[i] = sbox[state[i]];
    }
}

static void shift_rows(uint8_t state[AES_BLOCK_SIZE])
{
    uint8_t temp;

    temp = state[1];
    state[1] = state[5];
    state[5] = state[9];
    state[9] = state[13];
    state[13] = temp;

    temp = state[2];
    state[2] = state[10];
    state[10] = temp;

    temp = state[6];
    state[6] = state[14];
    state[14] = temp;

    temp = state[3];
    state[3] = state[15];
    state[15] = state[11];
    state[11] = state[7];
    state[7] = temp;
}

static void mix_columns(uint8_t state[AES_BLOCK_SIZE])
{
    uint32_t column;

    for (column = 0U; column < 4U; column++) {
        uint32_t index;

        uint8_t a0;
        uint8_t a1;
        uint8_t a2;
        uint8_t a3;
        uint8_t total;

        index = column * 4U;

        a0 = state[index];
        a1 = state[index + 1U];
        a2 = state[index + 2U];
        a3 = state[index + 3U];

        total = (uint8_t)(a0 ^ a1 ^ a2 ^ a3);

        state[index] =
            (uint8_t)(
                a0 ^
                total ^
                xtime((uint8_t)(a0 ^ a1))
            );

        state[index + 1U] =
            (uint8_t)(
                a1 ^
                total ^
                xtime((uint8_t)(a1 ^ a2))
            );

        state[index + 2U] =
            (uint8_t)(
                a2 ^
                total ^
                xtime((uint8_t)(a2 ^ a3))
            );

        state[index + 3U] =
            (uint8_t)(
                a3 ^
                total ^
                xtime((uint8_t)(a3 ^ a0))
            );
    }
}

static void aes256_key_expansion(
    const uint8_t aes_key[AES256_KEY_SIZE],
    uint8_t round_keys[AES256_ROUND_KEY_SIZE])
{
    uint32_t generated_bytes;
    uint32_t rcon_index;
    uint8_t temp[4];

    generated_bytes = AES256_KEY_SIZE;
    rcon_index = 1U;

    copy_bytes(
        round_keys,
        aes_key,
        AES256_KEY_SIZE
    );

    while (generated_bytes < AES256_ROUND_KEY_SIZE) {
        uint32_t i;

        temp[0] = round_keys[generated_bytes - 4U];
        temp[1] = round_keys[generated_bytes - 3U];
        temp[2] = round_keys[generated_bytes - 2U];
        temp[3] = round_keys[generated_bytes - 1U];

        if ((generated_bytes % AES256_KEY_SIZE) == 0U) {
            uint8_t first;

            first = temp[0];

            temp[0] = temp[1];
            temp[1] = temp[2];
            temp[2] = temp[3];
            temp[3] = first;

            temp[0] = sbox[temp[0]];
            temp[1] = sbox[temp[1]];
            temp[2] = sbox[temp[2]];
            temp[3] = sbox[temp[3]];

            temp[0] ^= rcon[rcon_index];
            rcon_index++;
        }
        else if ((generated_bytes % AES256_KEY_SIZE) == 16U) {
            temp[0] = sbox[temp[0]];
            temp[1] = sbox[temp[1]];
            temp[2] = sbox[temp[2]];
            temp[3] = sbox[temp[3]];
        }
        else {
            /* Nenhuma transformação adicional. */
        }

        for (i = 0U; i < 4U; i++) {
            round_keys[generated_bytes] =
                (uint8_t)(
                    round_keys[
                        generated_bytes - AES256_KEY_SIZE
                    ] ^
                    temp[i]
                );

            generated_bytes++;

            if (generated_bytes >= AES256_ROUND_KEY_SIZE) {
                break;
            }
        }
    }
}

static void aes256_encrypt_block(
    const uint8_t input[AES_BLOCK_SIZE],
    uint8_t output[AES_BLOCK_SIZE],
    const uint8_t round_keys[AES256_ROUND_KEY_SIZE])
{
    uint8_t state[AES_BLOCK_SIZE];
    uint32_t round;

    copy_bytes(
        state,
        input,
        AES_BLOCK_SIZE
    );

    /*
     * Rodada inicial.
     */
    add_round_key(
        state,
        &round_keys[0]
    );

    /*
     * Rodadas 1 até 13.
     */
    for (round = 1U; round < AES256_ROUNDS; round++) {
        sub_bytes(state);
        shift_rows(state);
        mix_columns(state);

        add_round_key(
            state,
            &round_keys[round * AES_BLOCK_SIZE]
        );
    }

    /*
     * Rodada final, sem MixColumns.
     */
    sub_bytes(state);
    shift_rows(state);

    add_round_key(
        state,
        &round_keys[AES256_ROUNDS * AES_BLOCK_SIZE]
    );

    copy_bytes(
        output,
        state,
        AES_BLOCK_SIZE
    );
}

/*
 * AES-256-CBC para um único bloco de 16 bytes.
 *
 * Como o IV é zero, no primeiro bloco:
 *
 * plaintext XOR IV = plaintext
 */
static void aes256_cbc_encrypt_one_block(
    const uint8_t input[AES_BLOCK_SIZE],
    volatile uint8_t output[AES_BLOCK_SIZE],
    const uint8_t aes_key[AES256_KEY_SIZE])
{
    uint8_t round_keys[AES256_ROUND_KEY_SIZE];
    uint8_t block[AES_BLOCK_SIZE];
    uint8_t encrypted_block[AES_BLOCK_SIZE];
    uint32_t i;

    aes256_key_expansion(
        aes_key,
        round_keys
    );

    /*
     * Operação CBC:
     * bloco de entrada = plaintext XOR IV.
     */
    for (i = 0U; i < AES_BLOCK_SIZE; i++) {
        block[i] = (uint8_t)(input[i] ^ iv[i]);
    }

    aes256_encrypt_block(
        block,
        encrypted_block,
        round_keys
    );

    for (i = 0U; i < AES_BLOCK_SIZE; i++) {
        output[i] = encrypted_block[i];
    }
}

int main(void)
{
    uint32_t result;

    aes256_cbc_encrypt_one_block(
        plaintext,
        ciphertext,
        key
    );

    /*
     * O RISC-V RV32I retorna valores de 32 bits
     * pelo registrador a0.
     *
     * Retorna os quatro primeiros bytes do ciphertext,
     * usando ordem big-endian:
     *
     * result[31:24] = ciphertext[0]
     * result[23:16] = ciphertext[1]
     * result[15:8]  = ciphertext[2]
     * result[7:0]   = ciphertext[3]
     */
    result =
        ((uint32_t)ciphertext[0] << 24U) |
        ((uint32_t)ciphertext[1] << 16U) |
        ((uint32_t)ciphertext[2] << 8U)  |
        ((uint32_t)ciphertext[3]);

    return (int)result;
}