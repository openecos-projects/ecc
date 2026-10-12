
(* techmap_celltype = "\$_TBUF_" *)
module _tbuf_disabled (A, E, Y);
  input A, E;
  output Y;
  parameter _TECHMAP_CONSTMSK_E_ = 1'b0;
  parameter _TECHMAP_CONSTVAL_E_ = 1'bx;
  wire _TECHMAP_FAIL_ = !(_TECHMAP_CONSTMSK_E_ && !_TECHMAP_CONSTVAL_E_);
  wire [1023:0] _TECHMAP_DO_ = "connect -unset Y";
endmodule

(* techmap_celltype = "\$_TBUF_" *)
module _tbuf_enabled (A, E, Y);
  input A, E;
  output Y;
  TBUFX1H7R _TECHMAP_REPLACE_ (.A(A), .OE(E), .Y(Y));
endmodule

