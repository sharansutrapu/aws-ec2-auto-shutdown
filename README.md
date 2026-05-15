# ec2-auto-shutdown

An AWS Lambda function that automatically stops EC2 instances on a daily or weekly schedule based on instance tags. Sends a Slack notification summarising what was stopped and publishes a CloudWatch custom metric with the shutdown count.

---

## How it works

1. A **CloudWatch Events** cron rule triggers the Lambda twice a day.
2. The Lambda scans all running EC2 instances in the configured regions.
3. For each instance it reads a set of **required tags** to decide whether and when to stop it.
4. After processing, a **Slack message** is posted listing every instance that was stopped.
5. The total shutdown count is published as a **CloudWatch custom metric** (`Instanceshutdown/DevInstanceShutDown`).

### Required EC2 tags

| Tag             | Required | Example values          | Description                                      |
|-----------------|----------|-------------------------|--------------------------------------------------|
| `SHUTDOWN`      | Yes      | `DAILY`, `WEEKLY`       | How often to shut the instance down              |
| `PLATFORM_TYPE` | Yes      | *(set in `constant.py`)* | Only instances whose tag matches `constant.platform_type` are touched |
| `TEAM_LOCATION` | Yes      | `INDIA`, `US`           | Determines which stop-time rule to apply         |
| `Name`          | No       | `my-dev-server`         | Shown in the Slack notification                  |
| `POC`           | No       | `john.doe`              | Point-of-contact shown in the Slack notification |

---

## Configuration

Edit `constant.py` before deploying:

```python
# AWS regions to scan
regions = ['us-west-2']

# Slack incoming-webhook URL
slack_webhook_url = 'https://hooks.slack.com/services/...'

# Value of the PLATFORM_TYPE EC2 tag this Lambda will manage.
# Only instances whose tag matches this value are eligible for shutdown.
platform_type = 'YOUR_PLATFORM_TYPE'

# Hour (24h, IST) after which INDIA instances are stopped
indiastoptime = 21   # 9 PM IST

# Hour (24h, IST) after which US instances are stopped
usstoptime = 9       # 9 AM IST

# Day of the week for WEEKLY shutdowns
IndiaStopDay = 'Friday'
UsStopDay    = 'Saturday'
```

> **Note:** The `slack_webhook_url` in `constant.py` is a placeholder. Replace it with your real webhook URL before deploying. Never commit real secrets to source control.

---

## Prerequisites

- Python 3.8+
- [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html) configured with appropriate permissions
- An IAM role for the Lambda with at least:
  - `ec2:DescribeInstances`
  - `ec2:StopInstances`
  - `cloudwatch:PutMetricData`
- A Slack [incoming webhook URL](https://api.slack.com/messaging/webhooks)

---

## Deployment

### 1. Clone and configure

```bash
git clone https://github.com/sharansutrapu/ec2-auto-shutdown.git
cd ec2-auto-shutdown
```

Edit `constant.py` with your regions, Slack webhook URL, and stop times.

### 2. Package dependencies

```bash
pip3 install --target ./package -r requirements.txt
cd package
zip -r ../instancestop.zip .
cd ..
```

### 3. Add source files to the zip

```bash
zip -g instancestop.zip instanceshutdown.py
zip -g instancestop.zip constant.py
```

### 4. Create the Lambda function

```bash
aws lambda create-function \
  --function-name instance_shutdown \
  --zip-file fileb://instancestop.zip \
  --runtime python3.8 \
  --role arn:aws:iam::<ACCOUNT_ID>:role/<LAMBDA_ROLE_NAME> \
  --handler instanceshutdown.lambda_handler \
  --timeout 300
```

Replace `<ACCOUNT_ID>` and `<LAMBDA_ROLE_NAME>` with your values.

---

## CloudWatch Events trigger

Run these two commands to create a cron rule that fires at **04:30 UTC and 16:30 UTC** every day:

```bash
aws events put-rule \
  --name "DailyInstanceShutDown" \
  --schedule-expression "cron(30 4,16 ? * * *)"

aws events put-targets \
  --rule DailyInstanceShutDown \
  --targets "Id"="1","Arn"="arn:aws:lambda:<REGION>:<ACCOUNT_ID>:function:instance_shutdown"
```

---

## Updating the Lambda

After making code changes, repackage and update:

```bash
pip3 install --target ./package -r requirements.txt
cd package
zip -r ../instancestop.zip .
cd ..
zip -g instancestop.zip instanceshutdown.py
zip -g instancestop.zip constant.py
aws lambda update-function-code \
  --function-name instance_shutdown \
  --zip-file fileb://instancestop.zip
```

---

## Dependencies

| Package    | Purpose                                     |
|------------|---------------------------------------------|
| `requests` | HTTP POST to the Slack incoming webhook     |
| `pytz`     | Timezone-aware datetime for shutdown logic  |

Install locally with:

```bash
pip3 install -r requirements.txt
```

