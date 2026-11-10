import io
import json
import zipfile

import boto3
import pytest
from moto import mock_aws

from deploy import deploy_aws as d

REGION = "us-east-1"
BUCKET = "marketlens-data-test"


def tiny_zip(tmp_path):
    path = tmp_path / "f.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("marketlens/__init__.py", "")
        z.writestr("marketlens/lambda_handler.py", "def handler(event, context):\n    return {}\n")
    return str(path)


@pytest.fixture
def aws():
    with mock_aws():
        yield boto3.Session(region_name=REGION)


def test_deploy_creates_everything(aws, tmp_path):
    info = d.deploy(aws, REGION, BUCKET, tiny_zip(tmp_path), "https://hooks.example/x")
    s3, lam, events, iam = aws.client("s3"), aws.client("lambda"), aws.client("events"), aws.client("iam")

    block = s3.get_public_access_block(Bucket=BUCKET)["PublicAccessBlockConfiguration"]
    assert all(block.values())
    rule = s3.get_bucket_lifecycle_configuration(Bucket=BUCKET)["Rules"][0]
    assert rule["Filter"]["Prefix"] == "raw/" and rule["Expiration"]["Days"] == 30

    cfg = lam.get_function_configuration(FunctionName=d.FUNCTION)
    assert cfg["Handler"] == "marketlens.lambda_handler.handler"
    assert cfg["Timeout"] == 900 and cfg["MemorySize"] == 2048
    assert cfg["Environment"]["Variables"] == {"MARKETLENS_BUCKET": BUCKET, "SLACK_WEBHOOK_URL": "https://hooks.example/x"}

    rule = events.describe_rule(Name=d.RULE)
    assert rule["ScheduleExpression"] == d.SCHEDULE and rule["State"] == "ENABLED"
    assert events.list_targets_by_rule(Rule=d.RULE)["Targets"][0]["Arn"] == info["function"]

    policy = iam.get_role_policy(RoleName=d.ROLE, PolicyName="marketlens-bucket-access")["PolicyDocument"]
    resources = [r for s in policy["Statement"] for r in ([s["Resource"]] if isinstance(s["Resource"], str) else s["Resource"])]
    s3_resources = [r for r in resources if r.startswith("arn:aws:s3")]
    assert s3_resources and all(BUCKET in r for r in s3_resources)   # the function can only touch its own bucket
    assert all(r.startswith(("arn:aws:s3", "arn:aws:logs")) for r in resources)      # no blanket "*" permission


def test_running_the_deploy_twice_is_safe(aws, tmp_path):
    z = tiny_zip(tmp_path)
    d.deploy(aws, REGION, BUCKET, z)
    d.deploy(aws, REGION, BUCKET, z, "https://hooks.example/y")     # second run adds Slack and changes nothing else
    cfg = aws.client("lambda").get_function_configuration(FunctionName=d.FUNCTION)
    assert cfg["Environment"]["Variables"]["SLACK_WEBHOOK_URL"] == "https://hooks.example/y"
    assert len(aws.client("events").list_targets_by_rule(Rule=d.RULE)["Targets"]) == 1


def test_log_retention_is_set(aws, tmp_path):
    d.deploy(aws, REGION, BUCKET, tiny_zip(tmp_path))
    groups = aws.client("logs").describe_log_groups(logGroupNamePrefix=f"/aws/lambda/{d.FUNCTION}")["logGroups"]
    assert groups[0]["retentionInDays"] == 14


def test_package_contains_the_code_and_not_tests(tmp_path):
    import os
    import shutil
    root = tmp_path / "repo"
    (root / "marketlens").mkdir(parents=True)
    (root / "marketlens" / "lambda_handler.py").write_text("x = 1\n")
    (root / "marketlens" / "__pycache__").mkdir()
    (root / "marketlens" / "__pycache__" / "junk.pyc").write_text("junk")
    (root / "requirements-lambda.txt").write_text("")          # nothing to install, so no network is needed
    out = d.build_package(str(tmp_path / "out.zip"), root=str(root))
    names = zipfile.ZipFile(out).namelist()
    assert "marketlens/lambda_handler.py" in names
    assert not any("__pycache__" in n for n in names)
