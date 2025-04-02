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
    input           [31: 0] inst_mem_read_data,
    input                   [31: 0] inst_data_future,
    output  reg  ok_read
    );

//////////////// Including OPCODES ////////////////////////////
`include "opcode.vh"

function [31:0]  set_operand;
    input [31:0] data;
begin
    $display("Na função: ",counter );  
    if (counter  == 'd24) begin
        $display("Na função: ",counter );  
        set_operand =  32'hfef42223;
    end
    else begin
        set_operand = data;
    end
end
endfunction

////////////////////////////////////////////////////////////////
// IF stage Start
////////////////////////////////////////////////////////////////
// assign pipe.instruction  = pipe.stall_read? NOP:inst_mem_read_data; //aqui recebe a instrução
assign pipe.instruction_future = inst_data_future;

integer counter;
integer counter2;
integer flag_decode;
integer flag;
integer aux;
integer flag_aux;
// reg teste4 [31:0];

// check for illegal instruction(instruction not in RV-32I architecture)

always @(posedge clk or negedge reset) 
begin
    if (!reset)
        exception           <= 1'b0;
        
    else if (pipe.illegal_inst || pipe.inst_mem_address[1:0] != 0)
        exception           <= 1'b1;
end




// Stall read assignment for stalling while reading 

always @(posedge clk or negedge reset) 
begin
    if (!reset) 
    begin
        pipe.stall_read             <= 1'b1;
    end else 
    begin
        pipe.stall_read             <= stall;
       
        //  teste4[0] = inst_data_future;
    end
end




always @(*) 
begin
    // if (counter2 == 12)begin
    //     pipe.save_instruction[12] = 32'h00f71663;
    // end
  
    // aux = counter2 ;
    if (pipe.save_instruction[counter2] == 32'h0780078F) begin
        pipe.save_instruction[14] = 32'h00f71663;
        pipe.save_instruction[16] = 32'h07800793;
        for (i = 0; i < 25; i = i + 1) begin
            $display("my_array[%0d] = %h", i, pipe.save_instruction[i]);
          end
        pipe.save_instruction[counter2] = 32'h00f71663;
        // pipe.save_instruction[counter2] = 32'h07800793;
        flag = 1;

  
    end

    // if (pipe.save_instruction[counter2] == 32'h00f71663) begin
    //     pipe.instruction = 32'h07800793;
    //     flag = 1;
    // end
end

always @(posedge clk ) 
begin
    if ( ok_read == 0) begin
        counter2 = counter2 + 1;
    end
end


always @(posedge clk ) 
begin
    if (counter >= 27) begin
        // if (pipe.save_instruction[counter2] == 32'h00f71663) begin
        //     pipe.instruction <= 32'h00f71663;
        //     aux <= counter2;
        // end
        // else if (pipe.instruction  == 32'h00f71663) begin
        //     pipe.instruction <= 32'h07800793;
        // end
        // else begin

        // pipe.save_instruction[14] <= 32'h00f71663;
        // pipe.save_instruction[16] <= 32'h07800793;

        // if (pipe.save_instruction[counter2] == 32'hfe442783) begin
        //     pipe.save_instruction[15] = 32'h07800793;
        //     aux <= counter2;
        // end

           pipe.instruction <= pipe.save_instruction[counter2];

        // end
        // $display("valor counter2: ",counter2 -);   
    end
end

////////////////////////////////////////////////////////////////
// IF stage end
////////////////////////////////////////////////////////////////

////////////////////////////////////////////////////////////////
// ID stage 
////////////////////////////////////////////////////////////////


//Aqui é onde vai fica as instruções que vao chegar
// Armazeno num aray para mannupular depois
always @*
begin
        // $display("Valor Array:%h",inst_data_future );   
    // pipe.instruction = //set_operand(inst_mem_read_data);
    // inst_mem_read_data;
   

    if ( counter == 27) begin
        
        pipe.instruction = 32'hfef42223; 
    end
    else  begin
        pipe.instruction = inst_mem_read_data;
    end
  

    // else if begin

    // end
    // pipe.instruction = 32'hfef42223;
         
end

always @(pipe.instruction)
begin
    
    // if ( counter == 25) begin
    //     pipe.instruction = 32'hfef42223; 
    // end
end

initial begin
    counter            <= 1;
    counter2  <= 1;
    ok_read <= 1  ;
    flag =  0 ; 
    aux = 0 ;
    flag_aux = 0 ;
end



always @(inst_mem_read_data) 
begin

    // $display("Valor Array:%h", pipe.save_instruction[20]);
 
    // $display("Clauber2:",counter);

    if ( counter == 26) begin
        ok_read <= 0  ;  
    end
    
    if (counter < 60) begin
        counter <= counter + 1;    
    end
    else begin
        counter = 0;
    end


    //k_read <= 1  ;  

end

always @(inst_data_future) 
begin
    pipe.save_instruction[counter] <= inst_data_future;
    // if ( counter == 22) begin
    //     ok_read <= 0  ;  
    // end
    counter <= counter + 1;
    // $display("Clauber:",counter);
    
end

always @* 
begin
    // $display("Valor Array:%h",inst_data_future);
    // pipe.save_instruction[counter] = inst_data_future;
    // $display("Valor Array:%h",pipe.save_instruction[counter]);
 
        
    
    pipe.immediate                     = 32'h0;
    pipe.illegal_inst                  = 1'b0;
    case(pipe.instruction[`OPCODE])
        JALR  : pipe.immediate      = {{20{pipe.instruction[31]}}, pipe.instruction[31:20]}; // I-Type 
        BRANCH: pipe.immediate      = {{20{pipe.instruction[31]}}, pipe.instruction[7], pipe.instruction[30:25], pipe.instruction[11:8], 1'b0}; // B-type
        LOAD  : pipe.immediate      = {{20{pipe.instruction[31]}}, pipe.instruction[31:20]}; // I-type
        STORE : pipe.immediate      = {{20{pipe.instruction[31]}}, pipe.instruction[31:25], pipe.instruction[11:7]}; // S-type
        ARITHI: pipe.immediate      = (pipe.instruction[`FUNC3] == SLL || pipe.instruction[`FUNC3] == SR) ? {27'h0, pipe.instruction[24:20]} : {{20{pipe.instruction[31]}}, pipe.instruction[31:20]}; // I-type
        ARITHR: pipe.immediate      = 'd0; // R-type
        LUI   : pipe.immediate      = {pipe.instruction[31:12], 12'd0}; // U-type
        JAL   : pipe.immediate      = {{12{pipe.instruction[31]}}, pipe.instruction[19:12], pipe.instruction[20], pipe.instruction[30:21], 1'b0}; // J-type

        CUSTOM: pipe.immediate      =   (pipe.instruction[`FUNC3] == SLL || pipe.instruction[`FUNC3] == SR) ? {27'h0, pipe.instruction[24:20]} : {{20{pipe.instruction[31]}}, pipe.instruction[31:20]}; // I-type

        CUSTOM_BRANCH: pipe.immediate = {{20{pipe.instruction[31]}}, pipe.instruction[7], pipe.instruction[30:25], pipe.instruction[11:8], 1'b0}; // B-type

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
        pipe.jal                    <= 1'b0;
        pipe.jalr                   <= 1'b0;
        pipe.branch                 <= 1'b0;
        pipe.custom                 <= 1'b0;
        pipe.branch_custom          <= 1'b0;
        pipe.pc                     <= RESET;
        pipe.src1_select            <= 5'h0;
        pipe.src2_select            <= 5'h0;
        pipe.dest_reg_sel           <= 5'h0;
        pipe.alu_operation          <= 3'h0;
        pipe.arithsubtype           <= 1'b0;
        pipe.mem_write              <= 1'b0;
        pipe.mem_to_reg             <= 1'b0;
    end 
    else if(!pipe.stall_read) 
    begin                      // else take the values from the IF stage and decode it to pass values to corresponding wires
        pipe.execute_immediate      <= pipe.immediate;
        
        // Esse habilita a instructions imediato
        pipe.immediate_sel          <= (pipe.instruction[`OPCODE] == JALR  ) || (pipe.instruction[`OPCODE] == LOAD  ) ||
                                        (pipe.instruction[`OPCODE] == ARITHI) ||  (pipe.instruction[`OPCODE] == CUSTOM) ;
       
       
       pipe.alu                    <= (pipe.instruction[`OPCODE] == ARITHI) || (pipe.instruction[`OPCODE] == ARITHR) || (pipe.instruction[`OPCODE] == CUSTOM);
        pipe.custom                 <= pipe.instruction[`OPCODE] == CUSTOM;
        pipe.lui                    <= pipe.instruction[`OPCODE] == LUI;
        pipe.jal                    <= pipe.instruction[`OPCODE] == JAL;
        pipe.jalr                   <= pipe.instruction[`OPCODE] == JALR;
        pipe.branch                 <= pipe.instruction[`OPCODE] == BRANCH;
        pipe.branch_custom          <= pipe.instruction[`OPCODE] == CUSTOM_BRANCH;
        pipe.pc                     <= pipe.inst_fetch_pc;
        pipe.src1_select            <= pipe.instruction[`RS1];
        pipe.src2_select            <= pipe.instruction[`RS2];
        pipe.dest_reg_sel           <= pipe.instruction[`RD];
        pipe.alu_operation          <= pipe.instruction[`FUNC3];
        pipe.arithsubtype           <= pipe.instruction[`SUBTYPE] && !(pipe.instruction[`OPCODE] == ARITHI && pipe.instruction[`FUNC3] == ADD);
        pipe.mem_write              <= pipe.instruction[`OPCODE] == STORE;
        pipe.mem_to_reg             <= pipe.instruction[`OPCODE] == LOAD;
        
    end
    
end



// Data forwarding and storing data in respective registers depending on conditions of write stalls, and other conditions 

assign pipe.reg_rdata1[31: 0] = (pipe.src1_select == 5'h0) ? 32'h0 :
                        (!pipe.wb_stall && pipe.wb_alu_to_reg && (pipe.wb_dest_reg_sel == pipe.src1_select)) ? (pipe.wb_mem_to_reg ? pipe.wb_read_data : pipe.wb_result) :
                        pipe.regs[pipe.src1_select];
assign pipe.reg_rdata2[31: 0] = (pipe.src2_select == 5'h0) ? 32'h0 :
                        (!pipe.wb_stall && pipe.wb_alu_to_reg && (pipe.wb_dest_reg_sel == pipe.src2_select)) ? (pipe.wb_mem_to_reg ? pipe.wb_read_data : pipe.wb_result) :
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
    else if (pipe.wb_alu_to_reg && !pipe.stall_read && !(pipe.wb_stall)) 
    begin
        pipe.regs[pipe.wb_dest_reg_sel]    <= pipe.wb_mem_to_reg ? pipe.wb_read_data : pipe.wb_result;
    end
end




endmodule
