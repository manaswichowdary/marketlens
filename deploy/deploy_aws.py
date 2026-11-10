"""Deploy the MarketLens daily run to AWS. Run it in AWS CloudShell, from the repo folder:

    python deploy/deploy_aws.py                 # create or update everything
    python deploy/deploy_aws.py --invoke        # also run the function once and show the result

It creates, in one region (default us-east-1):
  1. an S3 bucket that holds the database and the raw files (private, raw files expire after 30 days)
  2. an IAM role that lets the function read and write only that bucket and write its own logs
  3. the Lambda function (Python 3.12, 2 GB memory, 15 minute limit)
  4. an EventBridge rule that starts it every day at 13:00 UTC (6 AM in Phoenix)
Running it again updates the code and settings and leaves everything else alone.

If SLACK_WEBHOOK_URL is set in your shell, it is stored on the function as an environment variable so problems can
be posted to Slack. It is plain text in the function settings, so use a webhook that can only post to one channel.

Cost: one run takes about a minute of compute, so a month of runs is far inside the free tier. S3 holds a few
hundred MB. The expected bill is a few cents a month.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

FUNCTION = "marketlens-daily"
ROLE = "marketlens-daily-role"
RULE = "marketlens-daily-schedule"
SCHEDULE = "cron(0 13 * * ? *)"
RUNTIME = "python3.12"
RAW_DAYS = 30
LOG_DAYS = 14
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build_package(out_zip, root=ROOT):
    """Install the Lambda dependencies for Linux (whatever machine this runs on) and zip them with our code."""
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "-r", os.path.join(root, "requirements-lambda.txt"),
             "--platform", "manylinux2014_x86_64", "--implementation", "cp", "--python-version", "3.12",
             "--only-binary=:all:", "--target", tmp], check=True)
        shutil.copytree(os.path.join(root, "marketlens"), os.path.join(tmp, "marketlens"),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for folder, _, files in os.walk(tmp):
                if "__pycache__" in folder:
                    continue
                for name in files:
                    path = os.path.join(folder, name)
                    z.write(path, os.path.relpath(path, tmp))
    return out_zip


def ensure_bucket(s3, name, region):
    try:
        if region == "us-east-1":
            s3.create_bucket(Bucket=name)
        else:
            s3.create_bucket(Bucket=name, CreateBucketConfiguration={"LocationConstraint": region})
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("BucketAlreadyOwnedByYou",):
            raise
    s3.put_public_access_block(Bucket=name, PublicAccessBlockConfiguration={
        "BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True})
    # Versioning protects the database file from a bad overwrite. Old versions are removed after a week so the
    # 100 MB file does not pile up, and raw files expire after RAW_DAYS days.
    s3.put_bucket_versioning(Bucket=name, VersioningConfiguration={"Status": "Enabled"})
    s3.put_bucket_lifecycle_configuration(Bucket=name, LifecycleConfiguration={"Rules": [
        {"ID": "expire-raw-files", "Status": "Enabled", "Filter": {"Prefix": "raw/"},
         "Expiration": {"Days": RAW_DAYS}},
        {"ID": "expire-old-versions", "Status": "Enabled", "Filter": {"Prefix": ""},
         "NoncurrentVersionExpiration": {"NoncurrentDays": 7}}]})


def ensure_role(iam, bucket):
    """The function may use only this bucket. Returns the role ARN and whether it was just created."""
    trust = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
             "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]}
    created = False
    try:
        role = iam.create_role(RoleName=ROLE, AssumeRolePolicyDocument=json.dumps(trust),
                               Description="Runs the MarketLens daily pipeline")["Role"]
        created = True
    except ClientError as e:
        if e.response["Error"]["Code"] != "EntityAlreadyExists":
            raise
        role = iam.get_role(RoleName=ROLE)["Role"]
    iam.put_role_policy(RoleName=ROLE, PolicyName="marketlens-bucket-access", PolicyDocument=json.dumps({
        "Version": "2012-10-17", "Statement": [
            {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject"], "Resource": f"arn:aws:s3:::{bucket}/*"},
            {"Effect": "Allow", "Action": ["s3:ListBucket"], "Resource": f"arn:aws:s3:::{bucket}"},
            {"Effect": "Allow", "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
             "Resource": f"arn:aws:logs:*:*:log-group:/aws/lambda/{FUNCTION}:*"}]}))
    return role["Arn"], created


def ensure_function(lam, role_arn, bucket, key, env, role_is_new=False):
    if "SLACK_WEBHOOK_URL" not in env:      # a redeploy must not silently drop the webhook that is already saved
        try:
            saved = lam.get_function_configuration(FunctionName=FUNCTION).get("Environment", {}).get("Variables", {})
            if saved.get("SLACK_WEBHOOK_URL"):
                env = {**env, "SLACK_WEBHOOK_URL": saved["SLACK_WEBHOOK_URL"]}
        except ClientError:
            pass
    config = dict(Runtime=RUNTIME, Role=role_arn, Handler="marketlens.lambda_handler.handler", Timeout=900,
                  MemorySize=2048, EphemeralStorage={"Size": 2048}, Environment={"Variables": env})
    code = {"S3Bucket": bucket, "S3Key": key}
    try:
        lam.get_function(FunctionName=FUNCTION)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        for attempt in range(8):    # a brand new role can take a few seconds before Lambda may use it
            try:
                arn = lam.create_function(FunctionName=FUNCTION, Code=code, **config)["FunctionArn"]
                lam.get_waiter("function_active_v2").wait(FunctionName=FUNCTION)   # a new function starts as Pending
                return arn
            except ClientError as err:
                if "cannot be assumed" not in str(err) or attempt == 7:
                    raise
                time.sleep(5 if role_is_new else 1)
    lam.update_function_code(FunctionName=FUNCTION, **code)
    lam.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION)
    arn = lam.update_function_configuration(FunctionName=FUNCTION, **config)["FunctionArn"]
    lam.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION)
    return arn


def ensure_schedule(events, lam, function_arn):
    rule_arn = events.put_rule(Name=RULE, ScheduleExpression=SCHEDULE, State="ENABLED",
                               Description="Start the MarketLens daily run")["RuleArn"]
    try:
        lam.add_permission(FunctionName=FUNCTION, StatementId="allow-eventbridge", Action="lambda:InvokeFunction",
                           Principal="events.amazonaws.com", SourceArn=rule_arn)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceConflictException":
            raise
    events.put_targets(Rule=RULE, Targets=[{"Id": "marketlens-daily", "Arn": function_arn}])


def ensure_log_retention(logs):
    name = f"/aws/lambda/{FUNCTION}"
    try:
        logs.create_log_group(logGroupName=name)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceAlreadyExistsException":
            raise
    logs.put_retention_policy(logGroupName=name, retentionInDays=LOG_DAYS)


def deploy(session, region, bucket, zip_path, slack_webhook=""):
    s3, iam, lam = session.client("s3"), session.client("iam"), session.client("lambda")
    events, logs = session.client("events"), session.client("logs")
    ensure_bucket(s3, bucket, region)
    key = "deploy/marketlens-daily.zip"
    s3.upload_file(zip_path, bucket, key)
    role_arn, created = ensure_role(iam, bucket)
    env = {"MARKETLENS_BUCKET": bucket}
    if slack_webhook:
        env["SLACK_WEBHOOK_URL"] = slack_webhook
    ensure_log_retention(logs)
    function_arn = ensure_function(lam, role_arn, bucket, key, env, role_is_new=created)
    saved = lam.get_function_configuration(FunctionName=FUNCTION).get("Environment", {}).get("Variables", {})
    ensure_schedule(events, lam, function_arn)
    return {"bucket": bucket, "function": function_arn, "schedule": SCHEDULE, "slack": bool(saved.get("SLACK_WEBHOOK_URL"))}


def invoke_once(session):
    lam = session.client("lambda", config=Config(read_timeout=900, retries={"max_attempts": 0}))
    lam.get_waiter("function_active_v2").wait(FunctionName=FUNCTION)
    out = lam.invoke(FunctionName=FUNCTION, InvocationType="RequestResponse", LogType="Tail")
    body = out["Payload"].read().decode()
    return out.get("FunctionError"), body


def main():
    ap = argparse.ArgumentParser(description="Deploy the MarketLens daily run.")
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--bucket", default="", help="default: marketlens-data-<account id>")
    ap.add_argument("--invoke", action="store_true", help="run the function once after deploying")
    ap.add_argument("--zip", default="/tmp/marketlens-daily.zip")
    args = ap.parse_args()

    session = boto3.Session(region_name=args.region)
    account = session.client("sts").get_caller_identity()["Account"]
    bucket = args.bucket or f"marketlens-data-{account}"
    print(f"account {account}, region {args.region}, bucket {bucket}")
    print("building the package (about a minute)...")
    build_package(args.zip)
    print(f"package size: {os.path.getsize(args.zip) / 1e6:.1f} MB")
    info = deploy(session, args.region, bucket, args.zip, os.environ.get("SLACK_WEBHOOK_URL", ""))
    print("deployed:", json.dumps(info, indent=2))
    if not info["slack"]:
        print("note: no Slack webhook is saved on the function, so problems will only show in the function logs.")
    if args.invoke:
        print("running once (this can take a couple of minutes)...")
        error, body = invoke_once(session)
        print("function error:" if error else "result:", body[:1500])


if __name__ == "__main__":
    main()
