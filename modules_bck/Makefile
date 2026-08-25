SIM := iverilog
OUT := riscv_output
MODULES := ../modules

.PHONY: all check compile run clean

all: run

check:
	@test -f $(MODULES)/dmem.hex || (echo "ERRO: arquivo $(MODULES)/dmem.hex nao encontrado"; exit 1)
	@test -f $(MODULES)/imem_custom.hex || (echo "ERRO: arquivo $(MODULES)/imem_custom.hex nao encontrado"; exit 1)

compile: check
	$(SIM) -g2012 -f filelist.txt -o $(OUT)

run: compile
	vvp $(OUT)

clean:
	rm -f $(OUT) pipeline.vcd
