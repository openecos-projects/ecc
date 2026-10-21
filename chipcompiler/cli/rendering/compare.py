import sys

from chipcompiler.cli.rendering.pretty import render_field, render_header


def render_compare_run_text(records: tuple[dict, ...], file=None, *, color: bool = True) -> None:
    target = file or sys.stdout
    for record in records:
        print(render_header("run_comparison", color=color), file=target)
        for role in ("baseline", "current"):
            identity = record[role]
            print(
                render_field(
                    role,
                    f"{identity['workspace_id']} revision {identity['workspace_revision']} "
                    f"({identity['source']})",
                    color=color,
                ),
                file=target,
            )
        print(render_field("overall (numeric only)", record["summary"]["overall"]), file=target)
        for metric in record["metrics"]:
            label = f"{metric['id']} [{metric['scope']}, {metric['corner'] or 'no corner'}]"
            value = (
                f"{metric['baseline']} -> {metric['current']}; delta={metric['delta']}; "
                f"unit={metric['baseline_unit']} -> {metric['current_unit']}; {metric['trend']}"
            )
            if metric["reasons"]:
                value += f" ({', '.join(metric['reasons'])})"
            print(render_field(label, value), file=target)
        score = record["qor"]["score"]
        print(
            render_field(
                "QoR score", f"{score['baseline']} -> {score['current']}; {score['trend']}"
            ),
            file=target,
        )
        for section in ("steps", "parameter_changes", "configuration_changes", "artifacts"):
            changes = [item for item in record[section] if item["change"] != "unchanged"]
            print(render_field(f"{section} changed", len(changes)), file=target)
        for reason in record["compatibility"]["reasons"]:
            print(render_field("not comparable", reason), file=target)
        for warning in record["warnings"]:
            print(render_field("warning", warning), file=target)
