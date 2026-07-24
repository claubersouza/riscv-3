import json

def extrair_campos(instrucao_bin):
    return {
        "funct7": instrucao_bin[0:7],
        "rs2": instrucao_bin[7:12],
        "rs1": instrucao_bin[12:17],
        "funct3": instrucao_bin[17:20],
        "rd": instrucao_bin[20:25],
        "opcode": instrucao_bin[25:32]
    }

def comparar_instrucoes(instr1, instr2):
    if len(instr1) != 32 or len(instr2) != 32:
        return {
            "erro": "As duas instruções devem conter exatamente 32 bits."
        }

    campos1 = extrair_campos(instr1)
    campos2 = extrair_campos(instr2)

    resultado = {
        "instrucao_1": instr1,
        "instrucao_2": instr2,
        "comparacao": {}
    }

    for campo in campos1:
        resultado["comparacao"][campo] = {
            "instrucao_1": campos1[campo],
            "instrucao_2": campos2[campo],
            "iguais": campos1[campo] == campos2[campo]
        }

    return resultado

# Exemplo de uso
instrucao1 = "00000101101000000000011110010011"
instrucao2 = "00000111100000000000011110010011"

json_resultado = comparar_instrucoes(instrucao1, instrucao2)

# Exportar como string JSON formatada:
json.dumps(json_resultado, indent=2)
funct7_instr1 = json_resultado["comparacao"]["funct7"]["instrucao_1"]
funct7_instr2 = json_resultado["comparacao"]["funct7"]["instrucao_2"]
iguais = json_resultado["comparacao"]["funct7"]["iguais"]

# print(f"funct7 instr1: {funct7_instr1}")
# print(f"funct7 instr2: {funct7_instr2}")
# print(f"Iguais? {iguais}")

for campo, detalhes in json_resultado["comparacao"].items():
    if not detalhes["iguais"]:
        print(f"⚠️ Campo diferente: {campo}")
        print(f"  Instrucao 1: {detalhes['instrucao_1']}")
        print(f"  Instrucao 2: {detalhes['instrucao_2']}")


        


