module memory # (
    // Loading the hex file generated from the cross-compiler
    parameter FILE  = "../memory_data/imem.hex",
    //  Defining the maximum size of the memory files
    parameter SIZE  = 4096
    
) (
    input               clk,
    input               read_ready,
    input               write_ready,
    input       [31: 2] write_address,
    input       [31: 0] write_data,
    input       [ 3: 0] write_byte,
    input               write2_ready,
    input       [31: 2] write2_address,
    input       [31: 0] write2_data,
    input       [ 3: 0] write2_byte,
    output reg  [31: 0] read_data,
    input       [31: 2] read_address
    
);

    localparam ADDR = $clog2(SIZE/4);
    wire        [ADDR-1: 0] read_addr;
    wire        [ADDR-1: 0] write_addr;
    wire        [ADDR-1: 0] write2_addr;
    reg         [31: 0] memory [(SIZE/4)-1: 0];
    integer                 i;
    integer counter  ;
    reg [31:0] teste1, teste2, teste3;

assign read_addr[ADDR-1: 0] = read_address[ADDR+1: 2];
assign write_addr[ADDR-1: 0] = write_address[ADDR+1: 2];
assign write2_addr[ADDR-1: 0] = write2_address[ADDR+1: 2];

// task custom;
//     begin
//         if (memory[counter] == 32'h0780078F) begin
//             teste1 = memory[counter];
//             teste2 = memory[counter + 1];
//             teste3 = memory[counter + 2];


//         end
//     end
// endtask



initial begin
    read_data = 32'd0;
    for (i = 0; i < SIZE/4; i = i + 1)
        memory[i] = 32'h00000013; // NOP por padrão
    $display("Carregando memoria: %s", FILE);
    $readmemh(FILE, memory, 0, SIZE/4-1);
end

always @(posedge clk) begin
    if (write_ready) begin
        if (write_byte[0]) memory[write_addr][8*0+7:8*0] <= write_data[8*0+7:8*0];
        if (write_byte[1]) memory[write_addr][8*1+7:8*1] <= write_data[8*1+7:8*1];
        if (write_byte[2]) memory[write_addr][8*2+7:8*2] <= write_data[8*2+7:8*2];
        if (write_byte[3]) memory[write_addr][8*3+7:8*3] <= write_data[8*3+7:8*3];
    end

    // Segunda porta de escrita. É usada pela CUSTOM_SW3 para efetuar
    // MEM[x8-24] = 0 no mesmo ciclo de MEM[x8-20] = x15.
    if (write2_ready) begin
        if (write2_byte[0]) memory[write2_addr][8*0+7:8*0] <= write2_data[8*0+7:8*0];
        if (write2_byte[1]) memory[write2_addr][8*1+7:8*1] <= write2_data[8*1+7:8*1];
        if (write2_byte[2]) memory[write2_addr][8*2+7:8*2] <= write2_data[8*2+7:8*2];
        if (write2_byte[3]) memory[write2_addr][8*3+7:8*3] <= write2_data[8*3+7:8*3];
    end

    if (read_ready) begin
        if (write_ready && read_addr == write_addr) begin
            read_data[8*0+7:8*0] <= (write_byte[0]) ? write_data[8*0+7:8*0] : memory[read_addr][8*0+7:8*0];
            read_data[8*1+7:8*1] <= (write_byte[1]) ? write_data[8*1+7:8*1] : memory[read_addr][8*1+7:8*1];
            read_data[8*2+7:8*2] <= (write_byte[2]) ? write_data[8*2+7:8*2] : memory[read_addr][8*2+7:8*2];
            read_data[8*3+7:8*3] <= (write_byte[3]) ? write_data[8*3+7:8*3] : memory[read_addr][8*3+7:8*3];
        end else begin
            read_data <= memory[read_addr];
        end
    end
end

endmodule
