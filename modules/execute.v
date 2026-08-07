////////////////////////////////////////////////////////////
// Stage 2: Execute
////////////////////////////////////////////////////////////

module execute 
    #(
        parameter  [31:0]    RESET   = 32'h0000_0000
    ) 
    (   input clk,
        input reset
    );
//////////////// Including OPCODES ////////////////////////////

`include "opcode.vh"
    
// Selecting the first and second operands of ALU unit

assign pipe.alu_operand1         = pipe.reg_rdata1;                     //First operand gets data from register file
assign pipe.alu_operand2         = (pipe.immediate_sel) ? pipe.execute_immediate : pipe.reg_rdata2;     //Second operand gats data either from immediate or register file
assign pipe.result_subs[32: 0]   = {pipe.alu_operand1[31], pipe.alu_operand1} - {pipe.alu_operand2[31], pipe.alu_operand2};     //Substraction Signed
assign pipe.result_subu[32: 0]   = {1'b0, pipe.alu_operand1} - {1'b0, pipe.alu_operand2};           //Substraction Unsigned
assign pipe.write_address        = pipe.alu_operand1 + pipe.execute_immediate;          //Calculating write address for data memory
assign pipe.branch_stall         = pipe.wb_branch_nxt || pipe.wb_branch;                //Calculating branch stall value


//Calculating next PC value

always @(*) 
begin
    // $display("Valor:%h",pipe.instruction[`OPCODE]); 
    pipe.next_pc      = pipe.fetch_pc + 4;
    pipe.branch_taken = !pipe.branch_stall;
        case(1'b1)
        pipe.jal   : pipe.next_pc = pipe.pc + pipe.execute_immediate;
        pipe.jalr  : pipe.next_pc = pipe.alu_operand1 + pipe.execute_immediate;
        // pipe.branch_custom: begin
            // case(pipe.alu_operation) 
            // BNE_CUSTOM: begin
            //     // pipe.teste = 1'b1;
            //     pipe.next_pc = !pipe.result_subs[32] ? pipe.pc + pipe.execute_immediate : pipe.fetch_pc + 4;
            //     if (pipe.result_subs[32]) 
            //         pipe.branch_taken = 1'b0;
            // end 
            // default: begin
            //     pipe.next_pc    = pipe.fetch_pc;
            //     end
            // endcase
        // end 
        pipe.branch: begin
            case(pipe.alu_operation) 
                BEQ : begin
                            pipe.next_pc = (pipe.result_subs[32: 0] == 'd0) ? pipe.pc + pipe.execute_immediate : pipe.fetch_pc + 4;
                            if (pipe.result_subs[32: 0] != 'd0) 
                                pipe.branch_taken = 1'b0;
                         end
                BNE : begin
                            pipe.next_pc = (pipe.result_subs[32: 0] != 'd0) ? pipe.pc + pipe.execute_immediate : pipe.fetch_pc + 4;
                            if (pipe.result_subs[32: 0] == 'd0) 
                                pipe.branch_taken = 1'b0;
                         end
                BLT : begin
                            pipe.next_pc = pipe.result_subs[32] ? pipe.pc + pipe.execute_immediate : pipe.fetch_pc + 4;
                            if (!pipe.result_subs[32]) 
                                pipe.branch_taken = 1'b0;
                         end
                BGE : begin
                            pipe.next_pc = !pipe.result_subs[32] ? pipe.pc + pipe.execute_immediate : pipe.fetch_pc + 4;
                            if (pipe.result_subs[32]) 
                                pipe.branch_taken = 1'b0;
                         end
                BLTU: begin
                            pipe.next_pc = pipe.result_subu[32] ? pipe.pc + pipe.execute_immediate : pipe.fetch_pc + 4;
                            if (!pipe.result_subu[32]) 
                                pipe.branch_taken = 1'b0;
                         end
                BGEU: begin
                            pipe.next_pc = !pipe.result_subu[32] ? pipe.pc + pipe.execute_immediate : pipe.fetch_pc + 4;
                            if (pipe.result_subu[32]) 
                                pipe.branch_taken = 1'b0;
                         end
                default: begin
                         pipe.next_pc    = pipe.fetch_pc;
                         end
            endcase
        end
        default  : begin
                   pipe.next_pc          = pipe.fetch_pc + 4;
                   pipe.branch_taken     = 1'b0;
                   end
    endcase
end

//Calculating ALU result depending on the opcode

always @(*) 

begin
   
     case(1'b1)
        pipe.mem_write:   pipe.result          = pipe.alu_operand2;
        pipe.jal:         pipe.result          = pipe.pc + 4;
        pipe.jalr:        pipe.result          = pipe.pc + 4;
        pipe.lui:         pipe.result          = pipe.execute_immediate;
        pipe.custom: begin
            // A escrita em x10 ocorre exclusivamente no estágio de write-back.
            pipe.result = 32'd0;
        end
        pipe.custom2: begin
            // Mantido sem escrita direta no banco de registradores.
            pipe.result = 32'd0;
        end
  
            // case (pipe.alu_operation)
            // executar exatamente o que faria o ADDI
            // CUSTOM : begin 
                // pipe.regs[17] <=  pipe.regs[6] << 27;
                // pipe.regs[14] <= (pipe.regs[10] + ((pipe.regs[7] >> 5) | pipe.regs[17]) + pipe.regs[10]) >> 27;
                // pipe.regs[13] <= pipe.regs[6] << 5 ;
                // pipe.regs[16] <= (pipe.regs[12] << 5) | pipe.regs[14] ;
                // pipe.regs[11] <= pipe.regs[14] + 0 ;
                // pipe.regs[12] <= pipe.regs[0]  + 0 ;
                // pipe.regs[15] <= (((pipe.regs[11] << 5)  +  pipe.regs[10]) << 2)  ;
     
                // pipe.regs[10] <= pipe.regs[2] + 0;
        //     end
        // endcase
        default: pipe.result = 'hx;     
        pipe.alu:
      
            case(pipe.alu_operation)
                ADD : if (pipe.arithsubtype == 1'b0)
                            pipe.result  = pipe.alu_operand1 + pipe.alu_operand2;
                         else
                            pipe.result  = pipe.alu_operand1 - pipe.alu_operand2;
                SLL : pipe.result     = pipe.alu_operand1 << pipe.alu_operand2;
                SLT : pipe.result     = pipe.result_subs[32] ? 'd1 : 'd0;
                SLTU: pipe.result     = pipe.result_subu[32] ? 'd1 : 'd0;
                XOR : pipe.result     = pipe.alu_operand1 ^ pipe.alu_operand2;

                SR  : if (pipe.arithsubtype == 1'b0)
                            pipe.result  = pipe.alu_operand1 >>> pipe.alu_operand2;
                         else
                            pipe.result  = $signed(pipe.alu_operand1) >>> pipe.alu_operand2;
                OR  : pipe.result     = pipe.alu_operand1 | pipe.alu_operand2;
                AND : pipe.result     = pipe.alu_operand1 & pipe.alu_operand2;
          
                //CUSTOM : pipe.result =  pipe.alu_operand2 * 2  ;
                default: pipe.result     = 'hx;
            endcase
           
        default: pipe.result = 'hx;
    endcase
end

always @(posedge clk or negedge reset) 
begin
    if (!reset) 
    begin
        
        pipe.fetch_pc <= RESET;
    end 
    else if (!pipe.stall_read) 
    begin
    // A CUSTOM_LW2 substitui fe042683 e fec42783 por uma unica instrucao. A segunda palavra
    // continua reservada na IMEM para preservar todos os enderecos de JAL e
    // BRANCH, mas o PC avanca 8 bytes quando a FSM termina. Assim, nao e
    // necessario usar 00000013 como preenchimento e a palavra reservada nao
    // chega ao decode.
        // A 00f45053 é reconhecida diretamente na saída da IMEM.
        // O próximo fetch salta a segunda SW substituída sem stall e sem bolha.
        if (pipe.instruction == 32'h0010EFF1)
            pipe.fetch_pc <= pipe.fetch_pc + 32'd8;
        else if (((pipe.instruction == 32'h00f46053) &&
                  (pipe.reg_rdata2 == 32'd32)) ||
                 (pipe.instruction == 32'h0010EFF1))
            pipe.fetch_pc <= pipe.fetch_pc + 32'd8;
        else if ((pipe.instruction == 32'h000407db) && !pipe.custom_lw3_busy)
            pipe.fetch_pc <= pipe.fetch_pc + 32'd8;
        else
            pipe.fetch_pc <= (pipe.branch_stall) ? pipe.fetch_pc + 4 : pipe.next_pc;
    end
end

//Preparing output for writeback stage

always @(posedge clk or negedge reset) 
begin
    if (!reset) 
    begin
        pipe.wb_result               <= 32'h0;
        pipe.wb_mem_write            <= 1'b0;
        pipe.wb_alu_to_reg           <= 1'b0;
        pipe.wb_custom_write_x10      <= 1'b0;
        pipe.wb_custom_write_x2      <= 1'b0;
        pipe.wb_custom_x2_value      <= 32'd0;
        pipe.wb_custom_sw2            <= 1'b0;
        pipe.wb_custom_sw2_base       <= 32'd0;
        pipe.wb_custom_sw2_data       <= 32'd0;
        pipe.wb_custom_sw3            <= 1'b0;
        pipe.wb_custom_sw3_base       <= 32'd0;
        pipe.wb_custom_sw3_data       <= 32'd0;
        pipe.wb_custom_sw4            <= 1'b0;
        pipe.wb_custom_sw4_base       <= 32'd0;
        pipe.wb_custom_sw4_data       <= 32'd0;
        pipe.wb_custom_sw6            <= 1'b0;
        pipe.wb_custom_sw6_base       <= 32'd0;
        pipe.wb_custom_sw6_data       <= 32'd0;
        pipe.wb_custom_lw2             <= 1'b0;
        pipe.wb_custom_lw2_base        <= 32'd0;
        pipe.wb_custom_lw2_dest        <= 5'd0;
        pipe.wb_custom_lw3             <= 1'b0;
        pipe.wb_custom_lw3_base        <= 32'd0;
        pipe.wb_custom_lw3_dest        <= 5'd0;
        pipe.wb_dest_reg_sel         <= 5'h0;
        pipe.wb_branch               <= 1'b0;
        pipe.wb_branch_nxt           <= 1'b0;
        pipe.wb_mem_to_reg           <= 1'b0;
        pipe.wb_read_address         <= 2'h0;
        pipe.wb_alu_operation        <= 3'h0;
    end 
    // A FSM genérica trava o fetch/decode assim que reconhece SW3/SW4/SW6.
    // Mesmo durante esse stall inicial, a operação customizada precisa avançar
    // uma vez para os registradores wb_custom_sw*. Por isso existe a exceção.
    else if (!pipe.stall_read || pipe.custom_sw2 || pipe.custom_sw3 ||
             pipe.custom_sw4 || pipe.custom_sw6)
    begin
        pipe.wb_result               <= pipe.result;
        pipe.wb_mem_write            <= pipe.mem_write && !pipe.branch_stall;
        pipe.wb_alu_to_reg           <= pipe.alu | pipe.lui | pipe.jal |
                                        pipe.jalr | pipe.mem_to_reg;
        pipe.wb_custom_write_x10      <= pipe.custom_write_x10;
        pipe.wb_custom_write_x2       <= pipe.custom_write_x2;
        pipe.wb_custom_x2_value       <= pipe.reg_rdata1;
        // Os operandos já incluem o forwarding normal do pipeline.
        pipe.wb_custom_sw2            <= pipe.custom_sw2;
        pipe.wb_custom_sw2_base       <= pipe.reg_rdata1;
        pipe.wb_custom_sw2_data       <= pipe.reg_rdata2;
        pipe.wb_custom_sw3            <= pipe.custom_sw3;
        pipe.wb_custom_sw3_base       <= pipe.reg_rdata1;
        pipe.wb_custom_sw3_data       <= pipe.reg_rdata2;
        // 00f46053 só é válida após o ADDI que prepara x15=32.
        // Durante o caminho especulativo do BGEU, x15 vale 13; nesse caso,
        // a custom é anulada e não produz escrita nem salto de PC.
        pipe.wb_custom_sw4            <= pipe.custom_sw4 &&
                                         (pipe.reg_rdata2 == 32'd32);
        pipe.wb_custom_sw4_base       <= pipe.reg_rdata1;
        pipe.wb_custom_sw4_data       <= pipe.reg_rdata2;
        pipe.wb_custom_sw6            <= pipe.custom_sw6;
        pipe.wb_custom_sw6_base       <= pipe.reg_rdata1;
        pipe.wb_custom_sw6_data       <= pipe.reg_rdata2;
        pipe.wb_custom_lw2             <= pipe.custom_lw2;
        pipe.wb_custom_lw2_base        <= pipe.reg_rdata1;
        pipe.wb_custom_lw2_dest        <= pipe.dest_reg_sel;
        pipe.wb_custom_lw3             <= pipe.custom_lw3;
        pipe.wb_custom_lw3_base        <= pipe.reg_rdata1;
        pipe.wb_custom_lw3_dest        <= pipe.dest_reg_sel;
        pipe.wb_dest_reg_sel         <= pipe.dest_reg_sel;
        pipe.wb_branch               <= pipe.branch_taken;
        pipe.wb_branch_nxt           <= pipe.wb_branch;
        pipe.wb_mem_to_reg           <= pipe.mem_to_reg;
        pipe.wb_read_address         <= pipe.dmem_read_address[1:0];
        pipe.wb_alu_operation        <= pipe.alu_operation;
    end
end

endmodule