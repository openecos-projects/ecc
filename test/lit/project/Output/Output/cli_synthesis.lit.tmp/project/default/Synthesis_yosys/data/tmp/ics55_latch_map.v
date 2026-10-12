
module \$_DLATCH_N_ (E, D, Q);
  input E, D;
  output Q;
  LATLX1H7R _TECHMAP_REPLACE_ (.D(D), .GN(E), .Q(Q));
endmodule

module \$_DLATCH_P_ (E, D, Q);
  input E, D;
  output Q;
  LATHX1H7R _TECHMAP_REPLACE_ (.D(D), .G(E), .Q(Q));
endmodule

module \$_DLATCH_NN0_ (E, R, D, Q);
  input E, R, D;
  output Q;
  LATLRX1H7R _TECHMAP_REPLACE_ (.D(D), .RN(R), .GN(E), .Q(Q));
endmodule

module \$_DLATCH_NN1_ (E, R, D, Q);
  input E, R, D;
  output Q;
  LATLSX1H7R _TECHMAP_REPLACE_ (.D(D), .SN(R), .GN(E), .Q(Q));
endmodule

module \$_DLATCH_NP0_ (E, R, D, Q);
  input E, R, D;
  output Q;
  wire RN;
  INVX1H7R inv_reset (.A(R), .Y(RN));
  LATLRX1H7R _TECHMAP_REPLACE_ (.D(D), .RN(RN), .GN(E), .Q(Q));
endmodule

module \$_DLATCH_NP1_ (E, R, D, Q);
  input E, R, D;
  output Q;
  wire SN;
  INVX1H7R inv_set (.A(R), .Y(SN));
  LATLSX1H7R _TECHMAP_REPLACE_ (.D(D), .SN(SN), .GN(E), .Q(Q));
endmodule

module \$_DLATCH_PN0_ (E, R, D, Q);
  input E, R, D;
  output Q;
  LATHRX1H7R _TECHMAP_REPLACE_ (.D(D), .RN(R), .G(E), .Q(Q));
endmodule

module \$_DLATCH_PN1_ (E, R, D, Q);
  input E, R, D;
  output Q;
  LATHSX1H7R _TECHMAP_REPLACE_ (.D(D), .SN(R), .G(E), .Q(Q));
endmodule

module \$_DLATCH_PP0_ (E, R, D, Q);
  input E, R, D;
  output Q;
  wire RN;
  INVX1H7R inv_reset (.A(R), .Y(RN));
  LATHRX1H7R _TECHMAP_REPLACE_ (.D(D), .RN(RN), .G(E), .Q(Q));
endmodule

module \$_DLATCH_PP1_ (E, R, D, Q);
  input E, R, D;
  output Q;
  wire SN;
  INVX1H7R inv_set (.A(R), .Y(SN));
  LATHSX1H7R _TECHMAP_REPLACE_ (.D(D), .SN(SN), .G(E), .Q(Q));
endmodule

