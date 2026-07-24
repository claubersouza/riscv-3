////////////////////////////////////////////////////////////
// stage 3: Write Back
////////////////////////////////////////////////////////////
module wb 
#(
    parameter  [31:0]    RESET   = 32'h0000_0000
)
(
    input clk,
    input reset
);

// import "opcode.vh" for OPCODES
`include "opcode.vh"

// assigning these variables to read from the instruction memory
assign pipe.inst_mem_address            = pipe.fetch_pc; 
assign pipe.inst_mem_is_ready           = !pipe.stall_read;

// wb_stall flag for defining the first and second stall in branch instruction
assign pipe.wb_stall             = pipe.wb_stall_first || pipe.wb_stall_second;

always @(posedge clk or negedge reset) 
begin
    if (!reset) 
    begin
        pipe.inst_fetch_pc               <= RESET; // reset to instruction fetch program counter
    end
    else if (!pipe.stall_read) 
    begin // if stall is not there in branch
        pipe.inst_fetch_pc               <= pipe.fetch_pc;  // fetch the next instruction
    end
end

// Branch stall variable declarations
always @(posedge clk or negedge reset) 
begin
    if (!reset) 
    begin
        pipe.wb_stall_first              <= 1'b0;
        pipe.wb_stall_second             <= 1'b0;
    end 
    else if (!pipe.stall_read && !((pipe.wb_mem_to_reg && !pipe.dmem_write_valid))) 
    begin
        pipe.wb_stall_first              <= pipe.wb_branch;
        pipe.wb_stall_second             <= pipe.wb_stall_first;
    end
end


//Preparing write data for store type instructions

always @(posedge clk or negedge reset) 
begin
    if (!reset) 
    begin
        pipe.wb_write_address         <= 32'h0;
        pipe.wb_write_byte            <= 4'h0;
        pipe.wb_write_data            <= 32'h0;
    end 
    else if (!pipe.stall_read && pipe.mem_write) 
    begin
        pipe.wb_write_address         <= pipe.write_address;
        case(pipe.alu_operation)
            SB: begin
                pipe.wb_write_data    <= {4{pipe.alu_operand2[7:0]}};
                case(pipe.write_address[1:0])
                    2'b00:  pipe.wb_write_byte <= 4'b0001;
                    2'b01:  pipe.wb_write_byte <= 4'b0010;
                    2'b10:  pipe.wb_write_byte <= 4'b0100;
                    default:pipe.wb_write_byte <= 4'b1000;
                endcase
            end
            SH: begin
                pipe.wb_write_data    <= {2{pipe.alu_operand2[15:0]}};
                pipe.wb_write_byte    <= pipe.write_address[1] ? 4'b1100 : 4'b0011;
            end
            SW: begin
                pipe.wb_write_data    <= pipe.alu_operand2;
                pipe.wb_write_byte    <= 4'hf;
            end
            default: begin
                pipe.wb_write_data    <= 32'hx;
                pipe.wb_write_byte    <= 4'hx;
            end
        endcase
    end
end



always @* 
begin
    // load instruction based on the OPCODES
    case(pipe.wb_alu_operation)
        LB  : begin     // Load byte 
                    case(pipe.wb_read_address[1:0]) // a flag to define which byte to read and load
                        2'b00: pipe.wb_read_data[31: 0] = {{24{pipe.dmem_read_data[7]}}, pipe.dmem_read_data[7:0]};
                        2'b01: pipe.wb_read_data[31: 0] = {{24{pipe.dmem_read_data[15]}}, pipe.dmem_read_data[15:8]};
                        2'b10: pipe.wb_read_data[31: 0] = {{24{pipe.dmem_read_data[23]}}, pipe.dmem_read_data[23:16]};
                        2'b11: pipe.wb_read_data[31: 0] = {{24{pipe.dmem_read_data[31]}}, pipe.dmem_read_data[31:24]};
                    endcase
                 end
        // load halfword
        LH  : pipe.wb_read_data = (pipe.wb_read_address[1]) ? {{16{pipe.dmem_read_data[31]}}, pipe.dmem_read_data[31:16]} : {{16{pipe.dmem_read_data[15]}}, pipe.dmem_read_data[15:0]};
        LW  : pipe.wb_read_data = pipe.dmem_read_data;      // load word
        LBU : begin     // load byte unsigned
                    case(pipe.wb_read_address[1:0]) // a flag to define which byte to read and load
                        2'b00: pipe.wb_read_data[31: 0] = {24'h0, pipe.dmem_read_data[7:0]};
                        2'b01: pipe.wb_read_data[31: 0] = {24'h0, pipe.dmem_read_data[15:8]};
                        2'b10: pipe.wb_read_data[31: 0] = {24'h0, pipe.dmem_read_data[23:16]};
                        2'b11: pipe.wb_read_data[31: 0] = {24'h0, pipe.dmem_read_data[31:24]};
                    endcase
                 end
        // load halfword ungigned
        LHU : pipe.wb_read_data = (pipe.wb_read_address[1]) ? {16'h0, pipe.dmem_read_data[31:16]} : {16'h0, pipe.dmem_read_data[15:0]};
        default: pipe.wb_read_data = 'hx;
    endcase
end



// -----------------------------------------------------------------------------
// CUSTOM_SW2 (00f45053)
// Substitui:
//   sw x15, -20(x8)
//   sw x0,  -28(x8)
// A memória possui uma única porta de escrita, portanto são usados dois ciclos.
// -----------------------------------------------------------------------------
localparam [1:0] CUSTOM_SW2_IDLE   = 2'd0;
localparam [1:0] CUSTOM_SW2_WRITE1 = 2'd1;
localparam [1:0] CUSTOM_SW2_WRITE2 = 2'd2;

assign pipe.custom_sw2_busy = (pipe.custom_sw2_state != CUSTOM_SW2_IDLE);
assign pipe.custom_sw2_write_valid =
       (pipe.custom_sw2_state == CUSTOM_SW2_WRITE1) ||
       (pipe.custom_sw2_state == CUSTOM_SW2_WRITE2);

assign pipe.custom_sw2_write_address =
       (pipe.custom_sw2_state == CUSTOM_SW2_WRITE1) ?
       (pipe.custom_sw2_base_latched - 32'd20) :
       (pipe.custom_sw2_base_latched - 32'd28);

assign pipe.custom_sw2_write_data =
       (pipe.custom_sw2_state == CUSTOM_SW2_WRITE1) ?
       pipe.custom_sw2_data_latched : 32'd0;

always @(posedge clk or negedge reset)
begin
    if (!reset)
    begin
        pipe.custom_sw2_state        <= CUSTOM_SW2_IDLE;
        pipe.custom_sw2_base_latched <= 32'd0;
        pipe.custom_sw2_data_latched <= 32'd0;
    end
    else
    begin
        case (pipe.custom_sw2_state)
            CUSTOM_SW2_IDLE:
            begin
                if (pipe.wb_custom_sw2)
                begin
                    pipe.custom_sw2_base_latched <= pipe.wb_custom_sw2_base;
                    pipe.custom_sw2_data_latched <= pipe.wb_custom_sw2_data;
                    pipe.custom_sw2_state        <= CUSTOM_SW2_WRITE1;
                end
            end

            CUSTOM_SW2_WRITE1:
                pipe.custom_sw2_state <= CUSTOM_SW2_WRITE2;

            CUSTOM_SW2_WRITE2:
                pipe.custom_sw2_state <= CUSTOM_SW2_IDLE;

            default:
                pipe.custom_sw2_state <= CUSTOM_SW2_IDLE;
        endcase
    end
end



// -----------------------------------------------------------------------------
// CUSTOM_SW3 rápida (0010EFF1)
// As duas escritas são realizadas simultaneamente pelas duas portas da DMEM.
// Não há FSM nem stall específico para esta instrução.
// -----------------------------------------------------------------------------

// -----------------------------------------------------------------------------
// CUSTOM_LW2 (0004075b)
// Substitui:
//   fe042683  // lw x13, -32(x8)
//   fec42783  // lw x15, -20(x8)
//
// A RAM é síncrona: o dado solicitado em um ciclo somente pode ser capturado
// no ciclo seguinte. Por isso REQ e CAP são estados separados.
// -----------------------------------------------------------------------------
localparam [2:0] CUSTOM_LW2_IDLE   = 3'd0;
localparam [2:0] CUSTOM_LW2_REQ1   = 3'd1;
localparam [2:0] CUSTOM_LW2_CAP1   = 3'd2;
localparam [2:0] CUSTOM_LW2_REQ2   = 3'd3;
localparam [2:0] CUSTOM_LW2_CAP2   = 3'd4;
localparam [2:0] CUSTOM_LW2_WRITE1 = 3'd5;
localparam [2:0] CUSTOM_LW2_WRITE2 = 3'd6;

assign pipe.custom_lw2_busy = (pipe.custom_lw2_state != CUSTOM_LW2_IDLE);

assign pipe.custom_lw2_read_valid =
       (pipe.custom_lw2_state == CUSTOM_LW2_REQ1) ||
       (pipe.custom_lw2_state == CUSTOM_LW2_REQ2);

assign pipe.custom_lw2_read_address =
       (pipe.custom_lw2_state == CUSTOM_LW2_REQ1) ?
       (pipe.custom_lw2_base_latched - 32'd32) :
       (pipe.custom_lw2_base_latched - 32'd20);

assign pipe.custom_lw2_writeback_valid =
       (pipe.custom_lw2_state == CUSTOM_LW2_WRITE1) ||
       (pipe.custom_lw2_state == CUSTOM_LW2_WRITE2);

assign pipe.custom_lw2_writeback_dest =
       (pipe.custom_lw2_state == CUSTOM_LW2_WRITE1) ?
       5'd13 :
       5'd15;

assign pipe.custom_lw2_writeback_data =
       (pipe.custom_lw2_state == CUSTOM_LW2_WRITE1) ?
       pipe.custom_lw2_data1_latched :
       pipe.custom_lw2_data2_latched;

always @(posedge clk or negedge reset)
begin
    if (!reset)
    begin
        pipe.custom_lw2_state         <= CUSTOM_LW2_IDLE;
        pipe.custom_lw2_base_latched  <= 32'd0;
        pipe.custom_lw2_dest_latched  <= 5'd0;
        pipe.custom_lw2_data1_latched <= 32'd0;
        pipe.custom_lw2_data2_latched <= 32'd0;
        pipe.custom_lw2_seen          <= 1'b0;
    end
    else
    begin
        case (pipe.custom_lw2_state)
            CUSTOM_LW2_IDLE:
            begin
                if (pipe.custom_lw2 && !pipe.custom_lw2_seen)
                begin
                    // reg_rdata1 já contém x8 com o forwarding normal aplicado.
                    pipe.custom_lw2_base_latched <= pipe.reg_rdata1;
                    pipe.custom_lw2_dest_latched <= 5'd13; // primeiro destino fixo: x13
                    pipe.custom_lw2_seen          <= 1'b1;
                    pipe.custom_lw2_state         <= CUSTOM_LW2_REQ1;
                end
                else if (!pipe.custom_lw2)
                begin
                    pipe.custom_lw2_seen <= 1'b0;
                end
            end

            // A RAM recebe base-32 neste ciclo.
            CUSTOM_LW2_REQ1:
                pipe.custom_lw2_state <= CUSTOM_LW2_CAP1;

            // read_data agora corresponde a MEM[base-32].
            CUSTOM_LW2_CAP1:
            begin
                pipe.custom_lw2_data1_latched <= pipe.dmem_read_data;
                pipe.custom_lw2_state         <= CUSTOM_LW2_REQ2;
            end

            // A RAM recebe base-20 neste ciclo.
            CUSTOM_LW2_REQ2:
                pipe.custom_lw2_state <= CUSTOM_LW2_CAP2;

            // read_data agora corresponde a MEM[base-20].
            CUSTOM_LW2_CAP2:
            begin
                pipe.custom_lw2_data2_latched <= pipe.dmem_read_data;
                pipe.custom_lw2_state         <= CUSTOM_LW2_WRITE1;
            end

            CUSTOM_LW2_WRITE1:
                pipe.custom_lw2_state <= CUSTOM_LW2_WRITE2;

            CUSTOM_LW2_WRITE2:
                pipe.custom_lw2_state <= CUSTOM_LW2_IDLE;

            default:
                pipe.custom_lw2_state <= CUSTOM_LW2_IDLE;
        endcase
    end
end





// -----------------------------------------------------------------------------
// CUSTOM_lw3 (0004075b)
// Substitui:
//   fe042683  // lw x13, -32(x8)
//   fec42783  // lw x15, -20(x8)

// 0007a703  // lw x14, 0(x15)
// fec42783  // lw x15, -20(x8)
//
// A RAM é síncrona: o dado solicitado em um ciclo somente pode ser capturado
// no ciclo seguinte. Por isso REQ e CAP são estados separados.
// -----------------------------------------------------------------------------
localparam [2:0] CUSTOM_LW3_IDLE   = 3'd0;
localparam [2:0] CUSTOM_lw3_REQ1   = 3'd1;
localparam [2:0] CUSTOM_LW3_CAP1   = 3'd2;
localparam [2:0] CUSTOM_LW3_REQ2   = 3'd3;
localparam [2:0] CUSTOM_LW3_CAP2   = 3'd4;
localparam [2:0] CUSTOM_LW3_WRITE1 = 3'd5;
localparam [2:0] CUSTOM_LW3_WRITE2 = 3'd6;

assign pipe.custom_lw3_busy = (pipe.custom_lw3_state != CUSTOM_LW3_IDLE);

assign pipe.custom_lw3_read_valid =
       (pipe.custom_lw3_state == CUSTOM_lw3_REQ1) ||
       (pipe.custom_lw3_state == CUSTOM_LW3_REQ2);

assign pipe.custom_lw3_read_address =
    (pipe.custom_lw3_state == CUSTOM_lw3_REQ1)
        ? pipe.custom_lw3_base1_latched
        : pipe.custom_lw3_base2_latched - 32'd20;

assign pipe.custom_lw3_writeback_valid =
       (pipe.custom_lw3_state == CUSTOM_LW3_WRITE1) ||
       (pipe.custom_lw3_state == CUSTOM_LW3_WRITE2);

assign pipe.custom_lw3_writeback_dest =
       (pipe.custom_lw3_state == CUSTOM_LW3_WRITE1) ?
       5'd14 :
       5'd15;

assign pipe.custom_lw3_writeback_data =
       (pipe.custom_lw3_state == CUSTOM_LW3_WRITE1) ?
       pipe.custom_lw3_data1_latched :
       pipe.custom_lw3_data2_latched;

always @(posedge clk or negedge reset)
begin
    if (!reset)
    begin
        pipe.custom_lw3_state         <= CUSTOM_LW3_IDLE;
       pipe.custom_lw3_base1_latched <= 32'd0;
pipe.custom_lw3_base2_latched <= 32'd0;
        pipe.custom_lw3_dest_latched  <= 5'd0;
        pipe.custom_lw3_data1_latched <= 32'd0;
        pipe.custom_lw3_data2_latched <= 32'd0;
        pipe.custom_lw3_seen          <= 1'b0;
    end
    else
    begin
        case (pipe.custom_lw3_state)
            CUSTOM_LW3_IDLE:
            begin
                if (pipe.custom_lw3 && !pipe.custom_lw3_seen)
                begin
                    // reg_rdata1 já contém x8 com o forwarding normal aplicado.
                    pipe.custom_lw3_base1_latched <= pipe.reg_rdata1; // x15
                    pipe.custom_lw3_base2_latched <= pipe.reg_rdata2; // x8
                    pipe.custom_lw3_dest_latched <= 5'd14; // primeiro destino fixo: x14
                    pipe.custom_lw3_seen          <= 1'b1;
                    pipe.custom_lw3_state         <= CUSTOM_lw3_REQ1;
                end
                else if (!pipe.custom_lw3)
                begin
                    pipe.custom_lw3_seen <= 1'b0;
                end
            end

            // A RAM recebe base-32 neste ciclo.
            CUSTOM_lw3_REQ1:
                pipe.custom_lw3_state <= CUSTOM_LW3_CAP1;

            // read_data agora corresponde a MEM[base-32].
            CUSTOM_LW3_CAP1:
            begin
                pipe.custom_lw3_data1_latched <= pipe.dmem_read_data;
                pipe.custom_lw3_state         <= CUSTOM_LW3_REQ2;
            end

            // A RAM recebe base-20 neste ciclo.
            CUSTOM_LW3_REQ2:
                pipe.custom_lw3_state <= CUSTOM_LW3_CAP2;

            // read_data agora corresponde a MEM[base-20].
            CUSTOM_LW3_CAP2:
            begin
                pipe.custom_lw3_data2_latched <= pipe.dmem_read_data;
                pipe.custom_lw3_state         <= CUSTOM_LW3_WRITE1;
            end

            CUSTOM_LW3_WRITE1:
                pipe.custom_lw3_state <= CUSTOM_LW3_WRITE2;

            CUSTOM_LW3_WRITE2:
                pipe.custom_lw3_state <= CUSTOM_LW3_IDLE;

            default:
                pipe.custom_lw3_state <= CUSTOM_LW3_IDLE;
        endcase
    end
end

endmodule
