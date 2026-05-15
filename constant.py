# AWS regions to scan for running EC2 instances.
# Add more regions to the list as needed, e.g. ['us-west-2', 'us-east-1'].
regions = ['us-west-2']

# Slack incoming-webhook URL.
# Replace this placeholder with your real webhook URL before deploying.
# Never commit real webhook URLs or secrets to source control.
slack_webhook_url = 'https://hooks.slack.com/services/XXXX/XXXX/XXXX'

# Value of the PLATFORM_TYPE EC2 tag that this Lambda will manage.
# Only instances whose PLATFORM_TYPE tag exactly matches this value will be
# considered for shutdown. All other instances are ignored.
platform_type = 'YOUR_PLATFORM_TYPE'

# Hour (24h clock, IST) after which INDIA-team instances are stopped each day.
# e.g. 21 = 9 PM IST
indiastoptime = 21

# Hour (24h clock, IST) after which US-team instances are stopped each day.
# e.g. 9 = 9 AM IST
usstoptime = 9

# Day of the week on which WEEKLY-scheduled instances are stopped.
# Must match Python's strftime("%A") format, e.g. 'Monday', 'Friday'.
IndiaStopDay = 'Friday'
UsStopDay    = 'Saturday'