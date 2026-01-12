// Dummy netlist file for testing (pre-synthesized)
module gcd(input clk, input [7:0] a, b, output [7:0] result);
  wire [7:0] n1;
  BUF buf0 (.A(a[0]), .Y(n1[0]));
  assign result = n1;
endmodule
