"""
ec2-auto-shutdown — AWS Lambda function

Automatically stops EC2 instances on a configurable daily or weekly schedule.
Eligibility is controlled entirely by EC2 instance tags, so no code changes are
needed when adding or removing instances from the schedule.

After each run the function:
  - Posts a Slack notification listing every instance that was stopped.
  - Publishes a CloudWatch custom metric with the total shutdown count.

Required EC2 instance tags
--------------------------
  SHUTDOWN        "DAILY" | "WEEKLY"
                  How often the instance should be stopped.

  PLATFORM_TYPE   Must match the value of constant.platform_type.
                  Only instances with a matching value are managed by this Lambda.

  TEAM_LOCATION   "INDIA" | "US"
                  Selects which stop-hour and stop-day rule to apply.

Optional EC2 instance tags
--------------------------
  Name            Human-readable name shown in the Slack notification.
  POC             Point-of-contact shown in the Slack notification.

Configuration
-------------
All tuneable values (regions, Slack webhook URL, stop hours, stop days,
platform type) are in constant.py.
"""

import json
import boto3
import requests
from datetime import datetime
import pytz
import constant


# --------------------------------------------------------------------------- #
# Slack notification helper                                                     #
# --------------------------------------------------------------------------- #

def send_slack_message(slack_webhook_url, slack_message):
    """Post a plain-text message to a Slack channel via an incoming webhook.

    Args:
        slack_webhook_url (str): The Slack incoming webhook URL (from constant.py).
        slack_message     (str): The message body to post to Slack.
    """
    print('>send_slack_message: message=' + slack_message)

    slack_payload = {'text': slack_message}

    print('>send_slack_message: posting to Slack webhook')
    response = requests.post(slack_webhook_url, json.dumps(slack_payload))

    print('>send_slack_message: response=' + str(response.text))


# --------------------------------------------------------------------------- #
# Core shutdown logic                                                           #
# --------------------------------------------------------------------------- #

def find_running_ec2instances():
    """Scan configured AWS regions and stop eligible running EC2 instances.

    Shutdown eligibility rules
    --------------------------
    An instance is stopped when ALL of the following conditions are met:

      1. The instance has the tags SHUTDOWN, PLATFORM_TYPE, and TEAM_LOCATION.
      2. PLATFORM_TYPE matches constant.platform_type.
      3. SHUTDOWN == "DAILY"
           INDIA team : current IST hour >= constant.indiastoptime (every day)
           US team    : current IST hour >= constant.usstoptime    (every day)
         SHUTDOWN == "WEEKLY"
           INDIA team : above hour condition AND today == constant.IndiaStopDay
           US team    : above hour condition AND today == constant.UsStopDay

    Side effects:
      - Calls boto3 stop_instances for each eligible instance.
      - Updates the module-level global `totalinstanceshutdown`.
      - Calls send_slack_message if at least one instance was stopped.

    Returns:
        int: Total number of running EC2 instances found across all regions
             (includes instances that were not eligible for shutdown).
    """
    # Flag – flipped to 1 the first time an instance is stopped so we know
    # whether to send the Slack notification at the end.
    send_message_to_slack = 0

    # Module-level global so lambda_handler can read the count after this
    # function returns.
    global totalinstanceshutdown
    totalinstanceshutdown = 0

    # Running tally returned to the caller (all running instances, not just stopped ones)
    total_running_ec2_instances = 0

    # Slack message body – eligible instances are appended as they are stopped
    notification_message = 'The following EC2 instance(s) are ShutDown:\n'

    # Resolve current time in IST once so every instance comparison uses the
    # same timestamp for this invocation.
    IST = pytz.timezone('Asia/Kolkata')
    current_time = datetime.now(IST)

    # ---------------------------------------------------------------------- #
    # Iterate over every AWS region defined in constant.regions               #
    # ---------------------------------------------------------------------- #
    for region in constant.regions:

        # Create a region-specific EC2 client
        client = boto3.client('ec2', region_name=region)

        # Fetch only instances currently in the "running" state to avoid
        # trying to stop instances that are already stopped/terminated.
        running_ec2_instances = client.describe_instances(
            Filters=[{'Name': 'instance-state-name', 'Values': ['running']}]
        )

        # describe_instances groups results into Reservations – iterate each group
        for groups in running_ec2_instances['Reservations']:
            instances = groups['Instances']

            if not instances:
                # Empty reservation – nothing to process
                continue

            total_running_ec2_instances += len(instances)

            for instance in instances:

                # ---------------------------------------------------------- #
                # Tag validation                                               #
                # ---------------------------------------------------------- #

                # Skip instances that have no tags attached
                if 'Tags' not in instance:
                    print('>find_running_ec2instances: instance has no tags, skipping – '
                          + instance['InstanceId'])
                    continue

                # Convert the raw Tags list [{"Key": ..., "Value": ...}, ...]
                # into a plain dict for O(1) lookups instead of repeated iteration.
                tags = {tag['Key']: tag['Value'] for tag in instance['Tags']}

                # Both SHUTDOWN and TEAM_LOCATION must be present to be eligible
                if 'SHUTDOWN' not in tags or 'TEAM_LOCATION' not in tags:
                    print('>find_running_ec2instances: missing required tags (SHUTDOWN / '
                          'TEAM_LOCATION), skipping – ' + instance['InstanceId'])
                    continue

                # Only manage instances belonging to the configured platform.
                # This prevents the Lambda from accidentally touching instances
                # from other projects that happen to share the same account.
                if tags.get('PLATFORM_TYPE') != constant.platform_type:
                    print('>find_running_ec2instances: PLATFORM_TYPE mismatch, skipping – '
                          + instance['InstanceId'])
                    continue

                # ---------------------------------------------------------- #
                # Extract display fields for the Slack notification            #
                # ---------------------------------------------------------- #

                # Use the value of the "Name" tag if present, otherwise fall back
                ec2_instance_name = tags.get('Name', 'No Name')

                # Point-of-contact tag – used so the Slack message shows who owns
                # the instance
                ec2_POC = tags.get('POC', 'No POC')

                shutdown_schedule = tags['SHUTDOWN']       # "DAILY" or "WEEKLY"
                team_location     = tags['TEAM_LOCATION']  # "INDIA" or "US"

                # ---------------------------------------------------------- #
                # Evaluate whether the instance should be stopped right now   #
                # ---------------------------------------------------------- #
                should_stop = False

                if shutdown_schedule == 'DAILY':
                    # Stop every calendar day once the team's stop-hour is reached.
                    # indiastoptime / usstoptime are both expressed as hours in IST.
                    if team_location == 'INDIA' and current_time.hour >= constant.indiastoptime:
                        should_stop = True
                    elif team_location == 'US' and current_time.hour >= constant.usstoptime:
                        should_stop = True

                elif shutdown_schedule == 'WEEKLY':
                    # Stop once per week: only on the configured day AND after
                    # the stop-hour so back-to-back Lambda runs on the same day
                    # don't attempt to stop an already-stopped instance.
                    if (team_location == 'INDIA'
                            and current_time.hour >= constant.indiastoptime
                            and current_time.strftime('%A') == constant.IndiaStopDay):
                        should_stop = True
                    elif (team_location == 'US'
                            and current_time.hour >= constant.usstoptime
                            and current_time.strftime('%A') == constant.UsStopDay):
                        should_stop = True

                if not should_stop:
                    # Instance tags are valid but the shutdown window hasn't
                    # opened yet (wrong hour or wrong day).
                    print('>find_running_ec2instances: shutdown window not open, skipping – '
                          + instance['InstanceId'])
                    continue

                # ---------------------------------------------------------- #
                # Stop the instance                                            #
                # ---------------------------------------------------------- #

                # Build the info string that will appear in the Slack message
                ec2_info = (
                    ':point_right: Region:' + region
                    + ', Name:' + ec2_instance_name
                    + ', POC:' + ec2_POC
                )

                print('>find_running_ec2instances: stopping instance – ' + ec2_info)

                try:
                    client.stop_instances(InstanceIds=[str(instance['InstanceId'])])
                    totalinstanceshutdown += 1
                    send_message_to_slack = 1
                    # Append the Instance ID after a successful stop so the Slack
                    # message contains a full audit trail.
                    ec2_info += ', InstanceId: ' + instance['InstanceId']
                except Exception as e:
                    # Log the error but continue processing the remaining instances
                    print('>find_running_ec2instances: failed to stop instance '
                          + instance['InstanceId'] + ' – ' + str(e))

                notification_message += ec2_info + '\n'

    # ---------------------------------------------------------------------- #
    # Slack notification                                                        #
    # ---------------------------------------------------------------------- #

    if send_message_to_slack > 0:
        # At least one instance was stopped – post the full summary to Slack
        print('>find_running_ec2instances: sending Slack notification')
        send_slack_message(constant.slack_webhook_url, notification_message)
    else:
        print('>find_running_ec2instances: no instances stopped – Slack notification skipped')

    print('>find_running_ec2instances: total instances shutdown=' + str(totalinstanceshutdown))

    return total_running_ec2_instances


# --------------------------------------------------------------------------- #
# Lambda entry point                                                            #
# --------------------------------------------------------------------------- #

def lambda_handler(event, context):
    """AWS Lambda entry point invoked by the CloudWatch Events cron rule.

    Calls find_running_ec2instances() to perform the shutdown logic, then
    publishes the count of stopped instances as a CloudWatch custom metric so
    you can build dashboards or alarms on top of it.

    Args:
        event   (dict): Lambda event payload. Minimal for cron triggers – not used.
        context (obj):  Lambda runtime context object – not used.

    Returns:
        dict: HTTP-style response containing statusCode 200 and a message with
              the total number of running instances found across all regions.
    """
    # Run the shutdown logic across all configured regions
    num_running_instances  = find_running_ec2instances()
    num_shutdown_instances = totalinstanceshutdown

    # Publish a custom CloudWatch metric so the shutdown count can be graphed
    # or used to trigger alarms (e.g. alert if unexpectedly many instances
    # are left running outside business hours).
    cloudwatch = boto3.client('cloudwatch')
    cloudwatch.put_metric_data(
        MetricData=[
            {
                'MetricName': 'DevInstanceShutDown',
                'Dimensions': [
                    {
                        'Name':  'DevInstanceShutDown',
                        'Value': 'InstanceCount',
                    },
                ],
                'Unit':  'None',
                'Value': num_shutdown_instances,
            },
        ],
        Namespace='ec2-auto-shutdown',
    )

    return {
        'statusCode': 200,
        'body': json.dumps(
            'Number of EC2 instances currently running in all regions: '
            + str(num_running_instances)
        ),
    }