"""Launch the QLoRA experiment as a SageMaker training job, wait for it, and download the results.

Usage (from the repo root, in VS Code or any terminal):
    python finetune/make_dataset.py
    python finetune/launch.py                       # ml.g5.2xlarge, Qwen2.5-3B-Instruct, waits and downloads
    python finetune/launch.py --no-wait             # just start it

Uses plain boto3, so there is no SDK version to fight with. The job runs the AWS PyTorch training container, installs the libraries
in finetune/requirements.txt, and runs finetune/train.py. Cost is the instance price for the run time (about 1.5 dollars an hour
for ml.g5.2xlarge). A hard stop time protects against a runaway job.
"""
from __future__ import annotations

import argparse
import io
import json
import tarfile
import time
from pathlib import Path

import boto3

HERE = Path(__file__).parent
REGION = "us-east-1"
IMAGE = "763104351884.dkr.ecr.us-east-1.amazonaws.com/pytorch-training:2.8.0-gpu-py312-cu129-ubuntu22.04-sagemaker"


def outputs() -> dict[str, str]:
    cf = boto3.client("cloudformation", region_name=REGION)
    out = cf.describe_stacks(StackName="ClaimsAdjudicationData")["Stacks"][0]["Outputs"]
    return {o["OutputKey"]: o["OutputValue"] for o in out}


def package_source() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(HERE / "train.py", arcname="train.py")
        tar.add(HERE / "scoring.py", arcname="scoring.py")
        tar.add(HERE / "requirements.txt", arcname="requirements.txt")
    return buf.getvalue()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", default="ml.g5.2xlarge")
    ap.add_argument("--model", default="Qwen/Qwen2.5-3B-Instruct")
    ap.add_argument("--epochs", type=float, default=3)
    ap.add_argument("--max-minutes", type=int, default=90, help="hard stop")
    ap.add_argument("--tag", default="qlora")
    ap.add_argument("--no-wait", action="store_true")
    a = ap.parse_args()

    o = outputs()
    bucket, role = o["FinetuneBucketName"], o["SageMakerRoleArn"]
    s3 = boto3.client("s3", region_name=REGION)
    sm = boto3.client("sagemaker", region_name=REGION)
    job = f"{a.tag}-claims-flags-{time.strftime('%Y%m%d-%H%M%S')}"

    s3.put_object(Bucket=bucket, Key=f"{job}/code/sourcedir.tar.gz", Body=package_source())
    for name, channel in (("train", "train"), ("dev", "train"), ("test_unseen", "test"), ("test_golden", "test")):
        s3.upload_file(str(HERE / "data" / f"{name}.jsonl"), bucket, f"{job}/data/{channel}/{name}.jsonl")

    hp = {"sagemaker_program": "train.py", "sagemaker_submit_directory": f"s3://{bucket}/{job}/code/sourcedir.tar.gz", "sagemaker_region": REGION,
          "model": a.model, "epochs": a.epochs}
    sm.create_training_job(
        TrainingJobName=job, RoleArn=role,
        AlgorithmSpecification={"TrainingImage": IMAGE, "TrainingInputMode": "File"},
        InputDataConfig=[{"ChannelName": ch, "DataSource": {"S3DataSource": {"S3DataType": "S3Prefix", "S3Uri": f"s3://{bucket}/{job}/data/{ch}/",
                                                                           "S3DataDistributionType": "FullyReplicated"}}} for ch in ("train", "test")],
        OutputDataConfig={"S3OutputPath": f"s3://{bucket}/{job}/output/"},
        ResourceConfig={"InstanceType": a.instance, "InstanceCount": 1, "VolumeSizeInGB": 80},
        StoppingCondition={"MaxRuntimeInSeconds": a.max_minutes * 60},
        HyperParameters={k: json.dumps(v) for k, v in hp.items()},  # script mode expects JSON encoded values
        Tags=[{"Key": "project", "Value": "claimsadj"}])
    print(f"started {job} on {a.instance}")
    if a.no_wait:
        return

    last = ""
    while True:
        d = sm.describe_training_job(TrainingJobName=job)
        status = f"{d['TrainingJobStatus']} / {d.get('SecondaryStatus', '')}"
        if status != last:
            print(time.strftime("%H:%M:%S"), status, flush=True)
            last = status
        if d["TrainingJobStatus"] in ("Completed", "Failed", "Stopped"):
            break
        time.sleep(30)
    if d["TrainingJobStatus"] != "Completed":
        raise SystemExit(f"job did not complete: {d.get('FailureReason', d['TrainingJobStatus'])}")
    secs = d.get("BillableTimeInSeconds", 0)
    print(f"billable seconds: {secs}")
    dest = HERE / "out" / job
    dest.mkdir(parents=True, exist_ok=True)
    s3.download_file(bucket, f"{job}/output/{job}/output/output.tar.gz", str(dest / "output.tar.gz"))
    with tarfile.open(dest / "output.tar.gz") as tar:
        tar.extractall(dest / "output", filter="data")
    (dest / "job.json").write_text(json.dumps({"job": job, "instance": a.instance, "billable_seconds": secs, "model": a.model}, indent=2))
    print("results in", dest)


if __name__ == "__main__":
    main()
