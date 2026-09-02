from .common import config_param

SCHEMAS = (
    config_param(
        "sta.signoff",
        "sta",
        ("signoff",),
        [
            {
                "MAX": ["Cworst", "RCworst"],
                "WCL": ["Cworst", "RCworst"],
                "TYP": ["TYPICAL"],
                "MIN": ["Cworst", "RCworst", "Cbest", "RCbest"],
                "ML": ["Cworst", "RCworst", "Cbest", "RCbest"],
            }
        ],
        applies="sta",
        type="json",
    ),
)
