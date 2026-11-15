"""Create the QuickSight data source, datasets and dashboard over the telemetry lake. Usage: python scripts/quicksight_setup.py

Idempotent: existing objects are updated in place. Needs the QuickSight account to exist (see the README) and the Glue database
and Athena workgroup from the CDK data stack. Everything created here is named so it is easy to find and delete.
"""
import sys

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
ACCT = boto3.client("sts").get_caller_identity()["Account"]
qs = boto3.client("quicksight", region_name=REGION)
USER = f"arn:aws:quicksight:{REGION}:{ACCT}:user/default/{ACCT}"
DB = "claims_adjudication_telemetry"
DS_ID, DASH_ID = "claims-telemetry-athena", "claims-cost-latency"

S, INT, D, B = "STRING", "INTEGER", "DECIMAL", "BOOLEAN"
CALLS = [("call_id", S), ("run_id", S), ("claim_id", S), ("agent", S), ("model", S), ("input_tokens", INT), ("output_tokens", INT), ("cache_read", INT),
         ("cache_write", INT), ("latency_ms", INT), ("wall_ms", INT), ("cost_usd", D), ("error", S), ("variant", S), ("ts", S), ("day", S), ("mode", S)]
RUNS = [("run_id", S), ("claim_id", S), ("mode", S), ("variant", S), ("decision", S), ("latency_ms", INT), ("model_calls", INT), ("input_tokens", INT),
        ("output_tokens", INT), ("cost_usd", D), ("ok", B), ("error", S), ("ts", S), ("day", S)]

DS_ACTIONS = ["quicksight:DescribeDataSource", "quicksight:DescribeDataSourcePermissions", "quicksight:PassDataSource",
              "quicksight:UpdateDataSource", "quicksight:DeleteDataSource", "quicksight:UpdateDataSourcePermissions"]
SET_ACTIONS = ["quicksight:DescribeDataSet", "quicksight:DescribeDataSetPermissions", "quicksight:PassDataSet", "quicksight:DescribeIngestion",
               "quicksight:ListIngestions", "quicksight:UpdateDataSet", "quicksight:DeleteDataSet", "quicksight:CreateIngestion",
               "quicksight:CancelIngestion", "quicksight:UpdateDataSetPermissions"]
DASH_ACTIONS = ["quicksight:DescribeDashboard", "quicksight:ListDashboardVersions", "quicksight:UpdateDashboardPermissions",
                "quicksight:QueryDashboard", "quicksight:UpdateDashboard", "quicksight:DeleteDashboard",
                "quicksight:DescribeDashboardPermissions", "quicksight:UpdateDashboardPublishedVersion"]


def upsert(create, update, **kw):
    try:
        return create(**kw)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceExistsException":
            raise
        for k in ("Permissions", "Tags", "Type"):  # the update calls do not accept these
            kw.pop(k, None)
        return update(**kw)


def dataset(set_id: str, name: str, table: str, cols: list[tuple[str, str]], ds_arn: str) -> str:
    table_map = {table: {"RelationalTable": {"DataSourceArn": ds_arn, "Catalog": "AwsDataCatalog", "Schema": DB, "Name": table,
                                              "InputColumns": [{"Name": n, "Type": t} for n, t in cols]}}}
    # Latency is stored in milliseconds. A calculated column in seconds is what the dashboard shows, because a person reads 22.1 s faster than 22,100 ms.
    logical = {"main": {"Alias": name, "Source": {"PhysicalTableId": table}, "DataTransforms": [{"CreateColumnsOperation": {"Columns": [
        {"ColumnName": "latency_s", "ColumnId": f"{set_id}-latency-s", "Expression": "{latency_ms} / 1000"}]}}]}}
    upsert(qs.create_data_set, qs.update_data_set, AwsAccountId=ACCT, DataSetId=set_id, Name=name, ImportMode="DIRECT_QUERY",
           PhysicalTableMap=table_map, LogicalTableMap=logical, Permissions=[{"Principal": USER, "Actions": SET_ACTIONS}])
    return f"arn:aws:quicksight:{REGION}:{ACCT}:dataset/{set_id}"


def col(ds: str, name: str) -> dict:
    return {"DataSetIdentifier": ds, "ColumnName": name}


def measure(fid: str, ds: str, name: str, agg: str, dollars: int | None = None, seconds: bool = False) -> dict:
    field = {"FieldId": fid, "Column": col(ds, name), "AggregationFunction": {"SimpleNumericalAggregation": agg}}
    if dollars is not None:  # show money with a dollar sign and enough decimals that small differences stay visible
        field["FormatConfiguration"] = {"FormatConfiguration": {"NumberDisplayFormatConfiguration": {
            "Prefix": "$", "DecimalPlacesConfiguration": {"DecimalPlaces": dollars}}}}
    if seconds:
        field["FormatConfiguration"] = {"FormatConfiguration": {"NumberDisplayFormatConfiguration": {
            "Suffix": " s", "DecimalPlacesConfiguration": {"DecimalPlaces": 1}}}}
    return {"NumericalMeasureField": field}


def dim(fid: str, ds: str, name: str) -> dict:
    return {"CategoricalDimensionField": {"FieldId": fid, "Column": col(ds, name)}}


def title(text: str) -> dict:
    return {"Visibility": "VISIBLE", "FormatText": {"PlainText": text}}


def kpi(vid: str, text: str, ds: str, column: str, agg: str, dollars: int | None = None, seconds: bool = False) -> dict:
    return {"KPIVisual": {"VisualId": vid, "Title": title(text),
                          "ChartConfiguration": {"FieldWells": {"Values": [measure(f"{vid}m", ds, column, agg, dollars, seconds)]}}}}


def bars(vid: str, text: str, ds: str, category: str, value: str, agg: str, dollars: int | None = None, seconds: bool = False) -> dict:
    return {"BarChartVisual": {"VisualId": vid, "Title": title(text),
                               "ChartConfiguration": {"FieldWells": {"BarChartAggregatedFieldWells": {
                                   "Category": [dim(f"{vid}c", ds, category)], "Values": [measure(f"{vid}m", ds, value, agg, dollars, seconds)]}},
                                   "Orientation": "HORIZONTAL", "BarsArrangement": "CLUSTERED",
                                   "SortConfiguration": {"CategorySort": [{"FieldSort": {"FieldId": f"{vid}m", "Direction": "DESC"}}]},
                                   "DataLabels": {"Visibility": "VISIBLE"}}}}


def slowest(vid: str) -> dict:
    cols = [("agent", S), ("model", S), ("claim_id", S), ("variant", S), ("input_tokens", INT), ("latency_s", INT)]
    values = []
    for n, t in cols:
        field = ({"NumericalDimensionField": {"FieldId": f"{vid}{n}", "Column": col("calls", n)}} if t == INT
                 else {"CategoricalDimensionField": {"FieldId": f"{vid}{n}", "Column": col("calls", n)}})
        values.append(field)
    return {"TableVisual": {"VisualId": vid, "Title": title("Slowest model calls"),
                            "ChartConfiguration": {"FieldWells": {"TableUnaggregatedFieldWells": {"Values": [
                                {"FieldId": f"{vid}{n}", "Column": col("calls", n)} for n, _ in cols]}},
                                "SortConfiguration": {"RowSort": [{"FieldSort": {"FieldId": f"{vid}latency_s", "Direction": "DESC"}}]}}}}


def definition(runs_arn: str, calls_arn: str) -> dict:
    visuals = [
        kpi("k1", "Average cost per claim", "runs", "cost_usd", "AVERAGE", 4),
        kpi("k2", "Average latency per claim (seconds)", "runs", "latency_s", "AVERAGE", seconds=True),
        kpi("k3", "Total model spend in this data", "calls", "cost_usd", "SUM", 2),
        bars("b1", "Where the money goes: cost by agent", "calls", "agent", "cost_usd", "SUM", 2),
        bars("b2", "Cost by model", "calls", "model", "cost_usd", "SUM", 2),
        bars("b3", "Average cost per claim, by variant (before and after)", "runs", "variant", "cost_usd", "AVERAGE", 4),
        bars("b4", "Average latency per claim, by variant (seconds)", "runs", "variant", "latency_s", "AVERAGE", seconds=True),
        slowest("t1"),
    ]
    el = lambda vid, c, w, h: {"ElementId": vid, "ElementType": "VISUAL", "ColumnIndex": c, "ColumnSpan": w, "RowSpan": h}  # noqa: E731
    layout = [el("k1", 0, 12, 6), el("k2", 12, 12, 6), el("k3", 24, 12, 6), el("b1", 0, 18, 12), el("b2", 18, 18, 12),
              el("b3", 0, 18, 12), el("b4", 18, 18, 12), el("t1", 0, 36, 14)]
    top12 = {"FilterGroupId": "slowest-12", "Status": "ENABLED", "CrossDataset": "SINGLE_DATASET", "Filters": [{"TopBottomFilter": {
        "FilterId": "top12", "Column": col("calls", "call_id"), "Limit": 12, "AggregationSortConfigurations": [{
            "Column": col("calls", "latency_s"), "SortDirection": "DESC",
            "AggregationFunction": {"NumericalAggregationFunction": {"SimpleNumericalAggregation": "MAX"}}}]}}],
        "ScopeConfiguration": {"SelectedSheets": {"SheetVisualScopingConfigurations": [
            {"SheetId": "cost-latency", "Scope": "SELECTED_VISUALS", "VisualIds": ["t1"]}]}}}
    return {"FilterGroups": [top12], "DataSetIdentifierDeclarations": [{"Identifier": "runs", "DataSetArn": runs_arn}, {"Identifier": "calls", "DataSetArn": calls_arn}],
            "Sheets": [{"SheetId": "cost-latency", "Name": "Cost and latency", "Visuals": visuals,
                        "Layouts": [{"Configuration": {"GridLayout": {"Elements": layout}}}]}]}


def main() -> None:
    ds_arn = f"arn:aws:quicksight:{REGION}:{ACCT}:datasource/{DS_ID}"
    upsert(qs.create_data_source, qs.update_data_source, AwsAccountId=ACCT, DataSourceId=DS_ID, Name="Claims telemetry (Athena)", Type="ATHENA",
           DataSourceParameters={"AthenaParameters": {"WorkGroup": "claims-adjudication"}}, Permissions=[{"Principal": USER, "Actions": DS_ACTIONS}])
    runs_arn = dataset("claims-runs", "Claim runs", "runs", RUNS, ds_arn)
    calls_arn = dataset("claims-calls", "Model calls", "calls", CALLS, ds_arn)
    qs_def = definition(runs_arn, calls_arn)
    try:
        qs.create_dashboard(AwsAccountId=ACCT, DashboardId=DASH_ID, Name="Claims adjudication: cost and latency", Definition=qs_def,
                            Permissions=[{"Principal": USER, "Actions": DASH_ACTIONS}])
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceExistsException":
            raise
        v = qs.update_dashboard(AwsAccountId=ACCT, DashboardId=DASH_ID, Name="Claims adjudication: cost and latency", Definition=qs_def)
        qs.update_dashboard_published_version(AwsAccountId=ACCT, DashboardId=DASH_ID, VersionNumber=int(v["VersionArn"].split("/")[-1]))
    d = qs.describe_dashboard(AwsAccountId=ACCT, DashboardId=DASH_ID)["Dashboard"]
    print("dashboard:", d["Name"], "|", d["Version"]["Status"], "| errors:", d["Version"].get("Errors", []))
    print(f"open: https://{REGION}.quicksight.aws.amazon.com/sn/dashboards/{DASH_ID}")
    sys.exit(0 if d["Version"]["Status"] in ("CREATION_SUCCESSFUL", "CREATION_IN_PROGRESS") else 1)


if __name__ == "__main__":
    main()
