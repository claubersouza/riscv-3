//////////////// Including Stages ////////////////////////////
`include "IF_ID.v"
`include "execute.v"
`include "wb.v"

 module pipe 
#(
    parameter [31:0]             RESET = 32'h0000_0000
)
(
    input                   clk,
    input                   reset,
    input                   stall,
    output              exception,  

    // interface of instruction Memory
    input                   inst_mem_is_valid,
    input           [31: 0] inst_mem_read_data,
    input           [31: 0] inst_mem_read2_data,
    input           [31: 0] dmem_read_data_temp,
    input           [31: 0] dmem_read2_data_temp,
    input                   dmem_write_valid,
    input                   dmem_read_valid
);
    
    //Declaring Wires and Registers

    //Data Memory Wires
    
    wire          [31: 0] dmem_read_data;
    wire          [31: 0] dmem_read2_data;
    wire                  dmem_write_ready;
    wire                  dmem_read_ready;
    wire          [31: 0] dmem_write_address;
    wire          [31: 0] dmem_read_address;
    wire          [31: 0] dmem_read2_address;
    wire                  dmem_read2_ready;
    wire          [31: 0] dmem_write_data;
    wire          [ 3: 0] dmem_write_byte;
    wire                  dmem_write2_ready;
    wire          [31: 0] dmem_write2_address;
    wire          [31: 0] dmem_write2_data;
    wire          [ 3: 0] dmem_write2_byte;
    wire                  inst_mem_is_ready;
    wire          [31:0] inst_mem_port1_address;
    wire          [31:0] inst_mem_port2_address;
    reg                   custom_lw2_imem_prefetch;
    wire                  dmem_read_valid_checker;
    
    //Instruction Fetch/Decode Stage 
    
    reg           [31: 0] immediate;
    reg                   immediate_sel;
    reg           [ 4: 0] src1_select;
    reg           [ 4: 0] src2_select;
    reg           [ 4: 0] dest_reg_sel;
    reg           [ 2: 0] alu_operation;
    reg                   arithsubtype;
    reg                   mem_write;
    reg                   mem_to_reg;
    reg                   illegal_inst;
    reg           [31: 0] execute_immediate;
    reg                   alu;
    reg                   lui;
    reg                   jal;
    reg                   jalr;
    reg                   branch;
    reg                   custom;
    reg                   custom2;
    reg                   custom_sw2;
    reg                   custom_sw3;
    reg                   custom_sw4;
    reg                   custom_sw6;
    reg                   custom_lw2;
    reg                   custom_lw3;
    reg                   custom_write_x10;
    reg                   custom_write_x2;
    reg                   stall_read;
    wire          [31: 0] instruction;
    wire          [31: 0] reg_rdata2 ; 
    wire          [31: 0] reg_rdata1;
    reg           [31: 0] regs [31: 1];
    reg           [31: 0] teste;
    
    // PC

    reg            [31: 0] pc;
    reg            [31: 0] inst_fetch_pc;
    reg            [31: 0] fetch_pc ;  

    //Stalls
    
    reg     wb_stall_first;
    reg     wb_stall_second;
    wire    wb_stall;        
             
            
    //Execute Stage

    wire            [32: 0] result_subs;       
    wire            [32: 0] result_subu;        
    reg             [31: 0] result;
    reg             [31: 0] next_pc;
    wire            [31: 0] write_address;
    reg                     branch_taken;
    wire                    branch_stall;
    wire            [31:0] alu_operand1;
    wire            [31:0] alu_operand2;

    // Write Back 
    
    reg                    wb_alu_to_reg;
    reg                    wb_custom_write_x10;
    reg                    wb_custom_write_x2;
    reg            [31: 0] wb_custom_x2_value;
    reg                    wb_custom_sw2;
    reg            [31: 0] wb_custom_sw2_base;
    reg            [31: 0] wb_custom_sw2_data;

    // CUSTOM_SW3 rápida: duas portas de escrita na DMEM
    reg                    wb_custom_sw3;
    reg            [31:0]  wb_custom_sw3_base;
    reg            [31:0]  wb_custom_sw3_data;

    // CUSTOM_SW4 00f46053: MEM[x8-64]=x15 e MEM[x8-60]=0
    reg                    wb_custom_sw4;
    reg            [31:0]  wb_custom_sw4_base;
    reg            [31:0]  wb_custom_sw4_data;

    // CUSTOM_SW6: MEM[x8-20]=x15 e MEM[x8-36]=0
    reg                    wb_custom_sw6;
    reg            [31:0]  wb_custom_sw6_base;
    reg            [31:0]  wb_custom_sw6_data;

        reg                    wb_custom_lw3;
    reg            [31:0]  wb_custom_lw3_base;
    reg            [4:0]   wb_custom_lw3_dest;
    reg            [2:0]   custom_lw3_state;
    reg [31:0] custom_lw3_base1_latched;
    reg [31:0] custom_lw3_base2_latched;
    reg            [4:0]   custom_lw3_dest_latched;
    reg            [31:0]  custom_lw3_data1_latched;
    reg            [31:0]  custom_lw3_data2_latched;
    reg                    custom_lw3_seen;
    wire                   custom_lw3_busy;
    wire                   custom_lw3_read_valid;
    wire           [31:0]  custom_lw3_read_address;
    wire                   custom_lw3_writeback_valid;
    wire           [4:0]   custom_lw3_writeback_dest;
    wire           [31:0]  custom_lw3_writeback_data;


    // CUSTOM_LW2: x14=MEM[x8-28], x15=MEM[x8-36]
    reg                    wb_custom_lw2;
    reg            [31:0]  wb_custom_lw2_base;
    reg            [4:0]   wb_custom_lw2_dest;
    reg            [2:0]   custom_lw2_state;
    reg            [31:0]  custom_lw2_base_latched;
    reg            [4:0]   custom_lw2_dest_latched;
    reg            [31:0]  custom_lw2_data1_latched;
    reg            [31:0]  custom_lw2_data2_latched;
    reg                    custom_lw2_seen;
    wire                   custom_lw2_busy;
    wire                   custom_lw2_read_valid;
    wire           [31:0]  custom_lw2_read_address;
    wire           [31:0]  custom_lw2_read2_address;
    wire                   custom_lw2_writeback_valid;
    wire           [31:0]  custom_lw2_writeback_data1;
    wire           [31:0]  custom_lw2_writeback_data2;
    // CUSTOM_LW2B: nova dupla compactada, independente da 00f47053.
    reg                    custom_lw2b;
    reg                    custom_lw2b_seen;
    reg             [1:0] custom_lw2b_state;
    reg            [31:0] custom_lw2b_base_latched;
    wire                   custom_lw2b_busy;
    wire                   custom_lw2b_read_valid;
    wire           [31:0] custom_lw2b_read_address;
    wire           [31:0] custom_lw2b_read2_address;
    wire                   custom_lw2b_writeback_valid;
    wire           [31:0] custom_lw2b_writeback_data1;
    wire           [31:0] custom_lw2b_writeback_data2;

    // Controlador multiciclo genérico para CUSTOM_SW2/SW3/SW4/SW6
    reg            [1:0]  custom_sw_state;
    reg            [31:0] custom_sw_base_latched;
    reg            [31:0] custom_sw_data_latched;
    reg            [31:0] custom_sw_offset2_latched;
    reg                    custom_sw_seen;
    wire                   custom_sw_busy;
    wire                   custom_sw_write_valid;
    wire           [31:0] custom_sw_write_address;
    wire           [31:0] custom_sw_write_data;
    reg            [31: 0] wb_result;
    reg            [ 2: 0] wb_alu_operation;
    reg                    wb_mem_write;
    reg                    wb_mem_to_reg;
    reg            [ 4: 0] wb_dest_reg_sel;
    reg                    wb_branch;
    reg                    wb_branch_nxt;
    reg            [31: 0] wb_write_address;
    reg            [ 1: 0] wb_read_address;
    reg            [ 3: 0] wb_write_byte;
    reg            [31: 0] wb_write_data;
    reg            [31: 0] wb_read_data;
    wire           [31: 0] inst_mem_address;

//------------------------------------------------------//
// Porta 1: a CUSTOM 00f46053 faz a primeira escrita diretamente.
// As demais CUSTOM_SW continuam usando a FSM já existente.
assign dmem_write_address           = wb_custom_sw4 ? (wb_custom_sw4_base - 32'd64) :
                                      custom_sw_write_valid ? custom_sw_write_address :
                                                              wb_write_address;
assign dmem_read_address          = custom_lw3_read_valid ? custom_lw3_read_address : custom_lw2b_read_valid ? custom_lw2b_read_address : custom_lw2_read_valid ? custom_lw2_read_address :
                                                              (alu_operand1 + execute_immediate);
assign dmem_read_ready              = custom_lw3_read_valid || custom_lw2b_read_valid || custom_lw2_read_valid || mem_to_reg;
assign dmem_read2_ready             = custom_lw2b_read_valid || custom_lw2_read_valid;
assign dmem_read2_address           = custom_lw2b_read_valid ? custom_lw2b_read2_address : custom_lw2_read2_address;
assign dmem_write_ready             = wb_custom_sw4 || custom_sw_write_valid || wb_mem_write;
assign dmem_write_data              = wb_custom_sw4 ? wb_custom_sw4_data :
                                      custom_sw_write_valid ? custom_sw_write_data :
                                                              wb_write_data;
assign dmem_write_byte              = wb_custom_sw4 ? 4'b1111 :
                                      custom_sw_write_valid ? 4'b1111 : wb_write_byte;

// Segunda escrita da 00f46053 no mesmo ciclo:
// MEM[x8-60] = 0.
assign dmem_write2_ready            = wb_custom_sw4;
assign dmem_write2_address          = wb_custom_sw4_base - 32'd60;
assign dmem_write2_data             = 32'd0;
assign dmem_write2_byte             = wb_custom_sw4 ? 4'b1111 : 4'b0000;
assign dmem_read_data               = dmem_read_data_temp;      // data read from the memory
assign dmem_read2_data              = dmem_read2_data_temp;
assign dmem_read_valid_checker      = 1'b1;
// -----------------------------------------------------//

// instantiating Instruction fetch module -----------------------
IF_ID IF_ID(
    .clk        (clk),
    .reset     (reset),
    .stall      (stall),
    .exception  (exception),
    .inst_mem_read_data (inst_mem_read_data),
    .inst_mem_read2_data (inst_mem_read2_data),
    .inst_mem_is_valid (inst_mem_is_valid)
);

// instatiating execute module -----------------------------------
execute execute(
    .clk        (clk),
    .reset     (reset)
   );

// instatiating Writeback module ----------------------------------
wb wb(
    .clk        (clk),
    .reset     (reset)
   );
                  
endmodule                     
             