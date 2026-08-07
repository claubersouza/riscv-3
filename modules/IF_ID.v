////////////////////////////////////////////////////////////
// stage 1: fetch/decode
////////////////////////////////////////////////////////////
module IF_ID 
#(
    parameter [31:0]             RESET = 32'h0000_0000
    )
(
input                   clk,
input                   reset,
input                   stall,
output reg              exception,  

// interface of instruction Memory
input                   inst_mem_is_valid,
input           [31: 0] inst_mem_read_data

);

//////////////// Including OPCODES ////////////////////////////
`include "opcode.vh"

// function [4:0] somar_4bits (input [3:0] num1, input [3:0] num2);
// begin
//   somar_4bits = num1 + num2;
// end
// endfunction
task teste2 (input [31:0] inst1, output reg [31:0] value);
  begin
    if (inst1 == 32'h078007D3) begin
      value = 32'h07800793;
    end
    else begin
      value = inst1;
    end
  end
endtask

function [31:0] teste (input [31:0] inst1);
    // reg [31:0] inst2_local; // Variável local para armazenar o valor a ser retornado

    begin
        if (inst1 == 32'h078007D3) begin
            teste = inst1;
              
        end
        else begin
           teste = inst1;
        end
         // Atribui o valor a ser retornado (para inst2)
    end
endfunction
////////////////////////////////////////////////////////////////
// IF stage Start
////////////////////////////////////////////////////////////////
// A CUSTOM_SW3 faz o salto da segunda palavra já no estágio de fetch/decode.
// Portanto não é necessário inserir bolha quando ela chega ao execute.
assign pipe.instruction = pipe.stall_read ? NOP : teste(inst_mem_read_data);

integer counter ;
reg [31: 0] reg2;
initial begin
    counter = 0;
    
end
always @(pipe.instruction) begin
    counter = counter + 1;
end

// check for illegal instruction(instruction not in RV-32I architecture)

always @(posedge clk or negedge reset) 
begin
if (!reset)
    exception           <= 1'b0;
    
else if (!pipe.stall_read)
    exception <= pipe.illegal_inst || (pipe.inst_mem_address[1:0] != 2'b00);
end


// Stall read assignment for stalling while reading 

always @(posedge clk or negedge reset) 
begin
if (!reset) 
begin
    pipe.stall_read             <= 1'b1;
end else 
begin
    // A CUSTOM_LW2 precisa travar já no ciclo em que é reconhecida.
    // custom_lw2_seen permite liberar o pipeline depois da FSM sem redisparo.
    // Trava na primeira detecção e permanece travado somente enquanto a FSM
    // está ocupada. Depois de WRITE2, custom_lw2_seen=1 permite liberar o PC
    // mesmo que a palavra CUSTOM ainda esteja na saída da IMEM.
    // Para a FSM genérica de store, o pipeline deve travar já quando a
    // palavra customizada aparece na saída da IMEM. O sinal custom_sw_seen
    // permite liberar o PC somente depois de WRITE1 e WRITE2 terminarem.
    // IMPORTANTE: o stall começa somente depois que a instrução já foi
    // decodificada. Usar pipe.instruction aqui fazia a própria instrução virar
    // NOP antes de custom_sw3/custom_sw4/custom_sw6 serem registrados.
    pipe.stall_read <= stall ||
                       (((pipe.custom_sw3 || pipe.custom_sw6) &&
                         !pipe.custom_sw_seen)) ||
                       pipe.custom_sw_busy ||
                       pipe.custom_lw3_busy ||
                       ((pipe.instruction == 32'h000407db) && !pipe.custom_lw3_seen);
end
end

////////////////////////////////////////////////////////////////
// IF stage end
////////////////////////////////////////////////////////////////

////////////////////////////////////////////////////////////////
// ID stage 
////////////////////////////////////////////////////////////////

always @* 
begin
pipe.immediate                     = 32'h0;
pipe.illegal_inst                  = 1'b0;
// $display("Valor:%h",pipe.instruction[`OPCODE]);
 
case(pipe.instruction[`OPCODE])
    JALR  : pipe.immediate      = {{20{pipe.instruction[31]}}, pipe.instruction[31:20]}; // I-Type 
    BRANCH: pipe.immediate      = {{20{pipe.instruction[31]}}, pipe.instruction[7], pipe.instruction[30:25], pipe.instruction[11:8], 1'b0}; // B-type
    LOAD  : pipe.immediate      = {{20{pipe.instruction[31]}}, pipe.instruction[31:20]}; // I-type
    STORE : pipe.immediate      = {{20{pipe.instruction[31]}}, pipe.instruction[31:25], pipe.instruction[11:7]}; // S-type
    ARITHI: pipe.immediate      = (pipe.instruction[`FUNC3] == SLL || pipe.instruction[`FUNC3] == SR) ? {27'h0, pipe.instruction[24:20]} : {{20{pipe.instruction[31]}}, pipe.instruction[31:20]}; // I-type
    ARITHR: pipe.immediate      = 'd0; // R-type
    LUI   : pipe.immediate      = {pipe.instruction[31:12], 12'd0}; // U-type
    JAL   : pipe.immediate      = {{12{pipe.instruction[31]}}, pipe.instruction[19:12], pipe.instruction[20], pipe.instruction[30:21], 1'b0}; // J-type
    CUSTOM: pipe.immediate     = (pipe.instruction[`FUNC3] == SLL || pipe.instruction[`FUNC3] == SR) ? {27'h0, pipe.instruction[24:20]} : {{20{pipe.instruction[31]}}, pipe.instruction[31:20]}; // I-type
    CUSTOM_LW2: pipe.immediate = 32'd0; // base em rs1; offsets fixos -32 e -20
    CUSTOM_SW3: pipe.immediate = 32'd0; // operandos fixos x8 e x15; offsets -20 e -24
    CUSTOM2: pipe.immediate     = (pipe.instruction[`FUNC3] == SLL || pipe.instruction[`FUNC3] == SR) ? {27'h0, pipe.instruction[24:20]} : {{20{pipe.instruction[31]}}, pipe.instruction[31:20]}; // I-type

    default: begin // illegal instruction
        pipe.illegal_inst    = 1'b1;
    end
endcase
end

always @(posedge clk or negedge reset) 
begin

// If reset of the system is performed, reset all the values. 

if (!reset) 
begin
    pipe.execute_immediate      <= 32'h0;
    pipe.immediate_sel          <= 1'b0;
    pipe.alu                    <= 1'b0;
    pipe.custom                 <= 1'b0;
    pipe.custom2                <= 1'b0;
    pipe.custom_sw2             <= 1'b0;
    pipe.custom_sw3             <= 1'b0;
    pipe.custom_sw4             <= 1'b0;
    pipe.custom_sw6             <= 1'b0;
    pipe.custom_lw2             <= 1'b0;
    pipe.custom_write_x10       <= 1'b0;
     pipe.custom_write_x2       <= 1'b0;
    pipe.jal                    <= 1'b0;
    pipe.jalr                   <= 1'b0;
    pipe.branch                 <= 1'b0;
    pipe.lui                    <= 1'b0;
    pipe.pc                     <= RESET;
    pipe.src1_select            <= 5'h0;
    pipe.src2_select            <= 5'h0;
    pipe.dest_reg_sel           <= 5'h0;
    pipe.alu_operation          <= 3'h0;
    pipe.arithsubtype           <= 1'b0;
    pipe.mem_write              <= 1'b0;
    pipe.mem_to_reg             <= 1'b0;
end 
else if (!pipe.stall_read ||
         (pipe.instruction == 32'h0010EFF1) ||
         (pipe.instruction == 32'h00f46053) ||
         ((pipe.instruction == 32'h00f47053) || (pipe.instruction == 32'h00f470d3)))
begin
    //  $display("Valor:%b",pipe.instruction[`OPCODE]);    
                     // else take the values from the IF stage and decode it to pass values to corresponding wires
    pipe.execute_immediate      <= pipe.immediate;
    pipe.immediate_sel          <= (pipe.instruction[`OPCODE] == JALR  ) || (pipe.instruction[`OPCODE] == LOAD  ) ||
                                    (pipe.instruction[`OPCODE] == ARITHI) || (pipe.instruction[`OPCODE] == CUSTOM) ;
    pipe.alu                    <= (pipe.instruction[`OPCODE] == ARITHI) ||
                                   (pipe.instruction[`OPCODE] == ARITHR);
    pipe.lui                    <= pipe.instruction[`OPCODE] == LUI;
    pipe.custom                 <= pipe.instruction[`OPCODE] == CUSTOM;
    // 00f45053: MEM[x8-20] = x15 e MEM[x8-24] = 0
    // 00f46053: MEM[x8-64] = x15 e MEM[x8-60] = 0 (duas portas, sem stall)
    // 00f47053: MEM[x8-20] = x15 e MEM[x8-36] = 0 (CUSTOM_SW6)
    pipe.custom_sw2             <= 1'b0;
    pipe.custom_sw3             <= (pipe.instruction == 32'h0010EFF1);
    pipe.custom_sw4             <= (pipe.instruction == 32'h00f46053);
    pipe.custom_sw6             <= (pipe.instruction == 32'h00f470d3);
    // 00f47053: lw x14,-28(x8) + lw x15,-36(x8)
    pipe.custom_lw2             <= (pipe.instruction == 32'h00f47053);
    pipe.custom_lw3 <= (pipe.instruction == 32'h000407db);
    // pipe.custom2                <= pipe.instruction[`OPCODE] == CUSTOM2;
    // Instrução customizada exata que escreve 4 em x10.
    pipe.custom_write_x10       <= (pipe.instruction == 32'h00010553);
    pipe.custom_write_x2        <= (pipe.instruction == 32'h00010573);
    
    pipe.jal                    <= pipe.instruction[`OPCODE] == JAL;
    pipe.jalr                   <= pipe.instruction[`OPCODE] == JALR;
    pipe.branch                 <= pipe.instruction[`OPCODE] == BRANCH;
    pipe.pc                     <= pipe.inst_fetch_pc;
    pipe.src1_select            <=     (pipe.instruction == 32'h000407db) ? 5'd15 : (pipe.instruction == 32'h0010EFF1) ? 5'd8 :  pipe.instruction[`RS1];
    pipe.src2_select            <=      (pipe.instruction == 32'h000407db) ? 5'd8 : (pipe.instruction == 32'h0010EFF1) ? 5'd15 :  pipe.instruction[`RS2];
    pipe.dest_reg_sel           <= pipe.instruction[`RD];
    pipe.alu_operation          <= pipe.instruction[`FUNC3];
    pipe.arithsubtype           <= pipe.instruction[`SUBTYPE] && !(pipe.instruction[`OPCODE] == ARITHI && pipe.instruction[`FUNC3] == ADD);
    pipe.mem_write              <= pipe.instruction[`OPCODE] == STORE;
    pipe.mem_to_reg             <= pipe.instruction[`OPCODE] == LOAD;
    
end

end



// Data forwarding and storing data in respective registers depending on conditions of write stalls, and other conditions 

assign pipe.reg_rdata1 =
    (pipe.src1_select == 5'd0) ? 32'd0 :

    //03010413//Assembly: addi x8, x2, 48
//fff00793//Assembly: addi x15, x0, 4095

//02010413  // addi x8, x2, 32
//00010513  // addi x10, x2, 0
//00050e13  // addi x28, x10, 0
//00400513  // addi x10, x0, 4


    // Forwarding da CUSTOM 00010553:
    // x8=x2+32, x28=x2 e x10=4.
      (pipe.wb_custom_write_x10 && pipe.src1_select == 5'd8) ?
        (pipe.regs[2] + 32'd32) :
         (pipe.wb_custom_write_x10 && pipe.src1_select == 5'd28) ?
        (pipe.regs[2]):
        (pipe.wb_custom_write_x10 && pipe.src1_select == 5'd10) ?
        (4):    



    // Forwarding da CUSTOM 00010573:
    // x17=x10, x6=x10 e x7=0.
    (!pipe.wb_stall && pipe.wb_custom_write_x2 &&
     pipe.src1_select == 5'd17) ? pipe.regs[10] :
    (!pipe.wb_stall && pipe.wb_custom_write_x2 &&
     pipe.src1_select == 5'd6)  ? pipe.regs[10] :
    (!pipe.wb_stall && pipe.wb_custom_write_x2 &&
     pipe.src1_select == 5'd7)  ? 32'd0 :

    // Forwarding normal do estágio WB.
    (!pipe.wb_stall &&
     pipe.wb_alu_to_reg &&
     pipe.wb_dest_reg_sel != 5'd0 &&
     pipe.wb_dest_reg_sel == pipe.src1_select) ?
        (pipe.wb_mem_to_reg ? pipe.wb_read_data : pipe.wb_result) :

    pipe.regs[pipe.src1_select];

assign pipe.reg_rdata2 =
    (pipe.src2_select == 5'd0) ? 32'd0 :

    // Forwarding da CUSTOM 00010553.
        (pipe.wb_custom_write_x10 && pipe.src2_select == 5'd8) ?
        (pipe.regs[2] + 32'd32) :
         (pipe.wb_custom_write_x10 && pipe.src2_select == 5'd28) ?
        (pipe.regs[2]):
        (pipe.wb_custom_write_x10 && pipe.src2_select == 5'd10) ?
        (4):    

    // Forwarding da CUSTOM 00010573.
    (!pipe.wb_stall && pipe.wb_custom_write_x2 &&
     pipe.src2_select == 5'd17) ? pipe.regs[10] :
    (!pipe.wb_stall && pipe.wb_custom_write_x2 &&
     pipe.src2_select == 5'd6)  ? pipe.regs[10] :
    (!pipe.wb_stall && pipe.wb_custom_write_x2 &&
     pipe.src2_select == 5'd7)  ? 32'd0 :

    // Forwarding normal do estágio WB.
    (!pipe.wb_stall &&
     pipe.wb_alu_to_reg &&
     pipe.wb_dest_reg_sel != 5'd0 &&
     pipe.wb_dest_reg_sel == pipe.src2_select) ?
        (pipe.wb_mem_to_reg ? pipe.wb_read_data : pipe.wb_result) :

    pipe.regs[pipe.src2_select];

////////////////////////////////////////////////////////////
// Register file
////////////////////////////////////////////////////////////

integer i;
always @(posedge clk or negedge reset) 
begin
if (!reset) 
begin
    for(i = 1; i < 32; i=i+1) 
    begin
        pipe.regs[i] <= 32'h0;
    end

    
end 
else if (pipe.custom_lw3_writeback_valid)
begin
    if (pipe.custom_lw3_writeback_dest != 5'd0)
        pipe.regs[pipe.custom_lw3_writeback_dest] <= pipe.custom_lw3_writeback_data;
end
else if (pipe.custom_lw2)
begin
    // V30: fusão de:
    //   sw x15,-28(x8) (imediatamente anterior)
    //   lw x14,-28(x8)
    //   lw x15,-36(x8)
    //   and x14,x14,x15
    // reg_rdata2 já contém o x15 mais recente via forwarding normal.
    // Apenas MEM[x8-36] é lida de forma assíncrona.
    pipe.regs[14] <= pipe.reg_rdata2 & pipe.dmem_fast_read_data;
    pipe.regs[15] <= pipe.dmem_fast_read_data;
end
else if (pipe.wb_custom_write_x10 &&
         !pipe.stall_read &&
         !pipe.wb_stall)
begin
    // 03010413  // addi x8, x2, 48
    pipe.regs[8]  <= pipe.regs[2] + 32'd32;
    pipe.regs[28] = pipe.regs[10];
    pipe.regs[10] <= 4;
end
else if (pipe.wb_custom_write_x2 && !pipe.stall_read && !pipe.wb_stall)
begin
    // 00010573 substitui:
//   00050893  addi x17, x10, 0
//   00088313  addi x6,  x17, 0
//   00000393  addi x7,  x0,  0
// Como atribuicoes nao bloqueantes sao simultaneas, x6 recebe diretamente x10.
pipe.regs[17] <= pipe.regs[10];
pipe.regs[6]  <= pipe.regs[10];
pipe.regs[7]  <= 32'd0;
end
else if (pipe.wb_alu_to_reg && !pipe.stall_read && !pipe.wb_stall &&
         (pipe.wb_dest_reg_sel != 5'd0))
begin
    pipe.regs[pipe.wb_dest_reg_sel] <= pipe.wb_mem_to_reg ?
                                       pipe.wb_read_data : pipe.wb_result;
end
end




endmodule
