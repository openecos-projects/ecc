from chipcompiler.tools.ecc.module import ECCToolsModule as _BaseECCToolsModule


class ECCToolsModule(_BaseECCToolsModule):
    def _require_dreamplace_api(self, api_name: str):
        api = getattr(self.ecc, api_name, None)
        if api is None:
            raise AttributeError(
                f"ecc_py does not expose dreamplace IO API '{api_name}'. "
                "Please use an ecc runtime that includes the iEDA/DreamPlace bridge."
            )
        return api

    def has_dreamplace_db_io(self) -> bool:
        required = ("get_dmInst_ptr", "pydb", "write_placement_back")
        return all(hasattr(self.ecc, api_name) for api_name in required)

    def get_dmInst_ptr(self):
        return self._require_dreamplace_api("get_dmInst_ptr")()

    def pydb(
        self,
        dm_inst_ptr,
        route_num_bins_x: int,
        route_num_bins_y: int,
        routability_opt_flag: int,
        with_sta: int,
    ):
        return self._require_dreamplace_api("pydb")(
            dm_inst_ptr,
            route_num_bins_x,
            route_num_bins_y,
            routability_opt_flag,
            with_sta,
        )

    def build_macro_connection_map(self, max_hop: int):
        api = getattr(self.ecc, "build_macro_connection_map", None)
        if api is None:
            return []
        return api(max_hop)


__all__ = ["ECCToolsModule"]
