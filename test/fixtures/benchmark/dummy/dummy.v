// Dummy RTL file for testing
module gcd(input clk, input [7:0] a, b, output reg [7:0] result);
  always @(posedge clk) result <= a;
endmodule
